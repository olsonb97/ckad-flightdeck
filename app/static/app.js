import TerminalBundle from './vendor/terminal.js';
import { Enhancements } from './enhancements.js?v=8';
let enhancements = null;
const { Terminal, FitAddon } = TerminalBundle;
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const rich = value => esc(value).replace(/`([^`]+)`/g, '<code>$1</code>');
const icon = path => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
const storage = {
  get(key, fallback = '') { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* A storage policy must not break the lab. */ } },
};
const domainNames = { design: 'Design & build', deployment: 'Deployment', observability: 'Observability', configuration: 'Config & security', networking: 'Networking' };
const state = {
  data: null, csrf: '', connected: false, selected: storage.get('flightdeck-question', 'd01'),
  setId: storage.get('flightdeck-set', 'core'), search: '', tab: 'task', hints: {}, solutions: {},
  terminal: 'main', terms: {}, serverDelta: 0, taskSignature: '', listSignature: '',
  examSignature: '', operationSignature: '', modal: null, lastOp: null, requesting: false,
  toastTimer: null, dismissedOp: null, renderedTaskId: null, renderedTab: 'task', gradeTask: null,
  fontSize: Math.round(Math.max(10, Math.min(22, Number(storage.get('flightdeck-font', '14')) || 14))),
  noteDrafts: {}, dirtyNotes: new Set(), failedNotes: new Set(), pendingSaves: {}, noteRevision: 0, noteVersions: {}, openCheckpoint: null,
  openedQuestions: new Set(), openingQuestions: new Set(), failedQuestions: new Set(),
};
function focusSelector(element = document.activeElement) {
  if (element.id) return '#' + CSS.escape(element.id);
  if (element.dataset.checkStep !== undefined) return `[data-check-step="${Number(element.dataset.checkStep)}"]`;
  if (element.matches('summary') && element.parentElement.dataset.disclosure) return `[data-disclosure="${CSS.escape(element.parentElement.dataset.disclosure)}"] > summary`;
  return null;
}
function restoreFocus(selector) {
  if (!selector) return;
  const fallback = {'#solution-button':'#hide-solution', '#hide-solution':'#solution-button'};
  const element = $(selector) || (fallback[selector] && $(fallback[selector]));
  if (element && !element.disabled && element.getClientRects().length) element.focus({preventScroll:true});
}
let pollBusy = false, notesTimer = null;
const mockActive = exam => !!exam && ['running', 'preparing', 'grading', 'expired'].includes(exam.state);
const activeExam = () => mockActive(state.data?.exam);
const currentTask = () => state.data?.tasks.find(task => task.id === state.selected);
const currentSet = () => state.data?.sets[state.setId];
const studyTasks = () => state.data?.tasks.filter(task => task.set_id === state.setId) || [];
const isBusy = () => state.data?.operation?.state === 'running';
const smallNavigation = () => window.matchMedia('(max-width: 1100px)').matches;
const questionFailed = task => !!task && (state.failedQuestions.has(task.id) || state.data?.operation?.state === 'error' && state.data.operation.task_id === task.id && ['prepare', 'reset'].includes(state.data.operation.kind));
const labFailed = () => !state.data?.environment.ready && ['error', 'unavailable'].includes(state.data?.environment.phase);
const questionWaitMessage = task => labFailed() ? 'Lab startup failed. See the launcher for details.' : !state.data?.environment.ready ? 'Waiting for lab…' : questionFailed(task) ? 'Could not prepare this question. Please retry.' : 'Preparing question…';
const questionReady = task => !!task?.progress.prepared && (activeExam() || state.data?.exam?.state === 'finished' || state.openedQuestions.has(task.id) && !state.openingQuestions.has(task.id) && !questionFailed(task));
const questionNumber = task => taskPool().findIndex(item => item.id === task.id) + 1;

async function ensureQuestion() {
  const task = currentTask();
  if (!task || !state.connected || !state.data.environment.ready || activeExam() || state.data.exam?.state === 'finished' || isBusy() || state.requesting || state.openedQuestions.has(task.id) || state.openingQuestions.has(task.id)) return;
  state.openingQuestions.add(task.id);
  const result = await act(`/api/task/${task.id}/prepare`, {}, true);
  if (!result) await refresh();
  state.openingQuestions.delete(task.id);
  if (result) state.openedQuestions.add(task.id);
  else if (!isBusy()) { state.openedQuestions.add(task.id); state.failedQuestions.add(task.id); }
  if (state.selected === task.id) render();
}

function toast(message, error = false) {
  clearTimeout(state.toastTimer);
  $('#toast').textContent = message;
  $('#toast').className = 'toast' + (error ? ' error' : '');
  state.toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), error ? 9000 : 4200);
}
async function api(path, data) {
  const options = data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify(data) };
  const response = await fetch(path, options);
  const text = await response.text();
  let value;
  try { value = JSON.parse(text); } catch { value = { error: text || response.statusText }; }
  if (!response.ok) {
    if (response.status === 403 && path !== '/api/bootstrap') {
      // Fetch the new token but never retry a write automatically.
      const fresh = await fetch('/api/bootstrap');
      if (fresh.ok) { const bootstrap = await fresh.json(); if (bootstrap.csrf) state.csrf = bootstrap.csrf; }
      throw new Error('The app session changed. Reconnected; please try that action again.');
    }
    throw new Error(value.error || 'The request could not be completed.');
  }
  return value;
}
async function refresh(initial = false) {
  if (pollBusy) return;
  pollBusy = true;
  const firstLoad = !state.data, noteRevision = state.noteRevision;
  try {
    let data = await api(initial || !state.csrf ? '/api/bootstrap' : '/api/state');
    if (state.data?.instance && data.instance && data.instance !== state.data.instance) {
      data = await api('/api/bootstrap');
      state.openedQuestions.clear(); state.failedQuestions.clear();
      for (const item of Object.values(state.terms)) { const old=item.ws; item.ws=null; old?.close(); item.retryAt=0; item.received=false; }
    }
    if (data.csrf) state.csrf = data.csrf;
    for (const task of data.tasks) {
      if (!mockActive(data.exam) && state.noteVersions[task.id] > noteRevision) task.progress.notes = state.data.tasks.find(item => item.id === task.id)?.progress.notes ?? '';
    }
    if (mockActive(data.exam) && (!activeExam() || data.exam.id !== state.data?.exam?.id)) {
      clearTimeout(notesTimer); notesTimer = null;
      clearTimeout(state.toastTimer); $('#toast').classList.add('hidden');
      state.hints = {}; state.solutions = {}; state.openCheckpoint = null;
      state.tab = 'task'; state.search = '';
      $('#search').value = '';
      if (['results', 'mock'].includes(state.modal)) closeModal();
      $('#modal-body').replaceChildren();
    }
    if (firstLoad && data.operation?.state === 'done') state.lastOp = data.operation.id;
    state.data = data;
    state.connected = true;
    state.serverDelta = data.server_time * 1000 - Date.now();
    if (!Object.hasOwn(data.sets, state.setId)) state.setId = 'core';
    const inExam = activeExam() || data.exam?.state === 'finished';
    if (inExam && data.exam.tasks.length) {
      state.setId = data.exam.set_id || data.tasks.find(task => task.id === data.exam.tasks[0])?.set_id || 'core';
      if (!data.exam.tasks.includes(state.selected)) { flushNotes(); state.selected = data.exam.tasks[0]; state.tab = 'task'; }
    } else if (!studyTasks().some(task => task.id === state.selected)) {
      flushNotes(); state.selected = studyTasks()[0].id; state.tab = 'task';
    }
    storage.set('flightdeck-set', state.setId);
    storage.set('flightdeck-question', state.selected);
    render();
  } catch (error) {
    state.connected = false;
    if (initial) toast('Could not connect. Retrying…', true);
    $('#lab-warning').className = 'lab-warning error';
    if ($('#lab-warning').dataset.state !== 'offline') $('#lab-warning').textContent = 'App disconnected. Reconnecting…';
    $('#lab-warning').dataset.state = 'offline';
    renderButtons();
  } finally { pollBusy = false; }
}
async function act(path, data = {}, quiet = false) {
  if (state.requesting) return null;
  const focus = focusSelector(), taskId = state.selected;
  state.requesting = true;
  renderButtons();
  try {
    const result = await api(path, data);
    await refresh();
    return result;
  } catch (error) {
    if (!quiet) toast(error.message, true);
    return null;
  } finally {
    state.requesting = false;
    renderButtons();
    if (state.selected === taskId && document.activeElement === document.body) restoreFocus(focus);
  }
}
function taskPool() {
  const exam = state.data?.exam;
  if (activeExam() || exam?.state === 'finished') return exam.tasks.map(id => state.data.tasks.find(task => task.id === id)).filter(Boolean);
  return studyTasks();
}
function gradeFor(task) {
  if (activeExam()) return null;
  const exam = state.data.exam;
  if (exam?.state === 'finished' && exam.results?.[task.id]) return exam.results[task.id];
  return task.progress.last_grade;
}
function visibleTasks() {
  return taskPool().filter(task => `${task.id} ${task.title} ${task.requirements.join(' ')}`.toLowerCase().includes(state.search));
}
function switchTask(id, tab = 'task') {
  if (!taskPool().some(task => task.id === id)) return;
  flushNotes();
  if (state.selected !== id) {
    state.openedQuestions.delete(id); state.failedQuestions.delete(id);
    for (const item of Object.values(state.terms)) { const old = item.ws; item.ws = null; old?.close(); item.received = false; item.retryAt = 0; item.taskId = null; item.term.reset(); }
  }
  state.selected = id;
  state.tab = activeExam() ? 'task' : tab;
  storage.set('flightdeck-question', id);
  state.taskSignature = '';
  render();
  const pages = $('.task-pages');
  if (pages) pages.scrollTop = 0;
  closeSidebar();
}
function adjacentTask(direction) {
  let tasks = visibleTasks();
  if (!tasks.some(task => task.id === state.selected)) tasks = taskPool();
  const index = tasks.findIndex(task => task.id === state.selected);
  return tasks[index + direction];
}
function renderLabWarning() {
  const env = state.data.environment, notice = $('#lab-warning');
  const phase = env.ready ? 'ready' : env.phase, signature = `${phase}:${activeExam()}:${isBusy()}`;
  if (notice.dataset.state === signature) return;
  notice.dataset.state = signature;
  notice.className = 'lab-warning' + (env.ready ? ' hidden' : '') + (phase === 'error' ? ' error' : '');
  notice.textContent = env.ready ? '' : phase === 'starting' ? 'Starting lab…' : 'Lab startup failed. See the launcher for details.';
  if (phase === 'error' && !activeExam()) {
    const retry = document.createElement('button');
    retry.id = 'retry-lab'; retry.className = 'quiet'; retry.textContent = 'Retry'; retry.disabled = isBusy();
    notice.append(retry);
  }
}
function render() {
  const data = state.data;
  renderLabWarning();
  const tasks = studyTasks(), completed = tasks.filter(task => task.progress.last_grade?.complete).length;
  $('#completed-count').textContent = `${completed} / ${tasks.length}`;
  $('#mock-button').textContent = activeExam() ? 'Mock running' : data.exam?.state === 'finished' ? 'Mock results' : 'Timed mock';
  renderOperation();
  const op = data.operation;
  if (op?.state === 'done' && state.lastOp !== op.id) {
    state.lastOp = op.id;
    if (op.kind === 'grade' && !activeExam()) {
      if (state.gradeTask === state.selected) state.tab = 'results';
      const result = op.result;
      toast(result.has_errors ? 'Some checks could not run.' : result.complete ? 'All checks passed.' : `${result.earned}/${result.possible} checks passed.`, result.has_errors);
      state.gradeTask = null;
    }
    if (op.kind === 'check_step' && !activeExam()) {
      const result = op.result.criteria[0];
      state.openCheckpoint = {taskId: op.result.task_id, index: op.result.criterion};
      toast(result.status === 'pass' ? 'Step verified.' : result.status === 'error' ? 'Check unavailable. See feedback.' : 'Not yet. See feedback.', result.status === 'error');
    }
    if (op.kind === 'exam_submit') showResults();
  }
  renderSidebar(); renderTask(); renderExamBar(); renderButtons();
  connectTerm(state.terminal);
  updateNavigationState();
  ensureQuestion();
}
function renderOperation() {
  const op = state.data.operation;
  const visible = op && !['prepare', 'reset'].includes(op.kind) && ['running', 'error'].includes(op.state) && op.id !== state.dismissedOp;
  const signature = JSON.stringify([visible, op?.state, op?.message, op?.current, op?.total, op?.error]);
  if (signature === state.operationSignature) return;
  state.operationSignature = signature;
  $('#operation-bar').className = 'operation-bar' + (!visible ? ' hidden' : '') + (op?.state === 'error' ? ' error' : '');
  if (!visible) return;
  $('#operation-bar').innerHTML = op.state === 'error'
    ? '<span>Could not complete that action. Please try again.</span><button id="dismiss-operation" aria-label="Dismiss operation error">×</button>'
    : `<span class="spinner" aria-hidden="true"></span><span>${esc(op.message)}</span>${op.total > 1 ? `<progress value="${op.current}" max="${op.total}" aria-label="Operation progress"></progress>` : ''}`;
}
function renderSidebar() {
  const tasks = visibleTasks();
  const signature = JSON.stringify([state.setId, state.search, state.selected, state.data.exam?.id, state.data.exam?.state,
    state.data.tasks.map(task => [task.id, task.progress.flagged, gradeFor(task)?.percent, task.progress.prepared])]);
  if (signature === state.listSignature) return;
  state.listSignature = signature;
  $('#set-selector').innerHTML = Object.entries(state.data.sets).map(([id, set]) => `<option value="${esc(id)}">${esc(set.name)}</option>`).join('');
  $('#set-selector').value = state.setId;
  $('#question-list').innerHTML = tasks.length ? tasks.map(task => {
    const grade = gradeFor(task);
    const number = String(questionNumber(task)).padStart(2, '0');
    const mark = task.progress.flagged ? '⚑' : grade?.complete ? '✓' : grade ? `${Math.round(grade.percent)}%` : '';
    const status = task.progress.flagged ? 'Flagged for review' : grade?.complete ? 'Complete' : grade ? `${Math.round(grade.percent)} percent` : task.progress.prepared ? 'Lab prepared' : 'Not started';
    return `<button class="question-card ${state.selected === task.id ? 'active' : ''}" data-task="${task.id}" data-domain="${task.domain}" aria-current="${state.selected === task.id}" title="${esc(task.level)} · ${task.minutes} min · ${status}"><span class="question-number">${number}</span><span class="question-name">${esc(task.title)}</span><span class="question-mark ${task.progress.flagged ? 'flag' : grade?.complete ? 'pass' : ''}" aria-label="${status}">${mark}</span></button>`;
  }).join('') : '<p class="empty-list">No matching questions.</p>';
  updateAdjacentButtons();
}
function renderTask() {
  const task = currentTask();
  if (!task) return;
  const exam = activeExam(), grade = gradeFor(task), ready = questionReady(task), failed = questionFailed(task);
  if (exam) state.tab = 'task';
  const signature = JSON.stringify([task.id, task.progress.prepared, task.progress.flagged, task.progress.notes, task.progress.started_at, task.progress.step_checks, grade, exam, ready, failed, state.data.environment.ready, state.data.environment.phase, state.data.exam?.state, state.hints[task.id], state.solutions[task.id]]);
  if (signature === state.taskSignature) { applyTaskTab(); return; }
  state.taskSignature = signature;
  const sameTask = state.renderedTaskId === task.id;
  const notes = exam ? '' : state.dirtyNotes.has(task.id) ? state.noteDrafts[task.id] : task.progress.notes ?? '';
  const focused = sameTask && $('#task-content').contains(document.activeElement) ? focusSelector() : null;
  const keepFocus = !exam && sameTask && document.activeElement === $('#task-notes');
  const selection = keepFocus ? [$('#task-notes').selectionStart, $('#task-notes').selectionEnd] : null;
  const oldScroll = sameTask && state.renderedTab === state.tab ? $('.task-pages')?.scrollTop || 0 : 0;
  const disclosures = new Map(sameTask ? $$('.task-pages details[data-disclosure]').map(el => [el.dataset.disclosure, el.open]) : []);
  state.renderedTaskId = task.id;
  $('.task-panel').dataset.domain = task.domain;
  const hints = state.hints[task.id], solution = state.solutions[task.id];
  const resultBadge = grade ? `<span class="tab-badge ${grade.has_errors ? 'error' : grade.complete ? 'pass' : ''}" aria-label="${grade.earned} checks passed">${grade.has_errors ? '!' : grade.complete ? '✓' : `${grade.earned}/${grade.possible}`}</span>` : '';
  $('#task-content').innerHTML = `
    <header class="task-header">
      <div class="task-topline">${!exam ? `<span class="domain-tag"><i class="domain-dot" aria-hidden="true"></i>${domainNames[task.domain]}</span>` : ''}<span class="task-id">Question ${questionNumber(task)}</span><div class="task-navigation"><button id="previous-task" class="icon-button" aria-label="Previous question" title="Previous question">${icon('M15 6l-6 6 6 6')}</button><button id="next-task" class="icon-button" aria-label="Next question" title="Next question">${icon('M9 6l6 6-6 6')}</button></div></div>
      <div class="task-heading"><h2>${esc(task.title)}</h2><button id="flag-task" class="flag-button icon-button ${task.progress.flagged ? 'flagged' : ''}" aria-label="Flag question for review" aria-pressed="${!!task.progress.flagged}" title="${task.progress.flagged ? 'Remove review flag' : 'Flag for review'}">${icon('M5 21V4m0 0c5-3 9 3 14 0v10c-5 3-9-3-14 0')}</button></div>
      ${!exam ? `<div class="task-meta"><span>${esc(task.level)}</span><span>${task.minutes} min</span></div>` : ''}
    </header>
    ${!exam ? `<nav class="task-tabs" role="tablist" aria-label="Question panels">
      <button class="task-tab" id="tab-task" data-tab="task" role="tab" aria-controls="page-task">Task</button>
      <button class="task-tab" id="tab-results" data-tab="results" role="tab" aria-controls="page-results">Checks ${resultBadge}</button>
      <button class="task-tab" id="tab-help" data-tab="help" role="tab" aria-controls="page-help">Help</button>
      <button class="task-tab" id="tab-notes" data-tab="notes" role="tab" aria-controls="page-notes">Notes<span id="notes-indicator" class="note-indicator ${notes ? '' : 'hidden'}" aria-label="Has notes"></span></button>
    </nav>` : ''}
    <div class="task-pages">
      <section class="task-page" id="page-task" ${exam ? 'aria-label="Question"' : 'role="tabpanel" aria-labelledby="tab-task"'}>
        ${ready || state.data.exam?.state === 'finished' ? `<p class="task-namespace">Namespace <code>${esc(task.namespace)}</code></p>
        <ol class="requirements">${task.requirements.map(requirement => `<li>${rich(requirement)}</li>`).join('')}</ol>
        ${task.starter_files.length ? `<div class="section-label">Starter files</div><ul class="starter-list">${task.starter_files.map(file => `<li><code>${esc(file)}</code></li>`).join('')}</ul>` : ''}` : `<p class="question-loading" role="status">${questionWaitMessage(task)}</p>`}
      </section>
      ${!exam ? `<section class="task-page" id="page-results" role="tabpanel" aria-labelledby="tab-results" hidden>${state.data.exam?.state === 'finished' && grade ? renderGrade(grade) : renderPracticeChecks(task, grade)}</section>
      <section class="task-page" id="page-help" role="tabpanel" aria-labelledby="tab-help" hidden>
        <section class="support-card hint-card"><div class="support-heading"><h3>Hints</h3><button id="hint-button" class="quiet">${hints?.length ? 'Next hint' : 'Show hint'}</button></div>${hints ? `<ol class="hints">${hints.map(hint => `<li>${rich(hint)}</li>`).join('')}</ol>` : ''}</section>
        ${!solution ? `<section class="support-card solution-card"><div class="support-heading"><h3>Solution</h3><button id="solution-button" class="quiet">Reveal</button></div></section>` : renderSolution(solution)}
        <details class="docs-section" data-disclosure="docs"><summary>Documentation</summary><div class="docs-links">${task.docs.map(doc => `<a href="${esc(doc.url)}" target="_blank" rel="noopener noreferrer">${esc(doc.label)}<span aria-hidden="true">↗</span></a>`).join('')}</div></details>
      </section>
      <section class="task-page" id="page-notes" role="tabpanel" aria-labelledby="tab-notes" hidden><textarea id="task-notes" class="notes" maxlength="12000" placeholder="Commands to remember, mistakes to revisit…" aria-label="Notes for this question">${esc(notes)}</textarea><div id="notes-status" class="notes-status" aria-live="polite">${state.failedNotes.has(task.id) ? 'Not saved. Edit to retry.' : state.dirtyNotes.has(task.id) ? 'Saving…' : notes ? 'Saved.' : ''}</div></section>` : ''}
    </div>`;
  applyTaskTab();
  for (const detail of $$('.task-pages details[data-disclosure]')) if (disclosures.has(detail.dataset.disclosure)) detail.open = disclosures.get(detail.dataset.disclosure);
  if (state.openCheckpoint?.taskId === task.id) {
    const detail = $(`[data-disclosure="checkpoint-${state.openCheckpoint.index}"]`);
    if (detail && !detail.closest('.pass')) detail.open = true;
    state.openCheckpoint = null;
  }
  $('.task-pages').scrollTop = oldScroll;
  if (keepFocus) { $('#task-notes').focus({ preventScroll: true }); $('#task-notes').setSelectionRange(...selection); }
  else restoreFocus(focused);
  updateAdjacentButtons();
}
function renderPracticeChecks(task, grade) {
  return `<section class="practice-checks" aria-label="Practice checkpoints">
    ${grade ? `<div class="grade-summary ${grade.has_errors ? 'error' : grade.complete ? 'pass' : ''}" title="Last full check; later edits are not included"><strong>${grade.earned} / ${grade.possible}</strong><div>${grade.has_errors ? 'Last full check · errors' : 'Last full check'}</div></div>` : ''}
    ${(task.practice_checks || []).map((label, index) => {
      const previous = task.progress.step_checks?.[index];
      const checkedAt = previous?.checked_at ?? 0;
      const result = task.progress.prepared && checkedAt >= (task.progress.started_at || 0) ? previous : null;
      const status = result?.status || 'unchecked';
      return `<article class="practice-step ${status}"><header><h4>${esc(label)}</h4><button class="quiet" data-check-step="${index}" aria-label="Check step ${index + 1}: ${esc(label)}">${result ? 'Recheck' : 'Check'}</button></header>
        ${result ? `<details class="checkpoint-feedback" data-disclosure="checkpoint-${index}"><summary><strong>${status === 'pass' ? 'Verified' : status === 'error' ? 'Could not check' : 'Not yet'}</strong><span>Feedback</span></summary><p class="step-result">${esc(result.detail)}</p>${renderFeedback(result.feedback)}${result.checked_at ? `<p class="checkpoint-time">Checked ${new Date(result.checked_at * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</p>` : ''}</details>` : ''}</article>`;
    }).join('')}</section>`;
}
function renderFeedback(feedback) {
  if (!feedback) return '';
  return `<div class="learning-feedback"><h5>What you’re learning</h5><p>${rich(feedback.concept)}</p>${feedback.focus ? `<p class="field-focus"><strong>Field focus:</strong> <code>${esc(feedback.focus)}</code></p>` : ''}<h5>Next step</h5><p>${rich(feedback.next)}</p><details class="inspection-command"><summary>Inspection command</summary><pre tabindex="0"><code>${esc(feedback.command)}</code></pre></details></div>`;
}
function renderSolution(answer) {
  const guide = answer.guide;
  return `<article class="walkthrough" aria-label="Worked answer">
    <div class="walkthrough-heading"><h3>Solution</h3><button id="hide-solution" class="quiet">Hide</button></div>
    <p class="explanation">${rich(answer.explanation)}</p>
    ${guide ? `<ol class="walkthrough-steps">${guide.steps.map((step, index) => `<li><span class="step-number" aria-hidden="true">${index + 1}</span><p>${rich(step)}</p></li>`).join('')}</ol>` : ''}
    <details class="answer-section reference-solution" data-disclosure="solution"><summary>Commands & YAML</summary><div class="copy-row"><span>Bash</span><button id="copy-solution">Copy solution</button></div><pre tabindex="0" aria-label="Reference solution commands"><code>${esc(answer.solution)}</code></pre></details>
    ${guide ? `<details class="answer-section verification-section" data-disclosure="verification"><summary>Verify your work</summary><div class="copy-row"><span>Bash</span><button id="copy-verification">Copy checks</button></div><pre tabindex="0" aria-label="Verification commands"><code>${esc(guide.verification)}</code></pre><div class="expected-result"><strong>Expected result</strong><p>${rich(guide.expected)}</p></div></details>
    <details class="answer-section pitfall-card" data-disclosure="pitfall"><summary>Common mistake</summary><p>${rich(guide.pitfall)}</p></details>
    <details class="answer-section checklist-section" data-disclosure="checklist"><summary>Completion checklist</summary><ul>${guide.checklist.map(item => `<li>${rich(item)}</li>`).join('')}</ul></details>` : ''}
  </article>`;
}
function renderGrade(grade) {
  return `<div class="grade-summary ${grade.has_errors ? 'error' : grade.complete ? 'pass' : ''}"><strong>${Math.round(grade.percent)}%</strong><div>${grade.earned} / ${grade.possible} checks passed<small>${grade.has_errors ? 'Provisional: resolve the check errors.' : grade.complete ? 'All requirements verified.' : 'Fix the remaining checks and try again.'}</small></div></div>
    <ul class="criteria">${grade.criteria.map((criterion, index) => `<li class="${esc(criterion.status)}"><details data-criterion="${index}" data-disclosure="criterion-${index}"><summary><span aria-label="${esc(criterion.status)}">${criterion.status === 'pass' ? '✓' : criterion.status === 'error' ? '!' : '×'}</span><span>${esc(criterion.label)}</span></summary><div class="criterion-detail">${esc(criterion.detail)}</div>${renderFeedback(criterion.feedback)}</details></li>`).join('')}</ul>
    <p class="grade-time">${grade.checked_at ? `Checked ${new Date(grade.checked_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ` : ''}Results reflect the last check, not later edits.</p>`;
}
function applyTaskTab() {
  state.renderedTab = state.tab;
  $$('.task-tab').forEach(button => {
    const active = button.dataset.tab === state.tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $$('.task-page').forEach(page => { page.hidden = page.id !== `page-${state.tab}`; });
}
function setTaskTab(tab, focus = false) {
  if (!['task', 'results', 'help', 'notes'].includes(tab) || (activeExam() && tab !== 'task')) return;
  state.tab = tab;
  applyTaskTab();
  $('.task-pages').scrollTop = 0;
  if (focus) $(`#tab-${tab}`).focus();
}
function updateAdjacentButtons() {
  if ($('#previous-task')) $('#previous-task').disabled = !adjacentTask(-1);
  if ($('#next-task')) $('#next-task').disabled = !adjacentTask(1);
}
function renderButtons() {
  $('#mock-button').disabled = !state.connected || (isBusy() && !activeExam());
  $('#set-selector').hidden = activeExam() || state.data?.exam?.state === 'finished';
  $('#set-selector').disabled = !state.connected || isBusy() || state.requesting || activeExam() || state.data?.exam?.state === 'finished';
  $('#mock-button').hidden = activeExam() || state.data?.exam?.state === 'finished';
  $('#completed-count').hidden = activeExam();
  const task = currentTask();
  if (!task) return;
  const exam = activeExam(), inReport = state.data.exam?.state === 'finished', ready = questionReady(task), failed = questionFailed(task);
  const disabled = !state.connected || !state.data.environment.ready || isBusy() || state.requesting || exam || inReport;
  $('#prepare-button').classList.toggle('hidden', !failed || exam || inReport);
  $('#grade-button').classList.toggle('hidden', !ready || exam || inReport);
  $('#prepare-button').disabled = disabled;
  $('#grade-button').disabled = disabled;
  $('#reset-button').hidden = !ready || exam || inReport;
  $('#reset-button').disabled = disabled;
  $('.task-controls').hidden = exam || inReport || (!ready && !failed);
  $$('[data-check-step]').forEach(button => { button.disabled = disabled || !ready; button.title = !ready ? 'Question is being prepared' : 'Check only this requirement'; });
  if ($('#hint-button')) $('#hint-button').disabled = exam || state.requesting || !state.connected;
  if ($('#solution-button')) $('#solution-button').disabled = exam || state.requesting || !state.connected;
  if ($('#flag-task')) $('#flag-task').disabled = state.requesting || !state.connected;
}
function renderExamBar() {
  const exam = state.data.exam;
  const visible = exam && ['running', 'preparing', 'grading', 'expired', 'finished', 'interrupted'].includes(exam.state);
  $('#exam-bar').classList.toggle('hidden', !visible);
  if (!visible) { state.examSignature = ''; return; }
  const signature = JSON.stringify([exam.state, exam.tasks.length, exam.seed, exam.prepared, exam.graded, exam.has_errors, exam.score, exam.error]);
  if (signature !== state.examSignature) {
    state.examSignature = signature;
    const labels = { running: 'Timed mock', finished: 'Mock complete', preparing: 'Preparing mock', grading: 'Grading mock', expired: 'Time expired', interrupted: 'Mock interrupted' };
    $('#exam-bar').innerHTML = `<span class="exam-caption">${labels[exam.state]}<small>${exam.tasks.length} questions</small></span>${exam.state === 'running' ? '<strong id="countdown"></strong><button id="submit-exam" class="primary">Submit mock</button><button id="abandon-exam" class="quiet">Abandon</button>' :
      exam.state === 'finished' ? `<strong>${exam.has_errors ? 'Provisional ' : ''}${exam.score}%</strong><button id="results-button" class="primary">Review results</button><button id="leave-exam" class="quiet">Back to practice</button>` :
      exam.state === 'interrupted' ? `<span>${esc(exam.error || 'This attempt cannot be scored.')}</span><button id="leave-exam" class="quiet">Back to practice</button>` : `<strong>${exam.state === 'preparing' ? exam.prepared || 0 : exam.graded || 0} / ${exam.tasks.length}</strong>`}`;
  }
  updateCountdown();
}
function updateCountdown() {
  const exam = state.data?.exam;
  if (exam?.state !== 'running' || !$('#countdown')) return;
  const seconds = Math.max(0, Math.ceil((exam.deadline * 1000 - Date.now() - state.serverDelta) / 1000));
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), remainder = seconds % 60;
  $('#countdown').textContent = [hours, minutes, remainder].map(value => String(value).padStart(2, '0')).join(':');
  $('#countdown').classList.toggle('urgent', seconds < 600);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied.'); }
  catch { toast('Clipboard unavailable. Select the text and copy it manually.', true); }
}
// Drafts remain available if an autosave fails. Saves for each task are ordered.
function saveNotes(id) {
  if (activeExam()) return Promise.resolve();
  const notes = state.noteDrafts[id];
  if (notes === undefined) return Promise.resolve();
  const prior = state.pendingSaves[id] || Promise.resolve();
  const next = prior.catch(() => {}).then(async () => {
    if (activeExam()) return;
    try {
      await api(`/api/task/${id}/notes`, { notes });
      if (state.noteDrafts[id] === notes) {
        const task = state.data?.tasks.find(item => item.id === id);
        if (task) task.progress.notes = notes;
        state.noteVersions[id] = ++state.noteRevision;
        state.dirtyNotes.delete(id);
        state.failedNotes.delete(id);
        delete state.noteDrafts[id];
        if (state.selected === id && $('#notes-status')) $('#notes-status').textContent = 'Saved.';
      }
    } catch (error) {
      if (state.noteDrafts[id] === notes) {
        state.failedNotes.add(id);
        if (state.selected === id && $('#notes-status')) $('#notes-status').textContent = 'Not saved. Edit to retry.';
      }
      toast('Notes not saved: ' + error.message, true);
    }
  });
  state.pendingSaves[id] = next;
  return next;
}
function flushNotes() {
  clearTimeout(notesTimer); notesTimer = null;
  return Promise.all([...state.dirtyNotes].map(id => saveNotes(id)));
}
function showModal(kind, title, html) {
  state.modal = kind;
  $('#modal-title').textContent = title; $('#modal-body').innerHTML = html;
  if (!$('#modal').open) $('#modal').showModal();
}
function closeModal() { state.modal = null; $('#modal').close(); }
function showMock() {
  if (activeExam()) { toast('Your mock is running. Use the timer bar to submit or abandon.'); return; }
  if (state.data.exam?.state === 'finished') { showResults(); return; }
  const set = currentSet();
  showModal('mock', 'Start a timed mock', `
    <p>${esc(set.name)} · ${set.mock_tasks} questions · ${set.exam_minutes} minutes</p>
    <div class="notice warning">Starting resets this set’s question labs and files. Notes are kept.</div>
    <p>Hints and checks unlock after you submit. The timer keeps running if you leave the page.</p>
    <div class="modal-actions"><button id="modal-cancel" class="quiet">Cancel</button><button id="confirm-mock" class="primary" ${!state.data.environment.ready || isBusy() ? 'disabled' : ''}>Start mock</button></div>`);
}
function showResults() {
  const exam = state.data.exam;
  if (!exam || exam.state !== 'finished') return;
  showModal('results', 'Mock results', `
    <div class="mock-stats"><div><strong>${exam.score}%</strong><span>${exam.has_errors ? 'provisional score' : 'practice score'}</span></div><div><strong>${Object.values(exam.results).filter(result => result.complete).length}/${exam.tasks.length}</strong><span>completed tasks</span></div></div>
    ${exam.has_errors ? '<div class="notice warning">Some checks could not run; this score is provisional.</div>' : ''}
    <table class="score-table"><thead><tr><th>DOMAIN</th><th style="text-align:right">POINTS</th></tr></thead><tbody>${Object.entries(state.data.domains).map(([id, domain]) => `<tr data-domain="${id}"><td><i class="domain-dot" aria-hidden="true"></i>${esc(domain.short)}</td><td>${exam.domain_scores[id]} / ${exam.domain_weights?.[id] ?? domain.weight}</td></tr>`).join('')}</tbody></table>
    <h3 class="modal-subheading">Review tasks</h3>${exam.tasks.map(id => { const task = state.data.tasks.find(item => item.id === id), result = exam.results[id]; return `<button class="report-question" data-report-task="${id}">${esc(task.title)}<span>${result.earned}/${result.possible}${result.has_errors ? ' !' : ''} →</span></button>`; }).join('')}
    <div class="modal-actions"><button id="close-results" class="primary">Back to questions</button></div>`);
}
// PTY transport remains the same real server-side shell; only presentation changed.
function connectTerm(name) {
  if (!state.csrf) return;
  let item = state.terms[name];
  if (!item) {
    const term = new Terminal({
      fontFamily: '"Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace',
      fontSize: state.fontSize, lineHeight: 1.3, cursorBlink: true, scrollback: 12000, convertEol: false, allowProposedApi: false,
      theme: { background: '#111725', foreground: '#d7e0f1', cursor: '#bda1ff', selectionBackground: '#3c4562', black: '#1b2338', red: '#ff8597', green: '#77d9a8', yellow: '#f1ca7d', blue: '#8cbcff', magenta: '#c6a3fa', cyan: '#7fd7dc', white: '#e0e7f5', brightBlack: '#8390ab', brightRed: '#ffa9b6', brightGreen: '#a4ebc5', brightYellow: '#ffe0a8', brightBlue: '#b8d5ff', brightMagenta: '#e0c5ff', brightCyan: '#b0f2ed', brightWhite: '#ffffff' },
    });
    const fit = new FitAddon(); term.loadAddon(fit); term.open($(`#terminal-${name}`));
    item = state.terms[name] = { term, fit, ws: null, retryAt: 0, status: 'Connecting', received: false, taskId: null };
    term.onData(data => { if (item.ws?.readyState === WebSocket.OPEN && !state.data.terminal_locked && item.taskId === state.selected && questionReady(currentTask())) item.ws.send(JSON.stringify({ type: 'input', data })); });
    term.onResize(size => { if (item.ws?.readyState === WebSocket.OPEN) item.ws.send(JSON.stringify({ type: 'resize', ...size })); });
    new ResizeObserver(() => { if (state.terminal === name) fitTerm(item); }).observe($(`#terminal-${name}`));
  }
  const task = currentTask();
  if (!questionReady(task) || !state.data.environment.ready) { updateTermStatus(); return; }
  if (item.taskId !== task.id) { const old = item.ws; item.ws = null; old?.close(); item.term.reset(); item.received = false; item.retryAt = 0; item.taskId = task.id; }
  if (item.ws && [WebSocket.CONNECTING, WebSocket.OPEN].includes(item.ws.readyState)) { updateTermStatus(); return; }
  if (Date.now() < item.retryAt || state.data.terminal_locked) { updateTermStatus(); return; }
  item.retryAt = Date.now() + 3500; item.status = 'Connecting';
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${scheme}//${location.host}/ws/${name}?token=${encodeURIComponent(state.csrf)}&task=${encodeURIComponent(task.id)}`);
  item.ws = socket; socket.binaryType = 'arraybuffer';
  socket.onopen = () => {
    if (item.ws !== socket) return;
    item.status = 'Connected'; item.term.reset(); fitTerm(item);
    socket.send(JSON.stringify({ type: 'resize', cols: item.term.cols, rows: item.term.rows }));
    updateTermStatus();
  };
  socket.onmessage = event => {
    if (item.ws !== socket) return;
    if (event.data instanceof ArrayBuffer) { item.received = true; item.term.write(new Uint8Array(event.data)); }
    else { try { const message = JSON.parse(event.data); if (message.error) toast(message.error, true); } catch { item.received = true; item.term.write(event.data); } }
    updateTermStatus();
  };
  socket.onclose = () => { if (item.ws === socket) { item.status = 'Disconnected'; item.retryAt = Date.now() + 2000; updateTermStatus(); } };
  socket.onerror = () => { if (item.ws === socket) { item.status = 'Disconnected'; updateTermStatus(); } };
  updateTermStatus();
}
function fitTerm(item) { try { item?.fit.fit(); } catch { /* A hidden or zero-size pane is resized when visible. */ } }
function updateTermStatus() {
  const item = state.terms[state.terminal], locked = state.data?.terminal_locked;
  const waiting = !state.data?.environment.ready || !questionReady(currentTask());
  const open = item?.ws?.readyState === WebSocket.OPEN && item.taskId === state.selected;
  const status = labFailed() ? 'Lab unavailable' : waiting ? 'Preparing question' : locked ? 'Input paused' : item?.status || 'Connecting';
  if ($('#terminal-connection').textContent !== status) $('#terminal-connection').textContent = status;
  $('#terminal-state').title = status;
  $('#terminal-dot').className = labFailed() ? 'error' : open && !locked && !waiting ? 'ready' : item?.status === 'Disconnected' ? 'error' : '';
  $('#terminal-placeholder').classList.toggle('hidden', !waiting && (!!open || (!!item?.received && item?.status !== 'Disconnected')));
  $('#terminal-placeholder-title').textContent = labFailed() ? 'Lab unavailable' : waiting ? questionFailed(currentTask()) ? 'Question unavailable' : 'Preparing question…' : locked ? 'Terminal paused' : item?.status === 'Disconnected' ? 'Disconnected' : 'Connecting…';
  $('#terminal-placeholder-message').textContent = labFailed() ? 'Startup failed. See the launcher for details.' : waiting ? 'The terminal opens when its question is ready.' : locked ? 'A lab operation is running.' : item?.status === 'Disconnected' ? 'Reconnecting…' : '';
  $('#terminal-retry').classList.toggle('hidden', waiting || !!locked || item?.status !== 'Disconnected');
}
function switchTerm(name, focus = true) {
  state.terminal = name;
  $$('.terminal-host').forEach(host => host.classList.toggle('active', host.id === `terminal-${name}`));
  $$('.terminal-tab').forEach(button => { const active = button.dataset.terminal === name; button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
  connectTerm(name);
  requestAnimationFrame(() => { fitTerm(state.terms[name]); if (focus) state.terms[name]?.term.focus(); });
}
function reconnectTerm() {
  const item = state.terms[state.terminal];
  if (item) { const oldSocket = item.ws; item.ws = null; oldSocket?.close(); item.retryAt = 0; }
  connectTerm(state.terminal);
}
function expandTerminal(expanded) {
  $('.terminal-panel').classList.toggle('expanded', expanded);
  $('#terminal-expand').setAttribute('aria-pressed', String(expanded));
  $('#terminal-expand').setAttribute('aria-label', expanded ? 'Restore terminal size' : 'Expand terminal');
  requestAnimationFrame(() => fitTerm(state.terms[state.terminal]));
}
function closeSidebar() {
  $('#sidebar').classList.remove('open'); document.body.classList.remove('sidebar-open'); updateNavigationState();
}
function updateNavigationState() {
  const expanded = smallNavigation() ? $('#sidebar').classList.contains('open') : !document.body.classList.contains('sidebar-collapsed');
  $('#menu-button').setAttribute('aria-expanded', String(expanded));
}
function toggleSidebar() {
  if (smallNavigation()) { const open = !$('#sidebar').classList.contains('open'); $('#sidebar').classList.toggle('open', open); document.body.classList.toggle('sidebar-open', open); }
  else { document.body.classList.toggle('sidebar-collapsed'); storage.set('flightdeck-sidebar', document.body.classList.contains('sidebar-collapsed') ? 'collapsed' : 'open'); }
  updateNavigationState();
}
document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  // Question cards carry their domain only for color styling; resolve tasks first.
  if (button.dataset.task) { switchTask(button.dataset.task); return; }
  if (button.dataset.tab) { setTaskTab(button.dataset.tab); return; }
  if (button.dataset.terminal) { switchTerm(button.dataset.terminal); return; }
  if (button.dataset.reportTask) { closeModal(); switchTask(button.dataset.reportTask, 'results'); return; }
  const id = button.id, tid = state.selected;
  if (id === 'menu-button') toggleSidebar();
  else if (id === 'sidebar-backdrop') closeSidebar();
  else if (id === 'mock-button' && state.data) showMock();
  else if (['modal-close', 'modal-cancel', 'close-results'].includes(id)) closeModal();
  else if (id === 'previous-task' || id === 'next-task') { const task = adjacentTask(id === 'previous-task' ? -1 : 1); if (task) switchTask(task.id); }
  else if (id === 'prepare-button') { state.openedQuestions.delete(tid); state.failedQuestions.delete(tid); await ensureQuestion(); }
  else if (id === 'grade-button') { state.gradeTask = tid; if (!await act(`/api/task/${tid}/grade`)) state.gradeTask = null; }
  else if (id === 'reset-button') { if (confirm('Reset this question? Its namespace and task folder will be recreated. Both terminal sessions will restart.')) { await flushNotes(); await act(`/api/task/${tid}/reset`); } }
  else if (id === 'flag-task') await act(`/api/task/${tid}/notes`, { flagged: !currentTask().progress.flagged });
  else if (button.dataset.checkStep !== undefined) await act(`/api/task/${tid}/check`, {criterion:Number(button.dataset.checkStep)});
  else if (id === 'hint-button') { const result = await act(`/api/task/${tid}/hint`); if (result && !activeExam()) { const previous = state.hints[tid]?.length || 0; state.hints[tid] = result.hints; if (result.hints.length === previous) toast('All hints are shown.'); renderTask(); renderButtons(); } }
  else if (id === 'solution-button') { if (confirm('Reveal the full worked solution? This will be recorded in your progress.')) { const result = await act(`/api/task/${tid}/solution`); if (result && !activeExam()) { state.solutions[tid] = result; renderTask(); renderButtons(); } } }
  else if (id === 'hide-solution') { delete state.solutions[tid]; renderTask(); renderButtons(); }
  else if (id === 'copy-solution') copy(state.solutions[tid].solution);
  else if (id === 'copy-verification') copy(state.solutions[tid].guide.verification);
  else if (id === 'terminal-retry') reconnectTerm();
  else if (id === 'terminal-expand') expandTerminal(!$('.terminal-panel').classList.contains('expanded'));
  else if (id === 'confirm-mock') {
    const setId = state.setId; await flushNotes(); closeModal();
    state.hints = {}; state.solutions = {}; state.search = ''; $('#search').value = ''; state.tab = 'task';
    await act('/api/exam-start', { set_id: setId });
  }
  else if (id === 'submit-exam') { if (confirm(`Submit this mock? Terminal input stops and all ${state.data.exam.tasks.length} tasks will be graded.`)) { await flushNotes(); await act('/api/exam-submit'); } }
  else if (id === 'abandon-exam') { if (confirm('Abandon this mock without a final score?')) await act('/api/exam-leave', { abandon: true }); }
  else if (id === 'leave-exam') { state.tab = 'task'; await act('/api/exam-leave'); }
  else if (id === 'results-button') showResults();
  else if (id === 'retry-lab') await act('/api/retry');
  else if (id === 'dismiss-operation') { state.dismissedOp = state.data.operation?.id; renderOperation(); }
});
$('#set-selector').addEventListener('change', event => {
  if (activeExam() || state.data?.exam?.state === 'finished' || isBusy() || state.requesting) { event.target.value = state.setId; return; }
  const id = event.target.value;
  if (!state.data || !Object.hasOwn(state.data.sets, id)) return;
  state.setId = id; storage.set('flightdeck-set', id);
  state.search = ''; $('#search').value = '';
  state.listSignature = ''; state.openCheckpoint = null;
  switchTask(studyTasks()[0].id);
});
$('#search').addEventListener('input', event => { state.search = event.target.value.toLowerCase().trim(); if (state.data) renderSidebar(); });
document.addEventListener('input', event => {
  if (event.target.id !== 'task-notes' || activeExam()) return;
  const id = state.selected;
  state.noteDrafts[id] = event.target.value; state.dirtyNotes.add(id); state.failedNotes.delete(id); currentTask().progress.notes = event.target.value;
  $('#notes-status').textContent = 'Saving…'; $('#notes-indicator').classList.toggle('hidden', !event.target.value);
  clearTimeout(notesTimer); notesTimer = setTimeout(() => { notesTimer = null; saveNotes(id); }, 700);
});
$('#modal').addEventListener('close', () => { state.modal = null; });
document.addEventListener('keydown', event => {
  const target = document.activeElement;
  if (event.key === '/' && !document.querySelector('dialog[open]') && !['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) && !target.closest('.xterm')) {
    event.preventDefault();
    if (smallNavigation()) { $('#sidebar').classList.add('open'); document.body.classList.add('sidebar-open'); }
    else document.body.classList.remove('sidebar-collapsed');
    updateNavigationState(); $('#search').focus();
  }
  if (event.key === 'Escape' && !document.querySelector('dialog[open]')) { expandTerminal(false); closeSidebar(); }
  const tab = target.closest('[role="tab"]');
  if (tab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (tabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    const next = tabs[index];
    if (next.dataset.tab) setTaskTab(next.dataset.tab, true);
    else { switchTerm(next.dataset.terminal, false); next.focus(); }
  }
});
window.addEventListener('resize', updateNavigationState);
window.addEventListener('beforeunload', () => {
  if (!state.csrf || activeExam()) return;
  for (const id of state.dirtyNotes) fetch(`/api/task/${id}/notes`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify({ notes: state.noteDrafts[id] }), keepalive: true }).catch(() => {});
});
if (storage.get('flightdeck-sidebar') === 'collapsed') document.body.classList.add('sidebar-collapsed');
updateNavigationState();
enhancements = new Enhancements({
  getState: () => state,
  applyTerminal: font => {
    if(font!==null && font!==undefined) {state.fontSize=Math.max(10,Math.min(22,Number(font)||14));storage.set('flightdeck-font',state.fontSize);}
    for(const item of Object.values(state.terms)){item.term.options.fontSize=state.fontSize;fitTerm(item);}
  },
});
await refresh(true);
setInterval(() => refresh(), 1300);
setInterval(updateCountdown, 250);
