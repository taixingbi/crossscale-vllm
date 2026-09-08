"""Wait for one smoke pod, failing early on repeated startup errors."""
import json
import subprocess
import time


def inspect(pod):
    status = pod.get('status', {})
    if any(c['type'] == 'Ready' and c['status'] == 'True' for c in status.get('conditions', [])):
        return True, 'Ready'
    states = []
    for container in status.get('initContainerStatuses', []) + status.get('containerStatuses', []):
        state = container.get('state', {})
        reason = state.get('waiting', {}).get('reason') or state.get('terminated', {}).get('reason') or 'Running'
        states.append(container['name'] + ': ' + reason)
        last = container.get('lastState', {}).get('terminated', {})
        if container.get('restartCount', 0) >= 2 and (reason == 'CrashLoopBackOff' or last.get('exitCode', 0) != 0):
            raise RuntimeError(container['name'] + ' repeatedly failed: ' + (last.get('reason') or reason))
        if reason in ('InvalidImageName', 'CreateContainerConfigError'):
            raise RuntimeError(container['name'] + ': ' + reason)
    return False, ', '.join(states) or status.get('phase', 'Pending')


def main():
    started = time.monotonic()
    image_error_since = None
    while time.monotonic() - started < 35 * 60:
        result = json.loads(subprocess.check_output(['kubectl', '-n', 'crossscale', 'get', 'pods', '-l', 'app=vllm', '-o', 'json']))
        pods = [p for p in result['items'] if not p['metadata'].get('deletionTimestamp')]
        states = [inspect(p) for p in pods]
        if len(states) == 1 and states[0][0]:
            print('One vLLM pod is ready', flush=True)
            return
        message = '; '.join(s[1] for s in states) or 'Waiting for pod'
        print(message, flush=True)
        if 'ImagePullBackOff' in message or 'ErrImagePull' in message:
            image_error_since = image_error_since or time.monotonic()
            if time.monotonic() - image_error_since > 180:
                raise RuntimeError('Image pull has failed repeatedly for three minutes')
        else:
            image_error_since = None
        time.sleep(15)
    raise TimeoutError('vLLM did not become ready within 35 minutes')


if __name__ == '__main__':
    main()
