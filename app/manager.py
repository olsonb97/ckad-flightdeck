"""Persistent study state, server-timed mocks, and a live all-task self-test."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import secrets
import time
from bank import BANK,ACTIVE_BANK,DOMAINS,SETS,BANK_VERSION,set_tasks
from runtime import Runner,Grader,InfrastructureError
from labops import LabOperations
from tutor import study_guide, learning_feedback

PUBLIC_FIELDS=('id','set_id','title','domain','level','minutes','namespace','context','requirements','docs','workspace')

class BusyError(RuntimeError): pass

class Manager:
    def __init__(self,runner,state_dir):
        self.runner=runner; self.ops=LabOperations(runner); self.directory=Path(state_dir); self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'state.json'; self.state=self.load_state()
        self.environment={'ready':False,'phase':'starting','message':'Starting the local lab…','checks':{},'version':None,'error':None}
        self.operation=None; self.job=None; self.terminals=None; self.closed=False
        self.selftest=None
        report=self.directory/'selftest-report.json'
        if report.exists():
            try: self.selftest=json.loads(report.read_text())
            except (ValueError,OSError): pass
    def load_state(self):
        default={'schema':1,'practice':{},'exam':None,'history':[]}
        if not self.path.exists(): return default
        try:
            value=json.loads(self.path.read_text())
            if not isinstance(value,dict) or value.get('schema')!=1: raise ValueError('Unknown state schema')
            for key,val in default.items(): value.setdefault(key,val)
            if not isinstance(value['practice'],dict) or any(not isinstance(p,dict) for p in value['practice'].values()): raise ValueError('Invalid practice state')
            if not isinstance(value['history'],list): raise ValueError('Invalid history')
            exam=value['exam']
            if isinstance(exam,dict) and exam.get('state') in ('preparing','grading'): exam.setdefault('tasks',[])
            if exam is not None and (not isinstance(exam,dict) or not isinstance(exam.get('tasks'),list) or any(not isinstance(t,str) or t not in BANK for t in exam['tasks'])): raise ValueError('Invalid exam state')
            if exam and exam.get('state') in ('running','expired') and (type(exam.get('deadline')) not in (float,int)): raise ValueError('Invalid exam deadline')
            if value['exam'] and value['exam'].get('state') in ('preparing','grading'):
                value['exam']['state']='interrupted'
                value['exam']['error']='The app restarted during preparation or grading; this attempt has no valid final score.'
            return value
        except (ValueError,OSError):
            backup=self.path.with_name('state-unreadable-'+str(int(time.time()))+'.json')
            try: self.path.rename(backup)
            except OSError: pass
            return default
    @staticmethod
    def atomic(path,value):
        temp=path.with_suffix(path.suffix+'.tmp')
        with temp.open('w') as f:
            json.dump(value,f,indent=2); f.flush(); os.fsync(f.fileno())
        temp.replace(path)
    def save(self): self.atomic(self.path,self.state)
    def busy(self): return bool(self.operation and self.operation.get('state')=='running')
    def locked(self):
        if self.busy() and self.operation['kind'] in ('prepare','reset','exam_prepare','selftest','clean'): return True
        exam=self.state.get('exam')
        return bool(exam and (exam.get('state') in ('preparing','grading','expired') or (exam.get('state')=='running' and time.time()>=exam['deadline'])))
    def exam_active(self):
        exam=self.state.get('exam')
        return bool(exam and exam.get('state') in ('running','preparing','grading','expired'))
    def require_environment(self):
        if not self.environment.get('ready'): raise InfrastructureError('The live cluster is not ready. Open Lab status for the initialization result.')
    def require_practice(self):
        if self.exam_active(): raise BusyError('This action is unavailable during a timed mock. Submit or abandon the mock first.')
    def public_task(self,task):
        return {**{k:task[k] for k in PUBLIC_FIELDS},'starter_files':[task['workspace']+'/'+x for x in task['files']],
                'practice_checks':[c['label'] for c in task['checks']],
                'progress':deepcopy(self.state['practice'].get(task['id'],{}))}
    def snapshot(self):
        exam=deepcopy(self.state.get('exam')); active=self.exam_active()
        visible={**ACTIVE_BANK,**{tid:BANK[tid] for tid in (exam or {}).get('tasks',[])}}
        tasks=[self.public_task(t) for t in visible.values()]
        operation=deepcopy(self.operation)
        # Never leak criteria results through state during an active exam.
        if active:
            exam.pop('results',None)
            for task in tasks:
                task['progress']={key:value for key,value in task['progress'].items() if key in ('prepared','flagged')}
                task.pop('practice_checks',None)
                task.pop('docs',None)
            if operation: operation.pop('result',None)
        return {'tasks':tasks,'sets':deepcopy(SETS),'domains':DOMAINS,'environment':deepcopy(self.environment),'operation':operation,
          'exam':exam,'history':[] if active else deepcopy(self.state['history'][-20:]),'server_time':time.time(),'terminal_locked':self.locked(),
          'selftest':None if active else deepcopy(self.selftest),'meta':{'name':'CKAD Flightdeck','bank_version':BANK_VERSION,'target_kubernetes':'1.35','questions':len(ACTIVE_BANK),'criteria':sum(len(t['checks']) for t in ACTIVE_BANK.values()),'exam_minutes':120,'mock_tasks':20,'reference_pass_percent':66}}
    def start_action(self,kind,worker):
        if self.busy(): raise BusyError('Another lab operation is already in progress.')
        op={'id':secrets.token_hex(6),'kind':kind,'state':'running','message':'Starting…','current':0,'total':1,'started_at':time.time()}
        self.operation=op
        async def wrapped():
            try:
                result=await worker(op)
                op.update(state='done',result=result,message='Complete',finished_at=time.time())
            except asyncio.CancelledError:
                op.update(state='error',error='Operation interrupted by server shutdown.'); raise
            except Exception as exc:
                op.update(state='error',error=str(exc),message='Operation needs attention',finished_at=time.time())
                exam=self.state.get('exam')
                if kind=='selftest' and self.selftest:
                    self.selftest.update(state='error',error=str(exc),finished_at=time.time()); self.atomic(self.directory/'selftest-report.json',self.selftest)
                if kind in ('exam_prepare','exam_submit') and exam:
                    exam.update(state='interrupted',error=str(exc)); self.save()
        self.job=asyncio.create_task(wrapped())
        return {'operation_id':op['id']}
    async def prepare(self,tid,reset=False):
        self.require_environment(); self.require_practice()
        if self.busy(): raise BusyError('Another question is being prepared.')
        task=BANK[tid]
        if self.state['practice'].get(tid,{}).get('prepared') and not reset:
            names=self.ops.namespaces(task)
            result=await self.runner.k('get','namespace',*names,'--ignore-not-found=true','-o','name')
            if result.code: raise InfrastructureError('Could not check the question namespace.')
            if len(result.out.splitlines())==len(names) and self.runner.map_path(task['workspace']).is_dir():
                return {'already_prepared':True,'task_id':tid}
        async def work(op):
            op.update(message='Preparing question…',task_id=tid)
            if reset and self.terminals: self.terminals.stop_all()
            # Invalidate before destructive setup; even a partial reset failure
            # must not leave a ready badge or a grade from the previous lab.
            progress=self.state['practice'].setdefault(tid,{})
            progress['prepared']=False; progress.pop('last_grade',None); progress.pop('step_checks',None); self.save()
            await self.ops.setup(task,reset=reset)
            progress.update(prepared=True,started_at=time.time())
            if reset: progress.pop('last_grade',None)
            self.save(); return {'task_id':tid}
        return self.start_action('reset' if reset else 'prepare',work)
    def grade(self,tid,criterion=None):
        self.require_environment(); self.require_practice()
        if not self.state['practice'].get(tid,{}).get('prepared'): raise BusyError('Start the question lab before checking it.')
        task=BANK[tid]
        if criterion is not None and (type(criterion) is not int or not 0 <= criterion < len(task['checks'])):
            raise ValueError('Choose a valid practice checkpoint.')
        indices=[criterion] if criterion is not None else list(range(len(task['checks'])))
        checks=[task['checks'][i] for i in indices]
        async def work(op):
            op['message']='Checking: '+checks[0]['label'] if criterion is not None else 'Checking live Kubernetes objects and runtime behavior…'
            result=await Grader(self.runner,{**task,'checks':checks,'selection_checks':task['checks']}).grade(); result['checked_at']=time.time()
            progress=self.state['practice'].setdefault(tid,{})
            for i,item in zip(indices,result['criteria']):
                item['feedback']=learning_feedback(task,task['checks'][i],item['status'])
                progress.setdefault('step_checks',{})[str(i)]={**item,'checked_at':result['checked_at']}
            if criterion is None:
                progress['last_grade']=result; progress['checks']=progress.get('checks',0)+1
            else: result['criterion']=criterion
            self.save(); return result
        return self.start_action('check_step' if criterion is not None else 'grade',work)
    def save_notes(self,tid,notes=None,flag=None):
        if notes is not None: self.require_practice()
        progress=self.state['practice'].setdefault(tid,{})
        if notes is not None: progress['notes']=str(notes)[:12000]
        if flag is not None: progress['flagged']=bool(flag)
        self.save(); return {'ok':True}
    def reveal(self,tid,which):
        self.require_practice()
        progress=self.state['practice'].setdefault(tid,{})
        if which=='solution':
            progress['solution_seen']=True; self.save()
            return {'solution':BANK[tid]['solution'],'explanation':BANK[tid]['explanation'],'guide':study_guide(BANK[tid])}
        count=min(progress.get('hints_seen',0)+1,len(BANK[tid]['hints']))
        progress['hints_seen']=count; self.save()
        return {'hints':BANK[tid]['hints'][:count]}
    @staticmethod
    def choose_exam(seed,set_id='core'):
        tasks=set_tasks(set_id); rng=random.Random(seed); chosen=[]
        if SETS[set_id]['weighted']:
            for domain,data in DOMAINS.items():
                pool=[t['id'] for t in tasks if t['domain']==domain]
                chosen+=rng.sample(pool,data['weight']//5)
        else: chosen=[t['id'] for t in tasks]
        rng.shuffle(chosen)
        return chosen
    def start_exam(self,seed=None,set_id='core'):
        self.require_environment(); self.require_practice()
        scope=set_tasks(set_id)
        seed=str(seed or secrets.token_hex(4))[:80]
        ids=self.choose_exam(seed,set_id); points=100/len(ids); duration=SETS[set_id]['exam_minutes']*60
        weights={domain:round(sum(points for tid in ids if BANK[tid]['domain']==domain),2) for domain in DOMAINS}
        exam={'id':secrets.token_hex(6),'set_id':set_id,'seed':seed,'tasks':ids,'task_points':points,'domain_weights':weights,'state':'preparing','created_at':time.time(),'duration_seconds':duration,'prepared':0,'results':{}}
        async def work(op):
            if self.terminals: self.terminals.stop_all()
            self.state['exam']=exam; self.save()
            op.update(message='Resetting the selected question set…',total=len(ids),current=0)
            for task in scope:
                p=self.state['practice'].get(task['id'],{})
                p['prepared']=False; p.pop('step_checks',None)
            self.save()
            await self.ops.clean_all(scope)
            for i,tid in enumerate(ids):
                op.update(current=i,message=f'Preparing task {i+1}/{len(ids)}: '+BANK[tid]['title'])
                await self.ops.setup(BANK[tid],reset=False)
                self.state['practice'].setdefault(tid,{})['prepared']=True
                exam['prepared']=i+1; self.save()
            now=time.time(); exam.update(state='running',started_at=now,deadline=now+duration)
            op['current']=len(ids); self.save()
            return {'exam_id':exam['id']}
        return self.start_action('exam_prepare',work)
    @staticmethod
    def exam_score(results,points=5):
        # Exactly twenty tasks × five points: domain weights match 20/20/15/25/20.
        score=sum(points*r['earned']/r['possible'] for r in results.values())
        return round(score,1)
    def submit_exam(self):
        self.require_environment()
        exam=self.state.get('exam')
        if not exam or exam.get('state') not in ('running','expired'): raise BusyError('No running mock is available to submit.')
        if self.busy(): raise BusyError('Another operation is in progress.')
        exam.update(state='grading',submitted_at=time.time(),graded=0); self.save()
        if self.terminals: self.terminals.stop_all()
        async def work(op):
            op.update(message='Grading the submitted attempt…',total=len(exam['tasks']),current=0)
            gate=asyncio.Semaphore(2)
            async def one(tid):
                async with gate:
                    result=await Grader(self.runner,BANK[tid]).grade()
                    result['checked_at']=time.time(); exam['results'][tid]=result; exam['graded']+=1
                    op['current']=exam['graded']; self.save()
            await asyncio.gather(*(one(tid) for tid in exam['tasks']))
            exam.update(state='finished',finished_at=time.time(),score=self.exam_score(exam['results'],exam.get('task_points',5)),has_errors=any(r['has_errors'] for r in exam['results'].values()))
            exam['domain_scores']={domain:round(sum(exam.get('task_points',5)*exam['results'][tid]['earned']/exam['results'][tid]['possible'] for tid in exam['tasks'] if BANK[tid]['domain']==domain),2) for domain in DOMAINS}
            summary={k:deepcopy(v) for k,v in exam.items() if k!='results'}
            self.state['history'].append(summary); self.state['history']=self.state['history'][-30:]
            self.atomic(self.directory/f"exam-{exam['id']}.json",exam); self.save()
            return {'score':exam['score'],'has_errors':exam['has_errors']}
        return self.start_action('exam_submit',work)
    def leave_exam(self,abandon=False):
        if self.busy(): raise BusyError('Let the current operation finish before leaving.')
        exam=self.state.get('exam')
        if exam and exam.get('state') in ('running','expired'):
            if not abandon: raise BusyError('Confirm abandonment of the running attempt.')
            exam.update(state='abandoned',finished_at=time.time())
            self.state['history'].append({k:deepcopy(v) for k,v in exam.items() if k!='results'})
            if self.terminals: self.terminals.stop_all()
        self.state['exam']=None; self.save(); return {'ok':True}
    def cleanup(self):
        self.require_environment(); self.require_practice()
        async def work(op):
            if self.terminals: self.terminals.stop_all()
            op['message']='Deleting only the known CKAD question namespaces and task folders…'
            for p in self.state['practice'].values():
                p['prepared']=False; p.pop('step_checks',None)
            self.save()
            await self.ops.clean_all()
            self.save(); return {'ok':True}
        return self.start_action('clean',work)
    async def timer_loop(self):
        while not self.closed:
            await asyncio.sleep(.5)
            exam=self.state.get('exam')
            if exam and exam.get('state') in ('running','expired') and time.time()>=exam['deadline']:
                if exam['state']!='expired':
                    exam['state']='expired'; self.save()
                    if self.terminals: self.terminals.stop_all()
                if self.environment.get('ready') and not self.busy(): self.submit_exam()
    def start_selftest(self,ids=None,set_id=None):
        self.require_environment(); self.require_practice()
        scope=set_tasks(set_id) if set_id is not None else list(ACTIVE_BANK.values())
        allowed={task['id'] for task in scope}
        ids=[task['id'] for task in scope] if ids is None else ids
        if not ids or any(x not in allowed for x in ids) or len(ids)!=len(set(ids)): raise ValueError('Unknown, duplicate, or out-of-set self-test task ID')
        report={'state':'running','set_id':set_id,'started_at':time.time(),'cluster_version':self.environment.get('version'),'task_ids':ids,'results':[],'full_bank':len(ids)==len(ACTIVE_BANK)}
        async def work(op):
            if self.terminals: self.terminals.stop_all()
            self.selftest=report
            op.update(total=len(ids),current=0,message='Resetting the selected self-test scope…')
            for task in scope:
                p=self.state['practice'].get(task['id'],{})
                p['prepared']=False; p.pop('step_checks',None)
            self.save()
            await self.ops.clean_all(scope)
            self.state['exam']=None; self.save()
            candidate=Runner(self.runner.kubeconfig,str(self.runner.workspace))
            for index,tid in enumerate(ids):
                task=BANK[tid]; op.update(current=index,message=f'Self-test {index+1}/{len(ids)}: {task["title"]}')
                entry={'task_id':tid,'title':task['title'],'passed':False}
                try:
                    await self.ops.setup(task,reset=True)
                    before=await Grader(self.runner,task).grade()
                    entry['initial_percent']=before['percent']
                    if before['complete']: raise RuntimeError('Untouched fixture already receives full credit.')
                    solution=await candidate.run(['/bin/bash','-e','-o','pipefail','-c',task['solution']],timeout=360,cwd=str(self.runner.map_path(task['workspace'])))
                    if solution.code: raise RuntimeError('Reference solution failed: '+solution.err[-1800:])
                    deadline=time.time()+180; after=None
                    while time.time()<deadline:
                        after=await Grader(self.runner,task).grade()
                        if after['complete']: break
                        await asyncio.sleep(3)
                    entry['result']=after
                    if not after or not after['complete']: raise RuntimeError('Reference solution did not receive complete credit after convergence.')
                    from validation_cases import alternative_answers,invalidate_answer
                    entry['alternatives']=[]
                    async for label in alternative_answers(candidate,task):
                        deadline=time.monotonic()+180
                        while time.monotonic()<deadline:
                            variant=await Grader(self.runner,task).grade()
                            if variant['complete']: break
                            await asyncio.sleep(3)
                        entry['alternatives'].append({'label':label,'result':variant})
                        if not variant['complete']: raise RuntimeError('Valid alternative rejected: '+label)
                    await invalidate_answer(candidate,task)
                    for _ in range(12):
                        await asyncio.sleep(2)
                        bad=await Grader(self.runner,task).grade()
                        if not bad['complete'] and not bad['has_errors']: break
                    entry['negative_result']=bad
                    entry['negative_detected']=not bad['complete'] and not bad['has_errors']
                    if not entry['negative_detected']: raise RuntimeError('Grader did not reliably detect an intentionally incorrect result.')
                    entry['passed']=True
                except Exception as exc: entry['error']=str(exc)
                finally:
                    try: await self.ops.delete(task)
                    except Exception as exc: entry.update(passed=False,cleanup_error=str(exc))
                report['results'].append(entry)
                self.atomic(self.directory/'selftest-report.json',report)
            report.update(state='finished',finished_at=time.time(),passed=sum(x['passed'] for x in report['results']),total=len(ids),all_passed=all(x['passed'] for x in report['results']))
            self.atomic(self.directory/'selftest-report.json',report)
            op['current']=len(ids); return {'passed':report['passed'],'total':report['total']}
        return self.start_action('selftest',work)
