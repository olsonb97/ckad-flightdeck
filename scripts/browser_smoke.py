"""Browser checks for the UI update, with explicit in-page API/WebSocket fixtures.

No Kubernetes operation is executed by this script. Actual HTTP/PTY tests live
in tests/test_http_terminal.py. Run: python scripts/browser_smoke.py
Requires Playwright and Chromium. No browser policies are overridden.
"""
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from manager import Manager
from runtime import Runner
from bank import ACTIVE_BANK as BANK
from tutor import study_guide, learning_feedback

SHIM = r'''
window.__data = DATA;
window.__fixtures = FIXTURES;
window.__mockIds = MOCK_IDS;
window.__calls = [];
window.__sockets = [];
window.__socketMode = 'offline';
window.__failNotes = false;
window.__fullGrade = false;
window.__operationId = 0;
function fixtureGrade(id, full=false) {
  const criteria = window.__fixtures[id].checks.map((c,i)=>({label:c.label, detail:i===0||full?'Expected state found.':'Expected resource configuration was not found. Inspect the resource and try again.', status:i===0||full?'pass':'fail', feedback:window.__fixtures[id].feedback[i][i===0||full?'pass':'fail']}));
  const earned = criteria.filter(c=>c.status==='pass').length;
  return {task_id:id, earned, possible:criteria.length, percent:100*earned/criteria.length, complete:earned===criteria.length, has_errors:false, criteria, checked_at:Date.now()/1000};
}
function operation(kind, apply, taskId=null) {
  const op = {id:'fixture-'+(++window.__operationId), kind, task_id:taskId, state:'running', message:'UI fixture operation (no cluster).', current:0, total:1};
  window.__data.operation=op;
  if (['prepare','reset','exam_prepare','exam_submit'].includes(kind)) window.__data.terminal_locked=true;
  setTimeout(()=>{op.result=apply();op.state='done';window.__data.terminal_locked=false;},window.__operationDelay||100);
  return {operation_id:op.id};
}
window.fetch=async (url,options={})=>{
  const body=JSON.parse(options.body||'{}');window.__calls.push({url,body});
  let result,ok=true,status=200;
  if(url==='/api/bootstrap'||url==='/api/state'){window.__data.server_time=Date.now()/1000;result=structuredClone(window.__data);}
  else if(url.startsWith('/api/task/')){
    const [,,,id,action]=url.split('/'); const task=window.__data.tasks.find(t=>t.id===id);
    if(action==='notes'){
      if(window.__failNotes&&'notes' in body){ok=false;status=503;result={error:'Explicit save failure fixture.'};}
      else{Object.assign(task.progress,body);result={ok:true};}
    }
    else if(action==='hint'){
      task.progress.hints_seen=Math.min((task.progress.hints_seen||0)+1,window.__fixtures[id].hints.length);
      result={hints:window.__fixtures[id].hints.slice(0,task.progress.hints_seen)};
    }
    else if(action==='solution'){result=window.__fixtures[id];}
    else if(action==='prepare'||action==='reset'){
      result=action==='prepare'&&task.progress.prepared?{already_prepared:true,task_id:id}:operation(action,()=>{task.progress.prepared=true;if(action==='reset'){delete task.progress.last_grade;delete task.progress.step_checks;}return {task_id:id};},id);
    }
    else if(action==='check'){
      result=operation('check_step',()=>{const grade=fixtureGrade(id,window.__fullGrade);const criterion=body.criterion;const item=grade.criteria[criterion];(task.progress.step_checks ||= {})[criterion]={...item,checked_at:grade.checked_at};return {...grade,criteria:[item],criterion};});
    }
    else if(action==='grade'){
      result=operation('grade',()=>{const grade=fixtureGrade(id,window.__fullGrade);task.progress.last_grade=grade;task.progress.step_checks=Object.fromEntries(grade.criteria.map((item,i)=>[i,{...item,checked_at:grade.checked_at}]));return grade;});
    }
    else{ok=false;status=404;result={error:'Unknown fixture task action'};}
  }
  else if(url==='/api/exam-start'){
    const setId=body.set_id||'core';const ids=setId==='core'?window.__mockIds:window.__data.tasks.filter(t=>t.set_id===setId).map(t=>t.id);
    const points=100/ids.length;
    window.__data.exam={id:'fixture-exam',set_id:setId,task_points:points,domain_weights:Object.fromEntries(Object.keys(window.__data.domains).map(d=>[d,ids.filter(id=>window.__data.tasks.find(t=>t.id===id).domain===d).length*points])),seed:body.seed||'fixture',state:'preparing',tasks:ids,prepared:0};
    result=operation('exam_prepare',()=>{window.__data.exam.state='running';window.__data.exam.deadline=Date.now()/1000+7200;window.__data.exam.duration_seconds=7200;for(const id of ids)window.__data.tasks.find(t=>t.id===id).progress.prepared=true;return {ok:true};});
  }
  else if(url==='/api/exam-submit'){
    window.__data.exam.state='grading';
    result=operation('exam_submit',()=>{const e=window.__data.exam;e.state='finished';e.results=Object.fromEntries(e.tasks.map(id=>[id,fixtureGrade(id)]));e.score=50;e.has_errors=false;e.domain_scores=Object.fromEntries(Object.entries(e.domain_weights).map(([id,points])=>[id,points/2]));return {ok:true};});
  }
  else if(url==='/api/exam-leave'){window.__data.exam=null;result={ok:true};}
  else if(url==='/api/export'){result={fixture:true,practice:window.__data.tasks.map(t=>t.progress)};}
  else if(url==='/api/retry'){result={ok:true};}
  else{ok=false;status=409;result={error:'Explicit UI fixture: action not implemented; no live cluster.'};}
  return {ok,status,statusText:'Fixture response',text:async()=>JSON.stringify(result)};
};
class FixtureSocket {
  static CONNECTING=0;static OPEN=1;static CLOSING=2;static CLOSED=3;
  constructor(url){
    this.url=url;this.readyState=0;this.sent=[];window.__sockets.push(this);
    setTimeout(()=>{
      if(window.__socketMode==='offline'){this.readyState=3;this.onclose?.();return;}
      this.readyState=1;this.onopen?.();
      const text='\x1b[38;5;141mUI preview · fixture output, not a live cluster\x1b[0m\r\n\r\n\x1b[38;5;79mstudent@flightdeck\x1b[0m:\x1b[38;5;111m/workspace\x1b[0m$ ';
      this.onmessage?.({data:new TextEncoder().encode(text).buffer});
    },15);
  }
  close(){this.readyState=3;setTimeout(()=>this.onclose?.(),5);}
  send(data){if(this.readyState!==1)throw Error('Fixture socket is closed');this.sent.push(JSON.parse(data));}
}
window.WebSocket=FixtureSocket;
Object.defineProperty(window,'localStorage',{value:{store:{},getItem(k){return this.store[k]??null},setItem(k,v){this.store[k]=String(v)}}});
'''

