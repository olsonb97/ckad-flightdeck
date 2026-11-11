"""Wait for actual lab readiness from a launcher, without exposing credentials."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def retry_failed_startup(remaining):
    deadline = time.monotonic()+remaining
    with urllib.request.urlopen('http://127.0.0.1:8080/api/bootstrap', timeout=min(5, remaining)) as response:
        data = json.load(response)
    request = urllib.request.Request('http://127.0.0.1:8080/api/retry', data=b'{}',
        headers={'Content-Type':'application/json', 'X-CSRF-Token':data['csrf']})
    with urllib.request.urlopen(request, timeout=min(5, max(.01, deadline-time.monotonic()))) as response:
        return response.status == 200


def wait_ready(timeout=720, *, fetch=None, retry=None, clock=time.monotonic, sleep=time.sleep, emit=print):
    deadline = clock() + timeout
    last = None
    if fetch is None:
        def fetch(remaining):
            with urllib.request.urlopen('http://127.0.0.1:8080/api/state', timeout=min(5, remaining)) as response:
                return json.load(response)['environment']
    while clock() < deadline:
        try:
            environment = fetch(max(.01, deadline-clock()))
            if environment.get('ready'):
                emit('Lab ready. Questions and terminals are available.')
                return 0
            if environment.get('phase') in ('error', 'unavailable'):
                if retry is not None and environment.get('phase') == 'error':
                    retry_once, retry = retry, None
                    if retry_once(max(.01, deadline-clock())):
                        emit('Rechecking the previous startup failure...')
                        continue
                emit('Lab startup failed: '+str(environment.get('error') or environment.get('message') or 'Unknown startup error.'))
                return 1
            message = environment.get('message') or 'Waiting for the lab...'
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as exc:
            message = 'Waiting for the app: '+str(exc)
        if message != last:
            emit(message)
            last = message
        sleep(min(2, max(0, deadline-clock())))
    emit('Lab startup timed out. Last status: '+str(last or 'The app did not respond.'))
    return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=720)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    try:
        sys.exit(wait_ready(args.timeout, retry=retry_failed_startup))
    except KeyboardInterrupt:
        sys.exit(130)
