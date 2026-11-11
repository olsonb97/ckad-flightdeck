"""Trigger and follow the destructive live self-test through the running local app."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

SMOKE=['d01','d06','p01','p06','p09','p10','o01','o03','o06','c04','c06','c11','n01','n09','n10']
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--all',action='store_true',help='Test all tasks in the selected scope (default)')
    group.add_argument('--smoke',action='store_true',help='Test 15 representative tasks')
    group.add_argument('--tasks',nargs='+',help='Test selected IDs, for example n08 n09 n10')
    parser.add_argument('--set',choices=['core','focused'],help='Limit cleanup and validation to one question set')
    parser.add_argument('--yes',action='store_true',help='Confirm deletion of question namespaces and task folders in the selected scope')
    parser.add_argument('--url',default='http://127.0.0.1:8080')
    args=parser.parse_args()
    if not args.yes:
        parser.error('--yes is required: the self-test clears question namespaces and task folders. Notes and past reports are retained.')
    def request(path,data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['X-CSRF-Token']=token
        req=urllib.request.Request(args.url+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
    try:
        state=request('/api/bootstrap')
        if not state['environment']['ready']:
            print('Cluster not ready:',state['environment'].get('error') or state['environment']['message'],file=sys.stderr);return 2
        if args.set and args.set not in state.get('sets',{}):
            print('The running app does not support this question set. Rebuild the app before validating it.',file=sys.stderr);return 2
        ids=SMOKE if args.smoke else args.tasks
        if args.set and ids is not None:
            allowed={task['id'] for task in state['tasks'] if task.get('set_id')==args.set}
            if any(tid not in allowed for tid in ids):
                print('Selected task IDs are outside the requested question set.',file=sys.stderr);return 2
        print('Starting live self-test. Question labs and task files in '+(args.set or 'all sets')+' will be reset.',flush=True)
        response=request('/api/selftest',{'confirm':True,'ids':ids,'set_id':args.set},state['csrf']);op_id=response['operation_id'];seen=0
        while True:
            state=request('/api/state');report=state.get('selftest') or {};op=state.get('operation') or {}
            for result in report.get('results',[])[seen:]:
                print(('PASS' if result['passed'] else 'FAIL')+' '+result['task_id']+' — '+result['title'],flush=True)
                if not result['passed']: print('  '+result.get('error',result.get('cleanup_error','Unknown failure')),flush=True)
                seen+=1
            if op.get('id')!=op_id: print('The self-test operation was replaced or the app restarted.',file=sys.stderr);return 2
            if op.get('state')=='error': print(op.get('error','Self-test error'),file=sys.stderr);return 2
            if op.get('state')=='done':
                print(f"\n{report.get('passed',0)}/{report.get('total',0)} tasks passed. Full report: /data/selftest-report.json",flush=True)
                return 0 if report.get('all_passed') else 1
            time.sleep(2)
    except urllib.error.HTTPError as exc:
        print('App rejected the request: '+exc.read().decode(errors='replace'),file=sys.stderr);return 2
    except (urllib.error.URLError,OSError,ValueError) as exc:
        print('Could not reach or read the app: '+str(exc),file=sys.stderr);return 2
    except KeyboardInterrupt:
        print('\nStopped watching. The self-test is still running in the app. Check Lab status.',file=sys.stderr);return 130
if __name__=='__main__': raise SystemExit(main())
