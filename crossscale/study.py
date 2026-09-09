"""Real full-workload calibration and paired baseline runs, with durable outputs."""
import asyncio
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .analysis import compare
from .core import quantile, summarize, workload
from .episodes import Episodes, Observer, save
from .kube import extract, ready
from .live import aio, events, run
from .telemetry import collect

MODEL = 'meta-llama/Llama-3.1-8B-Instruct'
SERVICE = 'http://vllm:8000'
PROMETHEUS = 'http://prometheus-operated.monitoring.svc:9090'


def prometheus(query):
    with urlopen(PROMETHEUS + '/api/v1/query?' + urlencode({'query': query}), timeout=20) as response:
        data = json.load(response)
    if data['status'] != 'success':
        raise RuntimeError('Prometheus query failed')
    return data['data']['result']


async def probe(specs, tokens, url=SERVICE):
    """Simultaneous isolated requests; used for warmup and admission calibration."""
    http = aio()
    async with http.ClientSession(timeout=http.ClientTimeout(total=180), connector=http.TCPConnector(limit=0, force_close=True)) as session:
        start = time.monotonic()

        async def send(spec):
            first, last, count, done = None, None, None, False
            row = dict(spec)
            body = dict(model=MODEL, prompt=tokens[:spec['input_tokens']], max_tokens=spec['output_tokens'],
                        temperature=0, ignore_eos=True, stream=True, stream_options={'include_usage': True})
            async with session.post(url + '/v1/completions', json=body) as response:
                if response.status != 200:
                    raise RuntimeError('probe failed: ' + (await response.text())[:1000])
                async for event in events(response):
                    now = time.monotonic()
                    done |= bool(event.get('done'))
                    if event.get('usage'):
                        count = event['usage'].get('completion_tokens')
                    if any(choice.get('text') for choice in event.get('choices', [])):
                        first = now if first is None else first
                        last = now
            if not done or count != spec['output_tokens'] or first is None:
                raise RuntimeError('incomplete probe response')
            row.update(ttft_s=first-start, tpot_s=(last-first)/(count-1), actual_output_tokens=count)
            return row
        return await asyncio.gather(*(send(spec) for spec in specs))


def paired_bootstrap(differences):
    if len(differences) < 5:
        return {'pairs': len(differences), 'mean': None, 'ci95': [None, None]}
    rng = random.Random(0)
    means = [sum(rng.choices(differences, k=len(differences)))/len(differences) for _ in range(10000)]
    return {'pairs': len(differences), 'mean': sum(differences)/len(differences), 'ci95': [quantile(means, .025), quantile(means, .975)]}


def continuation_gate(comparisons, b6_summaries):
    reasons = []
    for name in ('B3', 'ready-only'):
        comparison = comparisons[name]
        if comparison['pairs'] < 5:
            reasons.append(name + ': fewer than five complete pairs')
        if comparison['mean_wg_difference'] < .05:
            reasons.append(name + ': mean improvement below 0.05')
        lower = comparison['paired_bootstrap_95'][0]
        if lower is None or lower <= 0:
            reasons.append(name + ': confidence interval does not exclude zero')
    if len(b6_summaries) < 5:
        reasons.append('fewer than five B6 repetitions')
    for summary in b6_summaries:
        c = summary['tenants']['C']
        if c['goodput'] is None or c['goodput'] < .5:
            reasons.append('tenant C minimum goodput failed')
        if not c['offered'] or c['rejected']/c['offered'] > .5:
            reasons.append('tenant C rejection cap failed')
    return {'trigger_e3_to_e7': not reasons, 'reasons': sorted(set(reasons)),
            'status': 'triggered' if not reasons else 'not-triggered', 'threshold_wg_improvement': .05}


