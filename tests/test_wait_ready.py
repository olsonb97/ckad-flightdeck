import sys
from pathlib import Path
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
if not (Path(__file__).resolve().parents[1]/'app').exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wait_ready import wait_ready


class LauncherReadinessTests(unittest.TestCase):
    def test_app_responding_is_not_lab_ready(self):
        states = iter([{'ready':False,'phase':'starting','message':'Waiting for worker'}, {'ready':True}])
        messages = []
        self.assertEqual(wait_ready(fetch=lambda remaining: next(states), sleep=lambda seconds: None, emit=messages.append), 0)
        self.assertEqual(messages, ['Waiting for worker', 'Lab ready. Questions and terminals are available.'])

    def test_startup_failure_is_reported_without_retrying(self):
        def fetch(remaining):
            return {'ready':False,'phase':'error','error':'Worker registration rejected'}
        messages = []
        self.assertEqual(wait_ready(fetch=fetch, sleep=lambda seconds: self.fail('Failure must exit promptly'), emit=messages.append), 1)
        self.assertEqual(messages, ['Lab startup failed: Worker registration rejected'])

    def test_unresponsive_app_has_a_bounded_deadline(self):
        now = [0]
        remaining_times = []
        def fetch(remaining):
            remaining_times.append(remaining)
            raise urllib.error.URLError('Not listening')
        def sleep(seconds):
            now[0] += seconds
        messages = []
        self.assertEqual(wait_ready(3, fetch=fetch, clock=lambda:now[0], sleep=sleep, emit=messages.append), 1)
        self.assertEqual(now[0], 3)
        self.assertEqual(remaining_times, [3, 1])
        self.assertIn('Not listening', messages[-1])

    def test_launcher_rechecks_a_previous_failure_only_once(self):
        failures = []
        messages = []
        def retry(remaining):
            self.assertGreater(remaining, 0)
            failures.append(True)
            return True
        self.assertEqual(wait_ready(fetch=lambda remaining:{'ready':False,'phase':'error','error':'Still unavailable'},
            retry=retry, sleep=lambda seconds:None, emit=messages.append), 1)
        self.assertEqual(failures, [True])
        self.assertIn('Still unavailable', messages[-1])


if __name__ == '__main__':
    unittest.main()
