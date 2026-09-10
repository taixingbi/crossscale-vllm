"""Resume after diagnosed client timer lag, preserving the initial profile."""
import fcntl
import json
import os
from pathlib import Path
import sys

from crossscale.study import Study
from crossscale.episodes import save

class BoundedStudy(Study):
    def sweep(self, name, replicas, rates, duration=180):
        if name == 'profile-one':
            rates, duration = [.01, .015, .02, .025, .05, .075], 1800
        elif name == 'profile-one-low':
            raise RuntimeError('Corrected extended profile has no sustainable rate; retain and diagnose')
        return super().sweep(name + '-bounded', replicas, rates, duration)

if __name__ == '__main__':
    root = Path(sys.argv[1])
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (root/'study.pid').write_text(str(os.getpid()))
        study = BoundedStudy(root)
        try:
            proof=json.loads((root/'diagnosis-bounded-wait-load/complete.json').read_text())
            if proof['max_dispatch_lag_s'] > .05:
                raise RuntimeError('Bounded client diagnostic is not dispatch-valid')
            for name in ('cached-on-existing-node','cold-new-node','prebaked-image-new-node'):
                result=json.loads((root/'e0'/name/'summary.json').read_text())
                if result['episodes'] != 30 or result['failures']:
                    raise RuntimeError('E0 completion prerequisite failed')
            study.event('bounded-profile-continuation-start', rates=[.01,.015,.02,.025,.05,.075], duration_s=1800, seeds=[17,18,19])
            c=study.full_calibration()
            cold=json.loads((root/'e0/cold-new-node/summary.json').read_text())
            result=study.finish_comparisons(c,cold['training_p90_s'])
            study.event('requires-E3-E7' if result['continuation_gate']['trigger_e3_to_e7'] else 'measurement-suite-finished',external_cleanup_required=True)
        except Exception as exc:
            study.event('needs-diagnosis',error=repr(exc))
            raise