class Study:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.control = Episodes(self.root / 'e0')
        self.k = self.control.k
        self.config = json.loads((self.root / 'full-config.json').read_text())
        self.tokens = json.loads((self.root / 'tokens.json').read_text())

    def event(self, event, **kwargs):
        self.control.event(event, **kwargs)
        save(self.root / 'status.json', dict(unix_s=time.time(), event=event, **kwargs))

    def remove_scaler(self):
        scaler = self.k.get('scaledobject', 'vllm', missing_ok=True)
        if scaler:
            if scaler['metadata'].get('labels', {}).get('crossscale-experiment') != 'full-20260908':
                raise RuntimeError('refusing to remove a scaler not created by this study')
            self.k.request('DELETE', self.k.path('scaledobject', 'vllm'), {'preconditions': {'uid': scaler['metadata']['uid']}})
        deadline = time.monotonic() + 90
        while self.k.get('hpa')['items']:
            if time.monotonic() > deadline:
                raise RuntimeError('HPA remains after removing study scaler')
            time.sleep(2)

    def fixed(self, count):
        self.remove_scaler()
        if count == 1:
            original_nodes = {c.get('status', {}).get('nodeName') for c in self.control.claims()
                              if c['metadata']['name'] in self.control.ownership['initial_claims']}
            for pod in self.k.get('pods', selector='app=vllm')['items']:
                cost = '1000' if pod.get('spec', {}).get('nodeName') in original_nodes else '0'
                self.k.patch('pods', pod['metadata']['name'], {'metadata': {'annotations': {'controller.kubernetes.io/pod-deletion-cost': cost}}})
        self.k.scale(count)
        self.control.wait_ready(count)

    def idle(self, timeout=180):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            busy = False
            for pod in self.k.get('pods', selector='app=vllm')['items']:
                if not ready(pod):
                    continue
                with urlopen('http://' + pod['status']['podIP'] + ':8000/metrics', timeout=15) as response:
                    lines = response.read().decode().splitlines()
                values = [float(line.rsplit(' ', 1)[1]) for line in lines if line.startswith(('vllm:num_requests_running{', 'vllm:num_requests_waiting{'))]
                if len(values) < 2:
                    raise RuntimeError('installed serving metrics missing')
                busy |= any(values)
            if not busy:
                return
            time.sleep(3)
        raise TimeoutError('server still has outstanding work after drain')

    def warmup(self):
        self.idle()
        for pod in self.k.get('pods', selector='app=vllm')['items']:
            if ready(pod):
                for n in (256, 8192):
                    asyncio.run(probe([{'input_tokens': n, 'output_tokens': 32}], self.tokens, 'http://' + pod['status']['podIP'] + ':8000'))

    def sweep(self, name, replicas, rates, duration=180):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        self.fixed(replicas)
        self.control.cleanup_empty()
        records = []
        for rate in rates:
            for seed in (17, 18, 19):
                dest = folder / f'rps-{rate}-seed-{seed}'
                c = copy.deepcopy(self.config)
                c.update(seed=seed, initial_replicas=replicas, max_replicas=replicas, duration_s=duration)
                c['phases'] = [{'start_s': 0, 'rates': {'A': rate*4/7, 'B': rate*2/7, 'C': rate/7}}]
                expected = workload(c)
                if not all(any(r['tenant'] == t for r in expected) for t in c['tenants']):
                    raise RuntimeError('profile requires nonempty tenant samples; increase duration before measuring')
                if max(r['input_tokens']+r['output_tokens'] for r in expected) > 32768:
                    raise RuntimeError('sample exceeds serving context')
                if not (dest / 'complete.json').exists():
                    self.event('profile-run-start', name=name, rps=rate, seed=seed)
                    self.warmup()
                    with Observer(self.k, dest):
                        save(dest / 'cluster-before.json', self.k.snapshot())
                        summary = asyncio.run(run(c, 'B0', dest / 'run', SERVICE, MODEL, self.root / 'tokens.json'))
                        self.idle()
                        save(dest / 'cluster-after.json', self.k.snapshot())
                        collect(PROMETHEUS, summary['start_unix_s'], time.time(), 5, dest / 'telemetry')
                    save(dest / 'complete.json', {'completed_unix_s': time.time()})
                summary = json.loads((dest / 'run' / 'summary.json').read_text())
                rows = [json.loads(line) for line in (dest / 'run' / 'requests.jsonl').read_text().splitlines()]
                valid = max(r.get('dispatch_lag_s', 0) for r in rows) <= .05
                passed = valid and all(t['goodput'] is not None and t['goodput'] >= .95 for t in summary['tenants'].values())
                records.append({'rps': rate, 'seed': seed, 'passed': passed, 'dispatch_valid': valid, 'summary': summary})
                save(folder / 'progress.json', records)
                self.event('profile-run-complete', name=name, rps=rate, seed=seed, passed=passed, wg=summary['weighted_slo_goodput'])
        sustainable = None
        for rate in sorted(rates):
            if all(r['passed'] for r in records if r['rps'] == rate):
                sustainable = rate
            else:
                break
        result = dict(replicas=replicas, sustainable_rps=sustainable, target=.95, results=records, duration_s=duration)
        save(folder / 'summary.json', result)
        return result

    def admission_calibration(self):
        path = self.root / 'admission-calibration.json'
        if path.exists():
            existing = json.loads(path.read_text())
            if existing['slots_per_replica'] is None:
                raise RuntimeError('saved isolated concurrency calibration failed; investigate before continuing')
            return existing
        self.fixed(1)
        self.warmup()
        isolated = []
        for repeat in range(3):
            for n in (256, 3072, 8192):
                isolated.extend(asyncio.run(probe([{'input_tokens': n, 'output_tokens': 2}], self.tokens)))
        # Retain a conservative empirical throughput estimate including overhead.
        throughput = quantile([r['input_tokens']/r['ttft_s'] for r in isolated], .1)
        concurrency = []
        slots = None
        tenants = list(self.config['tenants'])
        for size in (1, 2, 4):
            passed = True
            for repeat in range(3):
                specs = []
                for i in range(size):
                    tenant = tenants[(i+repeat) % 3]
                    t = self.config['tenants'][tenant]
                    specs.append({'tenant': tenant, 'input_tokens': t['input_median'], 'output_tokens': t['output_median']})
                rows = asyncio.run(probe(specs, self.tokens))
                good = all(r['ttft_s'] <= self.config['tenants'][r['tenant']]['ttft_s'] and r['tpot_s'] <= self.config['tenants'][r['tenant']]['tpot_s'] for r in rows)
                concurrency.append({'size': size, 'repeat': repeat, 'passed': good, 'requests': rows})
                passed &= good
            if passed and (size == 1 or slots is not None):
                slots = size
            else:
                break
        result = {'prefill_tokens_s': throughput, 'slots_per_replica': slots, 'isolated': isolated, 'concurrency': concurrency,
                  'limitation': 'conservative sampled admission calibration, not a general service model'}
        save(path, result)
        if slots is None:
            raise RuntimeError('even isolated concurrency calibration failed tenant SLOs')
        return result

    def install_scaler(self, baseline, threshold=1):
        metric_type = 'AverageValue' if baseline == 'B2' else 'Value'
        query = 'sum(vllm:num_requests_waiting{namespace="crossscale"})' if baseline == 'B2' else 'max(crossscale_slo_saturation{job="crossscale-gateway"})'
        body = {'apiVersion': 'keda.sh/v1alpha1', 'kind': 'ScaledObject',
                'metadata': {'name': 'vllm', 'namespace': 'crossscale', 'labels': {'crossscale-experiment': 'full-20260908'}},
                'spec': {'scaleTargetRef': {'name': 'vllm'}, 'pollingInterval': 5, 'minReplicaCount': 2, 'maxReplicaCount': 4,
                         'advanced': {'horizontalPodAutoscalerConfig': {'behavior': {'scaleUp': {'stabilizationWindowSeconds': 0}, 'scaleDown': {'selectPolicy': 'Disabled'}}}},
                         'triggers': [{'type': 'prometheus', 'metricType': metric_type, 'metadata': {'serverAddress': PROMETHEUS,
                                       'query': query, 'threshold': '5' if baseline == 'B2' else str(threshold), 'ignoreNullValues': 'false'}}]}}
        self.k.request('POST', self.k.path('scaledobject'), body)

    def baseline_run(self, folder, baseline, seed, c, eta, matched=False):
        dest = Path(folder) / str(seed) / baseline
        if (dest / 'complete.json').exists():
            if not json.loads((dest / 'complete.json').read_text())['dispatch_valid']:
                raise RuntimeError('saved run is dispatch-invalid; investigate before continuing')
            return json.loads((dest / 'run' / 'summary.json').read_text())
        self.event('baseline-start', baseline=baseline, seed=seed, matched=matched)
        self.remove_scaler()
        self.control.baseline()
        self.control.cleanup_empty()
        fixed = baseline in ('B0', 'B1', 'B4')
        if baseline == 'B1':
            self.fixed(4)
        self.warmup()
        c = copy.deepcopy(c)
        c.update(seed=seed, initial_replicas=4 if baseline == 'B1' else 2, max_replicas=(4 if baseline == 'B1' else 2) if fixed else 4)
        gateway = None
        with Observer(self.k, dest, eta) as observer:
            save(dest / 'config.json', c)
            save(dest / 'before.json', self.k.snapshot())
            log = (dest / 'gateway.log').open('w')
            try:
                gateway = subprocess.Popen([sys.executable, '-m', 'crossscale.cli', 'gateway', '--config', str(dest/'config.json'),
                                           '--baseline', baseline, '--state', str(dest/'state.json'), '--url', SERVICE, '--host', '0.0.0.0'], stdout=log, stderr=log)
                deadline = time.monotonic() + 60
                while True:
                    if gateway.poll() is not None:
                        raise RuntimeError('gateway exited during startup')
                    try:
                        with urlopen('http://127.0.0.1:8080/metrics', timeout=2):
                            pass
                        up = prometheus('up{job="crossscale-gateway"}')
                        if up and all(float(x['value'][1]) == 1 for x in up) and not prometheus('crossscale_slo_saturation{job="crossscale-gateway"}'):
                            break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError('gateway not freshly scraped by Prometheus')
                    time.sleep(2)
                if not fixed and not matched:
                    self.install_scaler(baseline, c.get('slo_threshold', 1))
                save(dest / 'scaler-before.json', {'scaledobject': self.k.get('scaledobject', 'vllm', missing_ok=True), 'hpa': self.k.get('hpa')})

                async def measured():
                    load = asyncio.create_task(run(c, baseline, dest/'run', 'http://127.0.0.1:8080', MODEL, self.root/'tokens.json'))
                    if matched:
                        await asyncio.sleep(60)
                        self.k.scale(4)
                    return await load

                summary = asyncio.run(measured())
                self.idle()
                # Keep capacity observations for the complete configured drain.
                until = summary['start_unix_s'] + c['duration_s'] + c['drain_s']
                while time.time() < until:
                    time.sleep(min(5, until-time.time()))
                save(dest / 'after.json', self.k.snapshot())
                save(dest / 'scaler-after.json', {'scaledobject': self.k.get('scaledobject', 'vllm', missing_ok=True), 'hpa': self.k.get('hpa')})
                collect(PROMETHEUS, summary['start_unix_s'], time.time(), 5, dest/'telemetry')
            finally:
                if gateway is not None:
                    gateway.terminate()
                    try:
                        gateway.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        gateway.kill()
                        gateway.wait()
                log.close()
                self.remove_scaler()
            if observer.error:
                raise RuntimeError(observer.error)
        rows = [json.loads(line) for line in (dest/'run'/'requests.jsonl').read_text().splitlines()]
        burst = summarize([r for r in rows if 60 <= r['offered_s'] < 180], dict(c, duration_s=120))
        save(dest/'burst-summary.json', burst)
        save(dest/'scale-summary.json', extract(dest/'observations.jsonl.gz'))
        valid = max((r.get('dispatch_lag_s', 0) for r in rows), default=0) <= .05
        save(dest/'complete.json', {'dispatch_valid': valid, 'completed_unix_s': time.time(), 'matched_schedule': matched})
        self.event('baseline-complete', baseline=baseline, seed=seed, wg=summary['weighted_slo_goodput'], dispatch_valid=valid, matched=matched)
        if not valid:
            raise RuntimeError('client dispatch lag exceeded predeclared limit; retain and investigate run')
        return summary

    def full_calibration(self):
        path = self.root / 'calibrated-config.json'
        if path.exists():
            return json.loads(path.read_text())
        self.k.patch('nodepool', 'crossscale-gpu', {'spec': {'template': {'spec': {'nodeClassRef': {'group': 'karpenter.k8s.aws', 'kind': 'EC2NodeClass', 'name': 'crossscale-gpu'}}}}})
        one = self.sweep('profile-one', 1, [.1, .2, .3, .4, .6, .8])
        single_rps = one['sustainable_rps']
        if single_rps is None:
            lower = self.sweep('profile-one-low', 1, [.025, .05, .075], duration=720)
            single_rps = lower['sustainable_rps']
        if single_rps is None:
            self.event('full-workload-feasibility-failed', reason='no passing single-GPU rate')
            raise RuntimeError('no full-workload rate meets all tenant SLOs; preserve results and diagnose serving feasibility')
        admission = self.admission_calibration()
        two_rates = [round(single_rps*factor, 8) for factor in (1.3, 2.0, 2.5)]
        two = self.sweep('profile-two', 2, two_rates)
        if two['sustainable_rps'] is None:
            two = self.sweep('profile-two-low', 2, [round(single_rps*factor, 8) for factor in (.5, .8, 1.0)], duration=360)
        if two['sustainable_rps'] is None:
            raise RuntimeError('no passing two-GPU profile rate; diagnose before generating experiments')
        c = copy.deepcopy(self.config)
        c.update(slots_per_replica=admission['slots_per_replica'], prefill_tokens_s=admission['prefill_tokens_s'])
        c['calibration'] = {'single_gpu_rps': single_rps, 'two_gpu_rps': two['sustainable_rps'],
                            'observed_scaling_efficiency': two['sustainable_rps']/(2*single_rps),
                            'source': 'full-workload measured profiles; no linear scaling assumption'}
        for phase, factor in zip(c['phases'], (.65, 1.65, .65)):
            total = two['sustainable_rps'] * factor
            phase['rates'] = {'A': total*4/7, 'B': total*2/7, 'C': total/7}
        save(path, c)
        self.event('full-calibration-complete', **c['calibration'])
        return c

    def comparison_plan(self, c):
        path = self.root / 'comparison-plan.json'
        if path.exists():
            return json.loads(path.read_text())
        # Select traces before running any baseline, based only on offered data.
        seeds, examined = [], []
        for seed in range(101, 1001):
            rows = workload(dict(c, seed=seed))
            counts = {t: sum(r['tenant'] == t for r in rows) for t in c['tenants']}
            examined.append({'seed': seed, 'counts': counts})
            if all(counts.values()):
                seeds.append(seed)
            if len(seeds) == 5:
                break
        if len(seeds) < 5:
            raise RuntimeError('unable to construct five informative paired traces')
        rng = random.Random(20260908)
        pairs = [(seed, b) for seed in seeds for b in ['B0', 'B1', 'B2', 'B3', 'B4', 'B5', 'ready-only', 'B6']]
        rng.shuffle(pairs)
        matched = [(seed, b) for seed in seeds for b in ['B3', 'ready-only', 'B6']]
        rng.shuffle(matched)
        result = {'seeds': seeds, 'trace_selection': examined, 'e2_order': pairs, 'matched_order': matched,
                  'matched_scale_at_s': 60, 'limitation': 'Poisson traces conditioned on nonempty tenant samples, selected without outcome data'}
        save(path, result)
        return result

    def finish_comparisons(self, c, eta):
        plan = self.comparison_plan(c)
        tuned_path = self.root / 'slo-tuning.json'
        if tuned_path.exists():
            tuning = json.loads(tuned_path.read_text())
        else:
            candidates = []
            for threshold in (.8, 1.0, 1.2):
                config = dict(c, slo_threshold=threshold)
                summaries = [self.baseline_run(self.root/'slo-tuning'/str(threshold), 'B3', seed, config, eta) for seed in (501, 502)]
                scores = [s['weighted_slo_goodput'] for s in summaries]
                candidates.append({'threshold': threshold, 'mean_wg': sum(scores)/len(scores) if all(x is not None for x in scores) else None})
            viable = [x for x in candidates if x['mean_wg'] is not None]
            if not viable:
                raise RuntimeError('SLO tuning traces have missing tenant samples')
            selected = max(viable, key=lambda x: (x['mean_wg'], -abs(x['threshold']-1)))
            tuning = {'selected_threshold': selected['threshold'], 'candidates': candidates, 'training_seeds': [501, 502]}
            save(tuned_path, tuning)
        c = dict(c, slo_threshold=tuning['selected_threshold'])
        save(self.root/'comparison-config.json', c)
        for seed in plan['seeds']:
            for baseline in ('B2', 'B3'):
                self.baseline_run(self.root/'E1', baseline, seed, c, eta)
        for seed, baseline in plan['e2_order']:
            self.baseline_run(self.root/'E2', baseline, seed, c, eta)
        for seed, baseline in plan['matched_order']:
            self.baseline_run(self.root/'matched-scale', baseline, seed, c, eta, matched=True)
        comparisons = {b: compare([self.root/'E2'], 'B6', b) for b in ('B3', 'ready-only')}
        matched = {b: compare([self.root/'matched-scale'], 'B6', b) for b in ('B3', 'ready-only')}
        b6 = [json.loads((self.root/'E2'/str(seed)/'B6'/'run'/'summary.json').read_text()) for seed in plan['seeds']]
        burst = {}
        for comparator in ('B3', 'ready-only'):
            differences = []
            for seed in plan['seeds']:
                l = json.loads((self.root/'E2'/str(seed)/'B6'/'burst-summary.json').read_text())['weighted_slo_goodput']
                r = json.loads((self.root/'E2'/str(seed)/comparator/'burst-summary.json').read_text())['weighted_slo_goodput']
                if l is not None and r is not None:
                    differences.append(l-r)
            burst[comparator] = paired_bootstrap(differences)
        gate = continuation_gate(comparisons, b6)
        result = {'whole_run_comparisons': comparisons, 'burst_comparisons': burst, 'matched_scale_comparisons': matched, 'continuation_gate': gate}
        save(self.root/'E2-analysis.json', result)
        self.event('E2-complete', gate=gate)
        self.fixed(1)
        self.control.cleanup_empty()
        self.k.patch('nodepool', 'crossscale-gpu', {'spec': {'limits': {'nvidia.com/gpu': '1'}}})
        return result