def main():
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).resolve().parents[1]
    static = root / 'app/static'
    output = Path(tempfile.mkdtemp(prefix='flightdeck-browser-'))
    completed = []
    def passed(name):
        completed.append(name)
        print(f'PASS {len(completed):02d}: {name}', flush=True)
    with tempfile.TemporaryDirectory() as temp:
        m = Manager(Runner(workspace=temp), Path(temp) / 'state')
        m.environment.update(phase='unavailable', message='Offline UI fixture. No Kubernetes cluster connected.', error='Start Docker Compose to connect the live cluster.')
        data = m.snapshot(); data['csrf'] = 'offline-ui-fixture-token'
        fixtures = {tid: {**{key: task[key] for key in ('solution', 'explanation', 'hints', 'checks')}, 'guide': study_guide(task), 'feedback': [{status: learning_feedback(task, c, status) for status in ('pass', 'fail')} for c in task['checks']]} for tid, task in BANK.items()}
        shim = SHIM.replace('DATA', json.dumps(data), 1).replace('FIXTURES', json.dumps(fixtures), 1).replace('MOCK_IDS', json.dumps(m.choose_exam('ui-update-fixture')), 1)
        html = re.sub(r'<link[^>]+>', '', (static / 'index.html').read_text())
        html = re.sub(r'<script.*?</script>', '', html, flags=re.S)
        vendor = (static / 'vendor/terminal.js').read_text().replace('export{ke as default};', 'globalThis.TerminalBundle=ke;')
        enhancements = (static / 'enhancements.js').read_text().replace('export class Enhancements', 'class Enhancements')
        # Separate module scope avoids collisions between the two modules' helpers.
        enhancements = 'globalThis.Enhancements = (()=>{' + enhancements + ';return Enhancements;})();'
        app = (static / 'app.js').read_text().replace("import TerminalBundle from './vendor/terminal.js';", '').replace("import { Enhancements } from './enhancements.js?v=8';", '')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1512,'height':1000}, device_scale_factor=1)
            page.set_default_timeout(5000)
            errors=[];page.on('pageerror', lambda error:errors.append(str(error)))
            page.set_content(html)
            page.add_style_tag(content=(static / 'vendor/terminal.css').read_text()+'\n'+(static / 'style.css').read_text()+'\n'+(static / 'enhancements.css').read_text())
            page.add_script_tag(content=shim);page.add_script_tag(content=vendor);page.add_script_tag(content=enhancements)
            page.add_script_tag(type='module',content=app)
            expect(page.locator('.question-card')).to_have_count(20)
            expect(page.locator('#page-task')).to_be_visible()
            for tab in ('results','help','notes'): expect(page.locator(f'#page-{tab}')).not_to_be_visible()
            expect(page.locator('#prepare-button')).to_be_disabled()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert page.locator('#terminal-main .xterm').count()==1
            assert page.locator('.task-panel').bounding_box()['height']>800
            page.screenshot(path=str(output/'preview.png'),full_page=True)
            passed('Desktop workspace, 20 questions, task-first panels, offline state and terminal mount')
            page.evaluate("window.__data.environment={ready:true,phase:'ready'}")
            expect(page.locator('#grade-button')).to_be_enabled()

            # Every displayed requirement must exactly match the bank, apart from code-format backticks.
            for tid, task in BANK.items():
                if page.locator('#set-selector').input_value() != task['set_id']:
                    page.locator('#set-selector').select_option(task['set_id'])
                page.locator(f'.question-card[data-task="{tid}"]').click()
                expect(page.locator('.requirements li')).to_have_count(len(task['requirements']))
                expect(page.locator('#grade-button')).to_be_enabled()
                actual=page.locator('.requirements li').all_text_contents()
                assert actual==[text.replace('`','') for text in task['requirements']],(tid,actual)
                assert page.locator('.task-heading h2').inner_text()==task['title']
            page.locator('#set-selector').select_option('core')
            passed('Both sets: all 36 visible question titles and requirements match the bank')

            expect(page.locator('#question-filters, #lab-status, #selftest-button')).to_have_count(0)
            page.locator('#search').fill('n08');expect(page.locator('.question-card')).to_have_count(1)
            page.locator('[data-task="n08"]').click()
            assert page.locator('.task-panel').get_attribute('data-domain')=='networking'
            page.locator('#search').fill('Helm');expect(page.locator('.question-card')).to_have_count(1)
            page.locator('#search').fill('no-such-question');expect(page.locator('.question-card')).to_have_count(0)
            page.locator('#search').fill('');page.locator('[data-task="n09"]').click()
            page.locator('#flag-task').click();expect(page.locator('#flag-task')).to_have_attribute('aria-pressed','true')
            expect(page.locator('[data-task="n09"] .question-mark')).to_have_class('question-mark flag')
            passed('Search, empty state, domain colors and review flags')

            page.locator('#tab-notes').click()
            page.locator('#task-notes').fill('Remember: selectors in one peer are ANDed.')
            expect(page.locator('#notes-status')).to_have_text('Saved.')
            page.locator('#task-notes').fill('Fast-switch draft <script>not markup</script>')
            page.locator('#next-task').click()
            page.locator('[data-task="n09"]').click();page.locator('#tab-notes').click()
            expect(page.locator('#task-notes')).to_have_value('Fast-switch draft <script>not markup</script>')
            expect(page.locator('#notes-status')).to_have_text('Saved.')
            assert page.evaluate("window.__data.tasks.find(t=>t.id==='n09').progress.notes").startswith('Fast-switch draft')
            page.evaluate('window.__failNotes=true')
            page.locator('#task-notes').fill('Save-failure draft retained')
            expect(page.locator('#notes-status')).to_have_text('Not saved. Edit to retry.')
            page.evaluate('window.__failNotes=false')
            page.locator('#task-notes').fill('Save recovered')
            expect(page.locator('#notes-status')).to_have_text('Saved.')
            page.locator('#task-notes').focus();page.wait_for_timeout(1400)
            assert page.locator('#task-notes').evaluate('(el)=>el===document.activeElement')
            passed('Notes autosave, rapid task-switch flush, escaped drafts, failure/retry and polling focus')

            page.locator('#tab-help').click()
            page.locator('#hint-button').click();expect(page.locator('.hints li')).to_have_count(1)
            page.locator('#hint-button').click();expect(page.locator('.hints li')).to_have_count(2)
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('#solution-button').click();expect(page.locator('.reference-solution pre')).to_have_count(0)
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('#solution-button').click()
            expect(page.locator('.reference-solution pre')).not_to_be_visible()
            page.locator('.reference-solution > summary').click()
            expect(page.locator('.reference-solution pre')).to_contain_text('kind: NetworkPolicy')
            page.locator('#tab-task').click();expect(page.locator('.reference-solution pre')).not_to_be_visible()
            page.locator('#tab-help').click();page.locator('#hide-solution').click();expect(page.locator('.reference-solution pre')).to_have_count(0)
            assert page.locator('.docs-links a').count()>0
            passed('Progressive hints, reveal/cancel/hide solution and separate documentation panel')

            page.locator('[data-task="d01"]').click()
            page.evaluate("window.__data.environment={...window.__data.environment,phase:'ready',ready:true,version:'v1.35 · UI fixture',error:null}")
            expect(page.locator('#prepare-button')).not_to_be_visible()
            expect(page.locator('#grade-button')).to_be_visible()
            expect(page.locator('#grade-button')).to_be_enabled()
            expect(page.locator('#send-context')).to_have_count(0)
            page.locator('#grade-button').click()
            expect(page.locator('#page-results')).to_be_visible()
            expect(page.locator('.grade-summary')).to_contain_text('1 /')
            expect(page.locator('.checkpoint-feedback[open]')).to_have_count(0)
            page.locator('.practice-step.pass > details > summary').click()
            expect(page.locator('.practice-step.pass > details[open]')).to_have_count(1)
            assert page.locator('.task-pages').evaluate('(el)=>el.scrollTop')==0
            passed('Start/check action flow, automatic results panel, partial grades and expandable criteria')

            page.evaluate("window.__socketMode='open'")
            expect(page.locator('#terminal-retry')).to_be_visible()
            page.locator('#terminal-retry').click()
            expect(page.locator('#terminal-connection')).to_have_text('Connected')
            expect(page.locator('#terminal-placeholder')).not_to_be_visible()
            page.locator('#tab-task').click()
            expect(page.locator('.task-namespace')).to_contain_text('ckad-d01')
            expect(page.locator('.manual-setup, #target-details')).to_have_count(0)
            inputs=page.evaluate("window.__sockets.flatMap(s=>s.sent).filter(m=>m.type==='input').map(m=>m.data)")
            assert inputs == []
            count=len(inputs)
            page.locator('#next-task').click()
            assert page.evaluate("window.__sockets.flatMap(s=>s.sent).filter(m=>m.type==='input').length")==count
            page.locator('[data-task="d01"]').click()
            page.locator('[data-terminal="scratch"]').click();expect(page.locator('#terminal-scratch')).to_be_visible()
            expect(page.locator('#terminal-connection')).to_have_text('Connected')
            page.locator('[data-terminal="main"]').click()
            page.locator('#settings-button').click();page.locator('#pref-terminal-font').select_option('16');page.locator('#pref-terminal-font').select_option('14');page.locator('#settings-close').click()
            width=page.locator('.terminal-panel').bounding_box()['width']
            page.locator('#terminal-expand').click()
            assert page.locator('.terminal-panel').bounding_box()['width']>width
            expect(page.locator('#terminal-expand')).to_have_attribute('aria-pressed','true')
            page.keyboard.press('Escape');expect(page.locator('#terminal-expand')).to_have_attribute('aria-pressed','false')
            assert all(0<m['cols']<500 for m in page.evaluate("window.__sockets.flatMap(s=>s.sent).filter(m=>m.type==='resize')"))
            page.wait_for_timeout(150)
            expect(page.locator('#terminal-connection')).to_have_text('Connected')
            passed('Fixture terminal send/setup, no auto-context side effects, tabs, resizing, fullscreen and reconnect')

            page.evaluate('window.__fullGrade=true')
            page.locator('#grade-button').click()
            expect(page.locator('.grade-summary')).to_have_class('grade-summary pass')
            expect(page.locator('#completed-count')).to_have_text('1 / 20')
            page.screenshot(path=str(output/'preview-results.png'),full_page=True)
            page.once('dialog',lambda dialog:dialog.accept());page.locator('#reset-button').click()
            expect(page.locator('.checkpoint-feedback')).to_have_count(0)
            expect(page.locator('[data-check-step]')).to_have_count(4)
            expect(page.locator('#completed-count')).to_have_text('0 / 20')
            passed('Complete-state colors, progress updates and confirmed reset')

            page.evaluate("window.__data.operation={id:'error-fixture',state:'error',kind:'grade',error:'Explicit infrastructure error fixture.'}")
            expect(page.locator('#operation-bar')).to_contain_text('Could not complete that action')
            page.locator('#dismiss-operation').click();expect(page.locator('#operation-bar')).not_to_be_visible()
            page.evaluate("window.__data.environment={ready:false,phase:'error',error:'Internal detail should not be shown'}")
            expect(page.locator('#lab-warning')).to_contain_text('Lab startup failed.')
            expect(page.locator('#lab-warning')).not_to_contain_text('Internal detail')
            page.locator('#retry-lab').click()
            assert page.evaluate("window.__calls.some(c=>c.url==='/api/retry')")
            page.evaluate("window.__data.environment={ready:true,phase:'ready'}")
            expect(page.locator('#lab-warning')).not_to_be_visible()
            expect(page.locator('#selftest-button, #settings-lab, #technical-details, #export-button')).to_have_count(0)
            passed('Plain failure recovery without maintenance dialogs')

            page.locator('#mock-button').click()
            page.locator('#confirm-mock').click()
            expect(page.locator('#countdown')).to_be_visible()
            expect(page.locator('.question-card')).to_have_count(20)
            expect(page.locator('#grade-button')).not_to_be_visible()
            expect(page.locator('#export-button, #exam-seed')).to_have_count(0)
            expect(page.locator('#target-details, #tab-help, #tab-results, #tab-notes, #hint-button, #solution-button, #task-notes')).to_have_count(0)
            expect(page.locator('#page-task')).to_be_visible()
            expect(page.locator('#status-filter')).to_have_count(0)
            page.evaluate('window.__data.exam.deadline=Date.now()/1000+30')
            expect(page.locator('#countdown')).to_have_class('urgent')
            page.screenshot(path=str(output/'preview-mock.png'),full_page=True)
            page.once('dialog',lambda dialog:dialog.accept());page.locator('#submit-exam').click()
            expect(page.locator('#modal')).to_be_visible()
            expect(page.locator('#modal-title')).to_have_text('Mock results')
            expect(page.locator('.report-question')).to_have_count(20)
            page.locator('.report-question').first.click()
            expect(page.locator('#page-results')).to_be_visible()
            expect(page.locator('.grade-summary')).to_be_visible()
            page.locator('#leave-exam').click();expect(page.locator('.question-card')).to_have_count(20)
            passed('Mock start, timed state, lockouts, deadline warning, submit/report and return to practice')

            page.locator('#tab-task').focus();page.keyboard.press('ArrowRight')
            expect(page.locator('#tab-results')).to_have_attribute('aria-selected','true')
            assert page.locator('#tab-results').evaluate('(el)=>el===document.activeElement')
            page.keyboard.press('End');expect(page.locator('#page-notes')).to_be_visible()
            page.locator('#menu-button').click();expect(page.locator('#sidebar')).not_to_be_visible()
            page.locator('#menu-button').click();expect(page.locator('#sidebar')).to_be_visible()
            page.locator('#settings-button').focus();page.keyboard.press('/')
            assert page.locator('#search').evaluate('(el)=>el===document.activeElement')
            passed('Keyboard tab navigation, focus states, desktop sidebar collapse and search shortcut')

            page.locator('[data-task="n09"]').click()
            for width,height in [(1920,1080),(1512,1000),(1366,768),(1100,800),(1024,768),(768,1024),(760,900),(390,844),(360,800),(320,760)]:
                page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(110)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'),f'horizontal overflow at {width}'
                assert page.locator('#prepare-button').is_visible() or page.locator('#grade-button').is_visible()
                assert page.locator('.task-panel').bounding_box()['width']>200
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(150)
            page.locator('#menu-button').click();expect(page.locator('#sidebar')).to_be_visible()
            page.locator('[data-task="n08"]').click();expect(page.locator('#sidebar')).not_to_be_visible()
            page.locator('#menu-button').click();page.locator('#sidebar-backdrop').click(position={'x':330,'y':100});expect(page.locator('#sidebar')).not_to_be_visible()
            page.screenshot(path=str(output/'preview-mobile.png'),full_page=True)
            passed('Ten desktop/tablet/phone viewport sizes, mobile drawer selection and backdrop dismissal')

            page.set_viewport_size({'width':1512,'height':1000});page.wait_for_timeout(150)
            page.locator('[data-task="n09"]').click()
            page.evaluate('window.__data.operation=null')
            page.wait_for_timeout(1450)
            page.locator('#search').fill('')
            page.locator('[data-task="d01"]').click()
            page.locator('[data-task="d01"]').hover()
            expect(page.locator('[data-task="d01"]')).to_have_css('background-color','rgb(238, 240, 255)')
            page.evaluate("window.__data.tasks.find(t=>t.id==='d01').progress.prepared=true")
            expect(page.locator('#grade-button')).to_be_visible()
            page.evaluate(r'''()=>{
              const socket=window.__sockets.filter(s=>s.url.includes('/ws/main')&&s.readyState===1).at(-1);
              const output='\x1b[2J\x1b[H\x1b[38;5;141mUI preview · sample output, not a live cluster\x1b[0m\r\n\r\n\x1b[38;5;79mstudent@flightdeck\x1b[0m:\x1b[38;5;111m/workspace/d01\x1b[0m$ kubectl get pods\r\nNAME      READY   STATUS    RESTARTS   AGE\r\ncatalog   1/1     Running   0          34s\r\n\r\n\x1b[38;5;79mstudent@flightdeck\x1b[0m:\x1b[38;5;111m/workspace/d01\x1b[0m$ ';
              socket.onmessage({data:new TextEncoder().encode(output).buffer});
            }''')
            page.mouse.move(1450, 20)
            page.wait_for_timeout(250)
            page.screenshot(path=str(output/'preview-workspace.png'),full_page=True)
            assert not errors,errors
            passed('No JavaScript page errors across all exercised interactions')
            browser.close()
    print(f'\n{len(completed)} browser scenario groups passed. All API/WebSocket traffic in this script used explicit fixtures. No Kubernetes cluster was tested.')

if __name__=='__main__':
    main()
