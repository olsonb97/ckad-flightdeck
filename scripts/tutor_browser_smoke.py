import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from browser_smoke import BANK, Manager, Runner, SHIM, study_guide, learning_feedback


def main():
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).resolve().parents[1]
    static = root / 'app/static'
    output = Path(tempfile.mkdtemp(prefix='flightdeck-study-'))
    print(f'Screenshots: {output}', flush=True)
    with tempfile.TemporaryDirectory() as temp:
        manager = Manager(Runner(workspace=temp), Path(temp) / 'state')
        manager.environment.update(ready=True, phase='ready', message='Explicit browser fixture; no cluster commands are run.')
        data = manager.snapshot()
        data['csrf'] = 'local-study-fixture'
        fixtures = {tid: {**{key: task[key] for key in ('solution', 'explanation', 'hints', 'checks')}, 'guide': study_guide(task), 'feedback': [{status: learning_feedback(task, c, status) for status in ('pass', 'fail')} for c in task['checks']]} for tid, task in BANK.items()}
        shim = SHIM.replace('DATA', json.dumps(data), 1).replace('FIXTURES', json.dumps(fixtures), 1).replace('MOCK_IDS', json.dumps(manager.choose_exam('learning')), 1)
        html = re.sub(r'<link[^>]+>', '', (static / 'index.html').read_text())
        html = re.sub(r'<script.*?</script>', '', html, flags=re.S)
        vendor = (static / 'vendor/terminal.js').read_text().replace('export{ke as default};', 'globalThis.TerminalBundle=ke;')
        preferences = (static / 'enhancements.js').read_text().replace('export class Enhancements', 'class Enhancements')
        preferences = 'globalThis.Enhancements = (()=>{' + preferences + ';return Enhancements;})();'
        app = (static / 'app.js').read_text().replace("import TerminalBundle from './vendor/terminal.js';", '').replace("import { Enhancements } from './enhancements.js?v=8';", '')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True)
            if '--regressions' in sys.argv:
                regression_checks(browser, html, static, shim, vendor, preferences, app)
                browser.close()
                return
            page = browser.new_page(viewport={'width': 1512, 'height': 980})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            page.set_content(html)
            page.add_style_tag(content='\n'.join((static / name).read_text() for name in ('vendor/terminal.css', 'style.css', 'enhancements.css')))
            page.add_script_tag(content=shim)
            page.add_script_tag(content="window.__socketMode='open';Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text;}}});")
            page.add_script_tag(content=vendor)
            page.add_script_tag(content=preferences)
            page.add_script_tag(type='module', content=app)
            expect(page.locator('.question-card')).to_have_count(20)
            expect(page.locator('.terminal-footer, .study-intro, .bank-eyebrow, #mode-label, #reading-button, .reading-mode')).to_have_count(0)
            expect(page.locator('.terminal-panel')).to_be_visible()
            expect(page.locator('#lab-warning')).not_to_be_visible()
            expect(page.locator('#question-filters, #lab-status, #settings-lab, #selftest-button')).to_have_count(0)
            expect(page.locator('#page-task .practice-checks, .manual-setup > p, .manual-setup > h3')).to_have_count(0)
            expect(page.locator('#domain-filter')).to_have_count(0)
            assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).theme") == 'system'
            assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).reading === undefined")
            page.emulate_media(color_scheme='dark')
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            page.emulate_media(color_scheme='light')
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            expect(page.locator('#tutor-button, #tutor-panel, #send-context, #copy-context')).to_have_count(0)
            expect(page.locator('.task-namespace')).to_contain_text('ckad-d01')
            expect(page.locator('.lab-unprepared, .section-label')).to_have_count(0)
            expect(page.locator('[data-check-step]')).to_have_count(4)
            expect(page.locator('[data-check-step="0"]')).to_be_enabled()
            expect(page.locator('#reset-button')).to_be_visible()
            expect(page.locator('#prepare-button')).not_to_be_visible()
            page.screenshot(path=str(output / 'workspace.png'), full_page=True)
            for selector in ('#menu-button', '#settings-button', '#terminal-expand', '#previous-task', '#next-task', '#flag-task'):
                centered = page.locator(selector).evaluate('(el)=>{const a=el.getBoundingClientRect(),b=el.querySelector("svg").getBoundingClientRect();return Math.abs(a.x+a.width/2-b.x-b.width/2)<1&&Math.abs(a.y+a.height/2-b.y-b.height/2)<1;}')
                assert centered, selector
            expect(page.locator('#target-details, .target-grid, .manual-setup')).to_have_count(0)
            page.locator('#next-task').click()
            expect(page.locator('.task-namespace')).to_contain_text('ckad-d02')
            page.locator('#previous-task').click()
            page.locator('#settings-button').click()
            expect(page.locator('#pref-setup-help, #pref-layout')).to_have_count(0)
            expect(page.locator('#settings-guide, #settings-lab, #export-button, #pref-blink, #pref-compact')).to_have_count(0)
            expect(page.locator('#settings-dialog select')).to_have_count(3)
            page.locator('#settings-close').click()
            expect(page.locator('.task-namespace')).to_contain_text('ckad-d01')
            assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).setupHelp === undefined")
            print('PASS: namespace-only questions, no context/setup controls or saved setup preference', flush=True)
            expect(page.locator('#prepare-button')).not_to_be_visible()
            expect(page.locator('.terminal-panel')).to_be_visible()
            expect(page.locator('#reset-button')).to_be_visible()
            page.locator('#tab-results').click()
            expect(page.locator('[data-check-step="1"]')).to_be_enabled()
            page.locator('[data-check-step="1"]').click()
            expect(page.locator('.practice-step').nth(1)).to_contain_text('Not yet')
            expect(page.locator('.practice-step').nth(1)).to_contain_text('What you’re learning')
            expect(page.locator('.practice-step').nth(1)).to_contain_text('Field focus:')
            expect(page.locator('#page-results')).to_be_visible()
            expect(page.locator('.practice-step').nth(1).locator('.checkpoint-feedback')).to_have_attribute('open', '')
            expect(page.locator('.checkpoint-feedback[open]')).to_have_count(1)
            assert page.evaluate("window.__data.tasks[0].progress.last_grade === undefined")
            page.locator('.practice-step').nth(1).locator('.inspection-command summary').click()
            expect(page.locator('.practice-step').nth(1).locator('pre')).to_contain_text('kubectl -n ckad-d01 get pod catalog')
            page.evaluate('window.__fullGrade=true')
            page.locator('[data-check-step="1"]').click()
            expect(page.locator('.practice-step').nth(1)).to_contain_text('Verified')
            expect(page.locator('#completed-count')).to_have_text('0 / 20')
            page.screenshot(path=str(output / 'checkpoint.png'), full_page=True)
            print('PASS: independent checkpoint feedback, field focus, retry and no whole-task score', flush=True)

            page.locator('#tab-help').click()
            expect(page.locator('.terminal-panel')).to_be_visible()
            page.screenshot(path=str(output / 'help.png'), full_page=True)
            page.locator('#solution-button').click()
            expect(page.locator('.walkthrough-steps > li')).to_have_count(3)
            expect(page.locator('.answer-section[open]')).to_have_count(0)
            page.locator('.verification-section > summary').click()
            page.locator('#copy-verification').click()
            assert page.evaluate('window.__copied') == study_guide(BANK['d01'])['verification']
            page.locator('.verification-section > summary').click()
            page.locator('.reference-solution > summary').click()
            page.locator('#copy-solution').click()
            assert page.evaluate('window.__copied') == BANK['d01']['solution']
            page.locator('.reference-solution > summary').click()
            page.locator('.task-pages').evaluate('(el)=>el.scrollTop=0')
            page.screenshot(path=str(output / 'walkthrough.png'), full_page=True)
            print('PASS: terminal stays visible with study help, detailed answers and copy-only commands', flush=True)

            for tid, task in BANK.items():
                if page.locator('#set-selector').input_value() != task['set_id']:
                    page.locator('#set-selector').select_option(task['set_id'])
                page.locator(f'[data-task="{tid}"]').click()
                expect(page.locator('#grade-button')).to_be_enabled()
                expect(page.locator('.task-namespace')).to_contain_text(task['namespace'])
                expect(page.locator('#target-details, .manual-setup')).to_have_count(0)
                page.locator('#tab-help').click()
                if page.locator('#solution-button').count():
                    page.locator('#solution-button').click()
                expect(page.locator('.walkthrough-steps > li')).to_have_count(3)
                expect(page.locator('.verification-section pre')).not_to_contain_text('kubectl config ')
                if 'kubectl ' in study_guide(task)['verification']:
                    expect(page.locator('.verification-section pre')).to_contain_text('-n ' + task['namespace'])
                expect(page.locator('.checklist-section li')).to_have_count(len(task['checks']))
                assert page.locator('.expected-result p').text_content()
                assert page.locator('.pitfall-card p').text_content()
            assert not page.evaluate("window.__calls.some(call=>call.url.includes('/api/tutor/'))")
            assert page.evaluate("window.__sockets.flatMap(s=>s.sent).filter(m=>m.type==='input')") == []
            print('PASS: all 36 visible walkthroughs, explicit task environments, no provider requests or injected terminal input', flush=True)

            page.locator('#settings-button').click()
            expect(page.locator('[data-settings-tab]')).to_have_count(0)
            page.locator('#pref-theme').select_option('dark')
            page.locator('#pref-task-font').select_option('16')
            page.locator('#settings-close').click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            expect(page.locator('.hint-card')).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
            page.locator('.task-pages').evaluate('(el)=>el.scrollTop=0')
            page.screenshot(path=str(output / 'dark.png'), full_page=True)
            for width in (1920, 1366, 1100, 1024, 768, 760, 390, 360, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(60)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), width
                assert not page.locator('.task-pages').evaluate('(el)=>el.scrollWidth > el.clientWidth'), width
                if width in (390, 320):
                    page.screenshot(path=str(output / f'mobile-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 1512, 'height': 980})
            expect(page.locator('.terminal-panel')).to_be_visible()
            page.locator('#settings-button').click()
            page.locator('#pref-theme').select_option('light')
            page.locator('#settings-close').click()
            print('PASS: dark mode, font settings and nine split-workspace viewport sizes', flush=True)

            page.locator('#set-selector').select_option('core')
            page.locator('[data-task="d01"]').click()
            page.evaluate("window.__fixtures.d01.guide.steps[0]='<img src=x onerror=window.__unsafe=true> **not executable**'")
            page.locator('#tab-help').click()
            page.locator('#hide-solution').click()
            page.locator('#solution-button').click()
            expect(page.locator('.walkthrough img')).to_have_count(0)
            assert not page.evaluate('Boolean(window.__unsafe)')
            page.locator('#mock-button').click()
            page.locator('#confirm-mock').click()
            expect(page.locator('#countdown')).to_be_visible()
            expect(page.locator('#toast')).not_to_be_visible()
            expect(page.locator('.practice-checks')).to_have_count(0)
            expect(page.locator('#tab-help, #tab-results, #tab-notes, #target-details, .walkthrough, #task-notes, .docs-links')).to_have_count(0)
            expect(page.locator('#page-task')).to_be_visible()
            page.screenshot(path=str(output / 'mock.png'), full_page=True)
            assert not errors, errors
            print('PASS: escaped answer content, mock lockouts and no JavaScript errors', flush=True)
            browser.close()
    print(f'Study UI smoke tests passed with explicit offline fixtures. Screenshots: {output}')


def regression_checks(browser, html, static, shim, vendor, preferences, app):
    from playwright.sync_api import expect
    failures = []

    def check(name, scenario, initial=''):
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.set_default_timeout(4000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        try:
            page.set_content(html)
            page.add_style_tag(content='\n'.join((static / path).read_text() for path in ('vendor/terminal.css', 'style.css', 'enhancements.css')))
            page.add_script_tag(content=shim)
            if initial:
                page.add_script_tag(content=initial)
            page.add_script_tag(content=vendor)
            page.add_script_tag(content=preferences)
            page.add_script_tag(type='module', content=app)
            scenario(page)
            assert not errors, errors
            print('PASS: ' + name, flush=True)
        except Exception as error:
            failures.append(name)
            print('FAIL: ' + name + ': ' + (str(error) or type(error).__name__).splitlines()[0], flush=True)
        finally:
            page.close()

    def automatic_question_opening(page):
        expect(page.locator('.question-card')).to_have_count(16)
        expect(page.locator('.question-loading')).to_contain_text('Preparing question')
        expect(page.locator('.requirements')).to_have_count(0)
        assert page.evaluate('window.__sockets.length') == 0
        expect(page.locator('#grade-button')).to_be_enabled()
        expect(page.locator('.task-id')).to_have_text('Question 1')
        expect(page.locator('.question-number').first).to_have_text('01')
        expect(page.locator('#prepare-button')).not_to_be_visible()
        page.wait_for_function("window.__sockets.some(s=>s.url.includes('task=s01')&&s.readyState===1)")
        page.locator('#next-task').click()
        expect(page.locator('.question-loading')).to_be_visible()
        expect(page.locator('.requirements')).to_have_count(0)
        expect(page.locator('#grade-button')).to_be_enabled()
        page.wait_for_function("window.__sockets.some(s=>s.url.includes('task=s02')&&s.readyState===1)")
        expect(page.locator('.task-id')).to_have_text('Question 2')
        operations=page.evaluate('window.__operationId')
        page.locator('#previous-task').click()
        expect(page.locator('#grade-button')).to_be_enabled()
        assert page.evaluate('window.__operationId') == operations
        assert page.evaluate("window.__sockets.flatMap(s=>s.sent).every(m=>m.type!=='input')")

    def remote_notes(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-notes').click()
        page.locator('#task-notes').fill('Saved in this tab')
        expect(page.locator('#notes-status')).to_have_text('Saved.')
        page.evaluate("window.__data.tasks[0].progress.notes='Edited in another tab'")
        expect(page.locator('#task-notes')).to_have_value('Edited in another tab')
        page.locator('#next-task').click()
        page.locator('#previous-task').click()
        page.locator('#tab-notes').click()
        expect(page.locator('#task-notes')).to_have_value('Edited in another tab')
        page.evaluate('window.__failNotes=true')
        page.locator('#task-notes').fill('Unsaved draft')
        expect(page.locator('#notes-status')).to_have_text('Not saved. Edit to retry.')
        page.evaluate("window.__data.tasks[0].progress.notes='Different server note';window.__data.tasks[0].progress.flagged=true")
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#task-notes')).to_have_value('Unsaved draft')
        expect(page.locator('#notes-status')).to_have_text('Not saved. Edit to retry.')

    def delayed_notes_poll(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-notes').click()
        page.evaluate("""()=>{
            window.__data.tasks[0].progress.flagged=true;
            const baseFetch=window.fetch;
            let hold=true;
            window.fetch=async(url,options)=>{
                const result=await baseFetch(url,options);
                if(url==='/api/state'&&hold){hold=false;return new Promise(resolve=>{window.__releaseState=()=>resolve(result);});}
                return result;
            };
        }""")
        page.wait_for_function('typeof window.__releaseState === "function"')
        page.locator('#task-notes').fill('Saved after the poll started')
        expect(page.locator('#notes-status')).to_have_text('Saved.')
        page.evaluate('window.__releaseState()')
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#task-notes')).to_have_value('Saved after the poll started')

    def student_ui_only(page):
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#lab-warning')).not_to_be_visible()
        page.locator('#settings-button').click()
        expect(page.locator('#settings-dialog select')).to_have_count(3)
        expect(page.locator('#settings-lab, #selftest-button, #technical-details, #validation-details, #settings-about, #export-button, #question-filters')).to_have_count(0)
        page.locator('#settings-close').click()
        page.evaluate("window.__data.environment.message='Internal diagnostic';window.__data.tasks[0].progress.flagged=true")
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('body')).not_to_contain_text('Internal diagnostic')
        assert page.evaluate("window.__calls.every(c=>!['/api/selftest','/api/clean','/api/export'].includes(c.url))")

    def scroll_position(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-help').click()
        page.locator('#solution-button').click()
        page.locator('.reference-solution > summary').click()
        page.locator('.task-pages').evaluate('(el)=>{el.scrollTop=el.scrollHeight;window.__savedScroll=el.scrollTop;}')
        page.evaluate('window.__data.tasks[0].progress.flagged=true')
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        assert page.evaluate('Math.abs(document.querySelector(".task-pages").scrollTop-window.__savedScroll)<2')
        expect(page.locator('.reference-solution')).to_have_attribute('open', '')

    def keyboard_focus(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-help').click()
        page.locator('#hint-button').focus()
        page.keyboard.press('Enter')
        expect(page.locator('.hints li')).to_have_count(1)
        expect(page.locator('#hint-button')).to_be_focused()
        page.locator('#solution-button').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#hide-solution')).to_be_focused()
        page.keyboard.press('Enter')
        expect(page.locator('#solution-button')).to_be_focused()

    def disconnected_controls(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-help').click()
        page.evaluate('window.__offline=true')
        expect(page.locator('#lab-warning')).to_have_text('App disconnected. Reconnecting…')
        expect(page.locator('#retry-lab')).to_have_count(0)
        for selector in ('#hint-button', '#solution-button', '#mock-button'):
            expect(page.locator(selector)).to_be_disabled()
        page.evaluate('window.__offline=false')
        expect(page.locator('#hint-button')).to_be_enabled()
        expect(page.locator('#mock-button')).to_be_enabled()

    def startup_settings(page):
        expect(page.locator('#lab-warning')).to_have_text('App disconnected. Reconnecting…')
        page.locator('#settings-button').click()
        page.locator('#pref-theme').select_option('dark')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        expect(page.locator('#settings-dialog select')).to_have_count(3)
        expect(page.locator('#settings-lab, #settings-guide')).to_have_count(0)

    def saved_preferences(page):
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('.terminal-panel')).to_be_visible()
        expect(page.locator('#target-details pre')).not_to_be_visible()
        page.locator('#settings-button').click()
        expect(page.locator('#pref-theme')).to_have_value('system')
        expect(page.locator('#pref-task-font')).to_have_value('14')
        expect(page.locator('#pref-terminal-font')).to_have_value('14')
        expect(page.locator('#pref-blink, #pref-compact')).to_have_count(0)
        expect(page.locator('.terminal-panel')).to_be_visible()
        expect(page.locator('#reading-button, .reading-mode')).to_have_count(0)
        assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).reading === undefined")

    def finished_selection(page):
        expect(page.locator('.question-card')).to_have_count(1)
        expect(page.locator('.task-heading h2')).to_have_text(BANK['n01']['title'])
        page.locator('#tab-results').click()
        expect(page.locator('.grade-summary')).to_be_visible()
        expect(page.locator('.practice-checks')).to_have_count(0)

    def no_historical_toast(page):
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#toast')).not_to_be_visible()

    def historical_checks(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-results').click()
        expect(page.locator('.checkpoint-feedback')).to_have_count(0)
        expect(page.locator('.grade-summary')).to_contain_text('Last full check')
        page.evaluate('window.__data.tasks[0].progress.prepared=true')
        expect(page.locator('#grade-button')).to_be_visible()
        expect(page.locator('.checkpoint-feedback')).to_have_count(0)
        page.evaluate("window.__data.tasks[0].progress.step_checks={0:{...fixtureGrade('d01',true).criteria[0],checked_at:1}};window.__data.tasks[0].progress.started_at=Date.now()/1000;window.__data.tasks[0].progress.flagged=true")
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.checkpoint-feedback')).to_have_count(0)

    def strict_mock_controls(page):
        expect(page.locator('.question-card')).to_have_count(20)
        page.locator('#tab-notes').click()
        page.locator('#task-notes').fill('Saved practice answer')
        expect(page.locator('#notes-status')).to_have_text('Saved.')
        page.evaluate('window.__failNotes=true')
        page.locator('#task-notes').fill('Unsaved practice draft')
        expect(page.locator('#notes-status')).to_have_text('Not saved. Edit to retry.')
        page.locator('#tab-help').click()
        page.locator('#solution-button').click()
        expect(page.locator('.walkthrough')).to_be_visible()
        note_writes = page.evaluate("window.__calls.filter(c=>c.url.endsWith('/notes')&&'notes' in c.body).length")
        for phase in ('preparing', 'running', 'grading', 'expired'):
            page.evaluate("phase=>{window.__data.exam={id:'strict-mock',state:phase,tasks:['d01'],deadline:Date.now()/1000+600,prepared:1,graded:0,seed:'fixture'};window.__data.operation=null;}", phase)
            expect(page.locator('#exam-bar')).to_be_visible()
            expect(page.locator('#target-details, #tab-help, #tab-results, #tab-notes, #page-help, #page-results, #page-notes, .walkthrough, .docs-links')).to_have_count(0)
            expect(page.locator('#page-task')).to_be_visible()
            expect(page.locator('.task-namespace')).to_contain_text('ckad-d01')
            expect(page.locator('#completed-count')).not_to_be_visible()
            expect(page.locator('#domain-filter, #status-filter, #export-button')).to_have_count(0)
            expect(page.locator('.task-meta, .task-panel .domain-tag')).to_have_count(0)
            expect(page.locator('#mock-button')).not_to_be_visible()
            page.locator('#settings-button').click()
            expect(page.locator('#settings-dialog select')).to_have_count(3)
            expect(page.locator('#pref-setup-help, #pref-layout, #settings-guide, #settings-lab')).to_have_count(0)
            expect(page.locator('#validation-details, #selftest-button, #retry-lab')).to_have_count(0)
            page.locator('#settings-close').click()
            page.evaluate("window.dispatchEvent(new Event('beforeunload'))")
        assert page.evaluate("window.__calls.filter(c=>c.url.endsWith('/notes')&&'notes' in c.body).length") == note_writes
        page.locator('#flag-task').click()
        expect(page.locator('#flag-task')).to_have_attribute('aria-pressed', 'true')
        page.evaluate('window.__data.exam=null;window.__failNotes=false')
        expect(page.locator('#tab-notes')).to_be_visible()
        page.locator('#tab-notes').click()
        expect(page.locator('#task-notes')).to_have_value('Unsaved practice draft')
        page.locator('#tab-help').click()
        expect(page.locator('#solution-button')).to_be_visible()
        expect(page.locator('.walkthrough')).to_have_count(0)

    def startup_recovery(page):
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#grade-button')).to_be_enabled()
        page.evaluate("window.__data.tasks[0].progress.prepared=false;window.__data.environment={ready:false,phase:'starting',message:'Waiting for ckad-worker (not reporting).',checks:{'node_ckad-control':true,'node_ckad-worker':false}}")
        expect(page.locator('#lab-warning')).to_have_text('Starting lab…')
        expect(page.locator('#retry-lab')).to_have_count(0)
        expect(page.locator('.question-loading')).to_have_text('Waiting for lab…')
        page.evaluate("window.__data.environment.phase='error';window.__data.environment.error='ckad-worker is not reporting. Check docker compose logs worker.'")
        expect(page.locator('#lab-warning')).to_contain_text('Lab startup failed.')
        expect(page.locator('.question-loading')).to_have_text('Lab startup failed. See the launcher for details.')
        expect(page.locator('#terminal-placeholder-title')).to_have_text('Lab unavailable')
        expect(page.locator('#terminal-placeholder-message')).to_have_text('Startup failed. See the launcher for details.')
        expect(page.locator('#terminal-connection')).to_have_text('Lab unavailable')
        expect(page.locator('#terminal-dot')).to_have_class('error')
        expect(page.locator('#retry-lab')).to_be_enabled()
        expect(page.locator('#retry-lab')).to_have_text('Retry')
        expect(page.locator('body')).not_to_contain_text('docker compose logs worker')
        page.locator('#retry-lab').click()
        assert page.evaluate("window.__calls.some(c=>c.url==='/api/retry')")
        page.evaluate("window.__data.tasks[0].progress.prepared=true;window.__data.environment.ready=true;window.__data.environment.phase='ready'")
        expect(page.locator('#lab-warning')).not_to_be_visible()
        expect(page.locator('.question-loading')).to_have_count(0)

    def question_sets(page):
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#set-selector option')).to_have_count(2)
        page.evaluate("window.__data.tasks[0].progress.last_grade=fixtureGrade('d01',true)")
        expect(page.locator('#completed-count')).to_have_text('1 / 20')
        page.locator('#set-selector').select_option('focused')
        expect(page.locator('.question-card')).to_have_count(16)
        expect(page.locator('#completed-count')).to_have_text('0 / 16')
        expect(page.locator('.task-namespace')).to_contain_text('ckad-s01')
        page.locator('#tab-notes').click()
        page.locator('#task-notes').fill('Second-set note')
        expect(page.locator('#notes-status')).to_have_text('Saved.')
        page.locator('#set-selector').select_option('core')
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#completed-count')).to_have_text('1 / 20')
        page.locator('#tab-notes').click()
        expect(page.locator('#task-notes')).to_have_value('')
        page.locator('#set-selector').select_option('focused')
        page.locator('#tab-notes').click()
        expect(page.locator('#task-notes')).to_have_value('Second-set note')
        expect(page.locator('#selftest-button, #settings-lab')).to_have_count(0)
        assert not page.evaluate("window.__calls.some(c=>c.url==='/api/selftest')")
        page.locator('#mock-button').click()
        expect(page.locator('#modal-body')).to_contain_text('Set 2')
        expect(page.locator('#modal-body')).to_contain_text('16 questions')
        page.locator('#confirm-mock').click()
        expect(page.locator('#countdown')).to_be_visible()
        expect(page.locator('.question-card')).to_have_count(16)
        expect(page.locator('#set-selector')).not_to_be_visible()
        expect(page.locator('#tab-help, #tab-notes, #target-details')).to_have_count(0)
        assert page.evaluate("window.__calls.find(c=>c.url==='/api/exam-start').body.set_id") == 'focused'
        page.evaluate("const s=document.querySelector('#set-selector');s.value='core';s.dispatchEvent(new Event('change'))")
        expect(page.locator('#set-selector')).to_have_value('focused')
        page.locator('#submit-exam').click()
        expect(page.locator('.report-question')).to_have_count(16)
        expect(page.locator('.score-table')).to_contain_text('31.25')
        page.locator('#modal-close').click()
        page.locator('#leave-exam').click()
        expect(page.locator('#set-selector')).to_be_visible()
        expect(page.locator('.question-card')).to_have_count(16)
        assert page.evaluate("JSON.parse(JSON.stringify(localStorage.getItem('flightdeck-set')))") == 'focused'
        assert page.evaluate("window.__sockets.flatMap(s=>s.sent).filter(m=>m.type==='input')") == []

    check('Question opening prepares fixtures before scoped terminal access', automatic_question_opening, "localStorage.setItem('flightdeck-set','focused');localStorage.setItem('flightdeck-question','s01');window.__operationDelay=900;window.__socketMode='open';")
    check('Question sets isolate progress, notes and timed mocks', question_sets)
    check('Plain startup notice and failure-only Retry', startup_recovery)
    check('Mocks remove study aids and preserve practice notes', strict_mock_controls)
    offline = "const baseFetch=window.fetch;window.__offline=false;window.fetch=(url,options)=>{if(window.__offline&&(url==='/api/state'||url==='/api/bootstrap'))throw new Error('Offline fixture');return baseFetch(url,options);};"
    check('Clean notes synchronize; unsaved drafts survive refresh', remote_notes)
    check('Delayed polls cannot overwrite newly saved notes', delayed_notes_poll)
    check('Student UI contains no maintenance tools', student_ui_only)
    check('Expanded walkthrough retains its scroll position', scroll_position)
    check('Keyboard focus survives hints and answer rerenders', keyboard_focus)
    check('Disconnected actions and accessible status update together', disconnected_controls, offline)
    check('Display settings work before bootstrap succeeds', startup_settings, offline + 'window.__offline=true;')
    check('Invalid saved preferences recover to usable defaults', saved_preferences, "localStorage.setItem('flightdeck-font','13.5');localStorage.setItem('flightdeck-workspace',JSON.stringify({theme:'invalid',taskFont:13.5,terminalFont:'bad',cursorBlink:'false',reading:true,setupHelp:'false'}));")
    check('Finished mock selects a task from its own report', finished_selection, "window.__data.exam={id:'finished',state:'finished',tasks:['n01'],results:{n01:fixtureGrade('n01')},score:25,seed:'fixture'};")
    check('Old completed operations are not replayed at startup', no_historical_toast, "window.__data.operation={id:'old',kind:'check_step',state:'done',result:{...fixtureGrade('d01'),criterion:0}};")
    check('Historical grades are not reused as fresh step checks', historical_checks, "window.__data.tasks[0].progress={prepared:false,last_grade:fixtureGrade('d01',true)};window.__data.tasks[0].progress.last_grade.checked_at=1;")
    assert not failures, 'Regression failures: ' + ', '.join(failures)


def live_smoke(url):
    from playwright.sync_api import sync_playwright, expect
    output = Path(tempfile.mkdtemp(prefix='flightdeck-live-ui-'))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True)
        page = browser.new_page(viewport={'width': 1512, 'height': 980})
        errors, frames = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('websocket', lambda socket: socket.on('framesent', lambda frame: frames.append(frame)))
        page.emulate_media(color_scheme='dark')
        page.add_init_script("if(!sessionStorage.getItem('flightdeck-legacy-test')){localStorage.setItem('flightdeck-workspace',JSON.stringify({theme:'system',reading:true}));sessionStorage.setItem('flightdeck-legacy-test','1');}")
        page.goto(url)
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).theme") == 'system'
        assert page.evaluate("JSON.parse(localStorage.getItem('flightdeck-workspace')).reading === undefined")
        expect(page.locator('.terminal-panel')).to_be_visible()
        expect(page.locator('#lab-warning')).not_to_be_visible()
        expect(page.locator('#lab-status, #reading-button, #settings-lab, #selftest-button')).to_have_count(0)
        page.emulate_media(color_scheme='light')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        expect(page.locator('#send-context, #tutor-button, #tutor-panel')).to_have_count(0)
        expect(page.locator('.task-namespace')).to_contain_text('ckad-d01')
        expect(page.locator('[data-check-step]')).to_have_count(4)
        expect(page.locator('#set-selector option')).to_have_count(2)
        page.locator('#set-selector').select_option('focused')
        expect(page.locator('.question-card')).to_have_count(16)
        expect(page.locator('.task-namespace')).to_contain_text('ckad-s01')
        page.locator('#set-selector').select_option('core')
        expect(page.locator('.question-card')).to_have_count(20)
        expect(page.locator('#target-details, .manual-setup')).to_have_count(0)
        page.locator('#next-task').click()
        expect(page.locator('.task-namespace')).to_contain_text('ckad-d02')
        page.locator('#tab-help').click()
        expect(page.locator('.terminal-panel')).to_be_visible()
        expect(page.locator('.study-intro, .terminal-footer')).to_have_count(0)
        expect(page.locator('.hint-card h3')).to_have_text('Hints')
        expect(page.locator('.solution-card h3')).to_have_text('Solution')
        page.locator('#tab-task').click()
        page.locator('#settings-button').click()
        page.locator('#pref-theme').select_option('dark')
        expect(page.locator('#pref-setup-help, #pref-layout')).to_have_count(0)
        page.screenshot(path=str(output / 'settings.png'), full_page=True)
        page.locator('#settings-close').click()
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        expect(page.locator('.terminal-panel')).to_be_visible()
        expect(page.locator('#reading-button, .reading-mode')).to_have_count(0)
        expect(page.locator('.task-namespace')).to_contain_text('ckad-d02')
        expect(page.locator('#target-details, .manual-setup')).to_have_count(0)
        page.reload()
        expect(page.locator('#target-details')).to_have_count(0)
        expect(page.locator('.task-namespace')).to_contain_text('ckad-d02')
        page.locator('#settings-button').click()
        expect(page.locator('#pref-setup-help, #pref-layout')).to_have_count(0)
        page.locator('#settings-close').click()
        page.locator('#tab-help').click()
        expect(page.locator('.hint-card')).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
        page.screenshot(path=str(output / 'live-dark.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(output / 'live-mobile.png'), full_page=True)
        inputs = [json.loads(frame).get('data', '') for frame in frames if isinstance(frame, str) and json.loads(frame).get('type') == 'input']
        assert not inputs, [(len(data), data.startswith('\x1b'), data in ('\r', '\n')) for data in inputs]
        assert not errors, errors
        browser.close()
    print(f'PASS: real HTTP assets and frontend, settings persistence, automatic question preparation, scoped terminals, no injected shell input, no page errors. Opening questions may create their starter fixtures; no reset was requested. Screenshots: {output}')


def live_question_workflow(url):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
        page=browser.new_page(viewport={'width':1512,'height':980})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.add_init_script("if(!sessionStorage.getItem('question-workflow')){localStorage.setItem('flightdeck-set','focused');localStorage.setItem('flightdeck-question','s01');sessionStorage.setItem('question-workflow','1');}")
        page.goto(url)
        expect(page.locator('.question-card')).to_have_count(16)
        expect(page.locator('#grade-button')).to_be_enabled(timeout=240000)
        expect(page.locator('.task-id')).to_have_text('Question 1')
        expect(page.locator('#prepare-button')).not_to_be_visible()
        expect(page.locator('#terminal-connection')).to_have_text('Connected')
        page.locator('#terminal-main .xterm-helper-textarea').focus()
        page.keyboard.type("printf 'NS='; kubectl config view --minify -o 'jsonpath={..namespace}'; printf '\\n'; kubectl get deployment api-server -o name; pwd")
        page.keyboard.press('Enter')
        expect(page.locator('#terminal-main')).to_contain_text('NS=ckad-s01',timeout=30000)
        expect(page.locator('#terminal-main')).to_contain_text('deployment.apps/api-server',timeout=30000)
        page.locator('#next-task').click()
        expect(page.locator('#grade-button')).to_be_enabled(timeout=240000)
        expect(page.locator('.task-id')).to_have_text('Question 2')
        expect(page.locator('#terminal-connection')).to_have_text('Connected')
        page.locator('#terminal-main .xterm-helper-textarea').focus()
        page.keyboard.type("printf 'NS='; kubectl config view --minify -o 'jsonpath={..namespace}'; printf '\\n'; pwd")
        page.keyboard.press('Enter')
        expect(page.locator('#terminal-main')).to_contain_text('NS=ckad-s02',timeout=30000)
        page.locator('#previous-task').click()
        expect(page.locator('#grade-button')).to_be_enabled(timeout=30000)
        expect(page.locator('#terminal-connection')).to_have_text('Connected')
        page.locator('#terminal-main .xterm-helper-textarea').focus()
        page.keyboard.type("printf 'RETURN_NS='; kubectl config view --minify -o 'jsonpath={..namespace}'; printf '\\n'")
        page.keyboard.press('Enter')
        expect(page.locator('#terminal-main')).to_contain_text('RETURN_NS=ckad-s01',timeout=30000)
        assert not errors,errors
        browser.close()
    print('PASS: Focused 1 creates api-server before showing the question; terminal defaults to ckad-s01, switches to isolated ckad-s02 for question 2, and returns to ckad-s01. No reset or answer grading was run.')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--live-question-workflow':
        live_question_workflow(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == '--live':
        live_smoke(sys.argv[2])
    else:
        main()