def main():
    import argparse
    import fcntl
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    args = p.parse_args()
    root = Path(args.root)
    with (root/'suite.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        study = Study(root)
        try:
            cached = root/'e0'/'cached-on-existing-node'/'summary.json'
            while not cached.exists():
                pid = int((root/'cached.pid').read_text())
                process = Path(f'/proc/{pid}/stat')
                if not process.exists() or process.read_text().rsplit(')', 1)[1].split()[0] == 'Z':
                    raise RuntimeError('cached E0 worker exited before completion; inspect e0-cached.log')
                study.event('waiting-for-cached-E0')
                time.sleep(30)
            study.control.condition('cold-new-node', 'crossscale-gpu')
            study.control.condition('prebaked-image-new-node', 'crossscale-gpu-prebaked')
            cold = json.loads((root/'e0'/'cold-new-node'/'summary.json').read_text())
            if cold['training_completed'] < 20 or cold['heldout_completed'] < 10:
                raise RuntimeError('E0 has censored data; assess ETA calibration before continuing')
            c = study.full_calibration()
            result = study.finish_comparisons(c, cold['training_p90_s'])
            study.event('requires-E3-E7' if result['continuation_gate']['trigger_e3_to_e7'] else 'measurement-suite-finished',
                        external_cleanup_required=True)
        except Exception as exc:
            study.event('needs-diagnosis', error=repr(exc))
            raise


if __name__ == '__main__':
    main()
