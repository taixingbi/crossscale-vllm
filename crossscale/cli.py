import argparse
import asyncio
import copy
import json
from pathlib import Path

from .core import BASELINES, config, workload


def main():
    p = argparse.ArgumentParser(description="CrossScale experiment harness")
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("trace", "simulate", "matrix", "live", "gateway", "calibrate", "profile"):
        s = sub.add_parser(command)
        s.add_argument("--config", default="configs/default.json")
        if command not in ("gateway",):
            s.add_argument("--out", required=True)
        if command in ("simulate", "live", "gateway"):
            s.add_argument("--baseline", choices=BASELINES, default="B6")
        if command in ("live", "gateway", "profile"):
            s.add_argument("--url", required=True)
        if command in ("live", "profile"):
            s.add_argument("--model", required=True)
            s.add_argument("--tokens", required=True)
        if command == "profile":
            s.add_argument("--rates", type=float, nargs="+", required=True)
            s.add_argument("--seeds", type=int, nargs="+", default=[17, 18, 19])
            s.add_argument("--duration", type=float, default=180)
            s.add_argument("--target", type=float, default=.95)
        if command == "gateway":
            s.add_argument("--state", required=True)
            s.add_argument("--host", default="127.0.0.1")
            s.add_argument("--port", type=int, default=8080)
        if command == "matrix":
            s.add_argument("--experiment", choices=["E2", "E3", "E4", "E5", "E6", "E7"], default="E2")
            s.add_argument("--seeds", type=int, nargs="+", default=[17, 18, 19])
        if command == "calibrate":
            s.add_argument("--replica-rps", type=float, required=True)
    s = sub.add_parser("compare")
    s.add_argument("paths", nargs="+")
    s.add_argument("--left", default="B6")
    s.add_argument("--right", default="ready-only")
    s = sub.add_parser("observe")
    for key in ("context", "namespace", "deployment", "selector", "out"):
        s.add_argument("--"+key, required=True)
    s.add_argument("--duration", type=float, default=600)
    s.add_argument("--interval", type=float, default=1)
    s.add_argument("--eta", type=float, required=True, help="held-out E0 startup P90 seconds; never future test data")
    s = sub.add_parser("e0-summary")
    s.add_argument("path")
    a = p.parse_args()
    if a.command == "compare":
        from .analysis import compare
        print(json.dumps(compare(a.paths, a.left, a.right), indent=2))
        return
    if a.command == "observe":
        from .kube import observe
        if min(a.duration, a.interval, a.eta) <= 0:
            p.error("duration, interval and eta must be positive")
        observe(a.context, a.namespace, a.deployment, a.selector, a.out, a.duration, a.interval, a.eta)
        return
    if a.command == "e0-summary":
        from .kube import extract
        print(json.dumps(extract(a.path), indent=2))
        return
    c = config(a.config)
    if a.command == "trace":
        with Path(a.out).open("x") as f:
            f.write("".join(json.dumps(r)+"\n" for r in workload(c)))
    elif a.command == "calibrate":
        if a.replica_rps <= 0:
            p.error("replica-rps must be positive")
        mix = c["phases"][0]["rates"]
        total = sum(mix.values())
        for phase, factor in zip(c["phases"], [.65, 1.65, .65]):
            phase["rates"] = {t: v/total*a.replica_rps*c["initial_replicas"]*factor for t, v in mix.items()}
        c["calibration"] = {"single_replica_sustainable_rps": a.replica_rps, "source": "user supplied measured saturation; fixed tenant mix"}
        with Path(a.out).open("x") as f:
            json.dump(c, f, indent=2)
    elif a.command == "simulate":
        from .sim import run
        print(json.dumps(run(c, a.baseline, a.out), indent=2))
    elif a.command == "matrix":
        from .sim import run
        baselines = list(BASELINES[:7]) + ["ready-only"]
        settings = [("default", {})]
        if a.experiment == "E3":
            c["phases"][1]["rates"] = dict(c["phases"][0]["rates"])
            c["phases"][1]["rates"]["C"] *= 5
        if a.experiment == "E4":
            settings = [(f"lag-{lag}", {"provisioning_lag_s": lag}) for lag in [0, 15, 30, 60, 90, 120]]
        if a.experiment == "E5":
            baselines = ["B3", "B5", "ready-only", "B6", "oracle-eta"]
            settings = [(f"error-{err}", {"eta_error": err}) for err in [-1, -.5, -.25, 0, .25, .5, 1]]
        if a.experiment == "E6":
            baselines = ["B2", "ready-only", "no-tenant", "B6", "oracle-eta"]
        if a.experiment == "E7":
            c["duration_s"] = 3600
            normal = c["phases"][0]["rates"]
            c["phases"] = [{"start_s": i*600, "rates": {t: r*factor for t, r in normal.items()}} for i, factor in enumerate([1, 2.5, 1, 1.8, 2.5, 1])]
        for seed in a.seeds:
            for label, update in settings:
                for baseline in baselines:
                    cc = copy.deepcopy(c)
                    cc.update(update, seed=seed)
                    dest = Path(a.out)/a.experiment/label/str(seed)/baseline
                    run(cc, baseline, dest)
        print(f"Synthetic matrix written to {a.out}; no production claims supported.")
    elif a.command == "profile":
        from .profile import sweep
        report = asyncio.run(sweep(c, a.out, a.url, a.model, a.tokens, a.rates, a.seeds, a.duration, a.target))
        print(json.dumps({"sustainable_rps": report["sustainable_rps"], "out": a.out}))
    elif a.command == "live":
        from .live import run
        print(json.dumps(asyncio.run(run(c, a.baseline, a.out, a.url, a.model, a.tokens)), indent=2))
    elif a.command == "gateway":
        if a.baseline == "oracle-eta":
            p.error("oracle ETA is simulation-only; use prerecorded controlled readiness for a real oracle")
        from .live import gateway
        asyncio.run(gateway(c, a.baseline, a.state, a.url, a.host, a.port))


if __name__ == "__main__":
    main()
