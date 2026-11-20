const byId = (id) => document.getElementById(id);
const form = byId('run-form');
const query = byId('query');
const editor = byId('question-editor');
const draftModel = byId('draft-model');
const draftModelId = byId('draft-model-id');
const draftBudget = byId('draft-budget');
const runButton = byId('run');
const stopButton = byId('stop');
const errorMessage = byId('run-error');
const reasoning = byId('reasoning');
const reasoningText = byId('reasoning-text');
const reasoningPlaceholder = byId('reasoning-placeholder');
const judgePayload = byId('judge-payload');
const handoffLink = byId('handoff-link');
const answerLink = byId('answer-link');
const answerText = byId('answer-text');
const answerPlaceholder = byId('answer-placeholder');
const answerPreview = byId('answer-preview');
const settings = byId('run-settings');
const workspace = byId('workspace');
const compact = window.matchMedia('(max-width: 820px)');
const stageLinks = document.querySelectorAll('.stage-links button');
const stepNames = ['draft', 'handoff', 'judge', 'revision'];
const labels = { accept: 'Accept', tweak: 'Tweak', regenerate: 'Regenerate' };
const routes = { accept: 'Original draft', tweak: 'Revised draft', regenerate: 'Regenerated' };
const setupMessages = {
  draft_key_missing: 'Set DEEPINFRA_API_KEY in your terminal and relaunch Esandel.',
  draft_settings_missing: 'Check ESANDEL_DRAFT_BASE_URL and ESANDEL_DRAFT_MODEL, then relaunch Esandel.',
  draft_url_invalid: 'Set ESANDEL_DRAFT_BASE_URL to an HTTP or HTTPS URL, then relaunch Esandel.',
  judge_key_missing: 'Set OPENAI_API_KEY in your terminal and relaunch Esandel.',
};
const markdown = window.markdownit({ html: false, breaks: true });
markdown.renderer.rules.link_open = () => '';
markdown.renderer.rules.link_close = () => '';
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(tokens[index].content);
const isMac = navigator.platform.startsWith('Mac');
let running = false;
let config;
let answerSource = '';
let traceOrigin;
let traceTimer;
let activeTiming;

byId('shortcut').textContent = isMac ? '⌘ + Enter to run' : 'Ctrl + Enter to run';

function setStatus(state, text) {
  const status = byId('run-status');
  status.dataset.state = state;
  status.textContent = text;
}

function setCurrentStage(id) {
  for (const button of stageLinks) {
    if (button.id === id) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  }
}

function setStep(name, state, label) {
  const step = byId(name + '-step');
  step.dataset.state = state;
  step.querySelector('.step-status').textContent = label;
}

function formatDuration(milliseconds) {
  const rounded = Math.max(0, Math.round(milliseconds));
  return rounded < 1000 ? rounded + ' ms' : (rounded / 1000).toFixed(2) + ' s';
}

function setStepTime(name, text) {
  byId(name + '-step').querySelector('.step-time').textContent = text;
}

function refreshTraceTime() {
  const now = performance.now();
  byId('trace-time').textContent = formatDuration(now - traceOrigin);
  if (activeTiming) {
    setStepTime(activeTiming.name, formatDuration(now - activeTiming.receivedAt));
  }
}

function startStepTiming(name, elapsed) {
  const now = performance.now();
  traceOrigin = now - elapsed;
  activeTiming = { name, elapsed, receivedAt: now };
  setStepTime(name, '0 ms');
  byId('trace-time').textContent = formatDuration(elapsed);
  traceTimer ??= window.setInterval(refreshTraceTime, 100);
}

function finishStepTiming(elapsed) {
  if (!activeTiming) return;
  const duration = elapsed === undefined ? performance.now() - activeTiming.receivedAt
    : elapsed - activeTiming.elapsed;
  setStepTime(activeTiming.name, formatDuration(duration));
  activeTiming = undefined;
}

function finishTraceTiming(elapsed) {
  if (traceTimer === undefined) return;
  window.clearInterval(traceTimer);
  traceTimer = undefined;
  finishStepTiming(elapsed);
  byId('trace-time').textContent = formatDuration(elapsed ?? performance.now() - traceOrigin);
}

function setView(view) {
  workspace.dataset.view = view;
}

function scrollToSection(section) {
  const trace = section.closest('#trace-panel');
  if (trace && !compact.matches) {
    const header = trace.querySelector('.trace-header');
    const offset = section.getBoundingClientRect().top - trace.getBoundingClientRect().top;
    trace.scrollTo({ top: section === byId('workflow-heading') ? 0 : trace.scrollTop + offset - header.offsetHeight - 12 });
    return;
  }
  const chromeHeight = document.querySelector('.topbar').offsetHeight;
  const top = section.getBoundingClientRect().top + window.scrollY - chromeHeight - 16;
  window.scrollTo({ top: Math.max(0, top) });
}

function clearHandoffHighlight() {
  delete handoffLink.dataset.unread;
  handoffLink.removeAttribute('aria-label');
}

for (const button of stageLinks) {
  button.addEventListener('click', () => {
    const target = byId(button.dataset.target);
    if (compact.matches) setView(button === answerLink ? 'answer' : 'trace');
    if (button === handoffLink && !byId('handoff-body').hidden) judgePayload.open = true;
    scrollToSection(target);
    target.focus({ preventScroll: true });
  });
}

byId('view-answer').addEventListener('click', () => answerLink.click());

judgePayload.addEventListener('toggle', () => {
  if (judgePayload.open) clearHandoffHighlight();
});

function selectedDraftModel() {
  if (typeof config?.draftModel !== 'string') return null;
  return config.draftModelChoices?.length ? draftModel.value : draftModelId.value.trim();
}

function updateRunButton() {
  runButton.textContent = editor.hidden ? 'Run again' : 'Run question';
  runButton.disabled = running || !query.value.trim() || config === undefined
    || Boolean(config?.draftIssue || config?.judgeIssue || selectedDraftModel() === '');
}

function showSetup() {
  const issues = byId('setup-issues');
  const messages = config === null
    ? ['Check the project’s Python environment and relaunch Esandel.']
    : [config.draftIssue, config.judgeIssue].filter(Boolean).map((issue) => setupMessages[issue]);
  byId('run-mode').textContent = config === null ? 'Live setup check failed'
    : messages.length ? 'Live setup required' : 'Live draft · GPT‑6.2 Sol review';
  for (const message of messages) {
    const item = document.createElement('li');
    item.textContent = message;
    issues.append(item);
  }
  issues.hidden = messages.length === 0;
  if (typeof config?.draftModel === 'string') {
    if (config.draftModelChoices?.length) {
      for (const { id, label } of config.draftModelChoices) {
        draftModel.add(new Option(label, id));
      }
      draftModel.value = config.draftModel;
      byId('draft-model-choice').hidden = false;
    } else {
      draftModelId.value = config.draftModel;
      byId('draft-model-custom').hidden = false;
    }
  }
  if (config?.defaultDraftMaxTokens) {
    const defaultBudget = config.defaultDraftMaxTokens.toLocaleString();
    draftBudget.placeholder = defaultBudget;
    byId('budget-default').textContent = 'Default ' + defaultBudget + ' tokens';
  }
  updateRunButton();
}

function showEditor(open) {
  editor.hidden = !open;
  byId('question-summary').hidden = open;
  byId('edit-question').hidden = open || running;
  settings.hidden = !open;
  updateRunButton();
}

function setRunning(value) {
  running = value;
  byId('options').disabled = value;
  query.readOnly = value;
  runButton.hidden = value;
  stopButton.hidden = !value;
  byId('edit-question').hidden = value || !editor.hidden;
  updateRunButton();
}

function resetTimeline() {
  for (const name of stepNames) {
    setStep(name, 'pending', 'Pending');
    setStepTime(name, '');
  }
  byId('trace-time').textContent = '—';
  for (const id of ['draft-body', 'handoff-body', 'verdict-body', 'guidance-block', 'draft-text',
    'reasoning-text', 'answer-text', 'answer-preview', 'copy-answer', 'run-error', 'adjust-budget']) {
    byId(id).hidden = true;
  }
  for (const id of ['draft-text', 'reasoning-text', 'judge-input', 'judge-question', 'judge-draft',
    'rationale', 'guidance', 'answer-text', 'answer-route', 'copy-status']) {
    byId(id).textContent = '';
  }
  answerSource = '';
  byId('copy-answer').textContent = 'Copy answer';
  byId('copy-judge').textContent = 'Copy exact JSON';
  delete byId('judge-step').dataset.decision;
  delete answerLink.dataset.ready;
  answerLink.textContent = 'Answer';
  setView('trace');
  clearHandoffHighlight();
  setCurrentStage('reasoning-link');
  reasoning.open = false;
  judgePayload.open = false;
  byId('judge-raw').open = false;
  reasoningPlaceholder.hidden = false;
  reasoningPlaceholder.textContent = 'Waiting for reasoning from the endpoint…';
  answerPlaceholder.hidden = false;
  answerPlaceholder.textContent = 'Waiting for the run to finish…';
}

function markUnreachedSteps() {
  for (const name of stepNames) {
    if (byId(name + '-step').dataset.state === 'pending') setStep(name, 'skipped', 'Did not run');
  }
}

function showFailure(message, draftLimitReached = false) {
  markUnreachedSteps();
  errorMessage.textContent = draftLimitReached
    ? 'The draft reached its token limit. Raise the limit or shorten the question, then run again.'
    : message;
  errorMessage.hidden = false;
  byId('adjust-budget').hidden = !draftLimitReached;
  setStatus('error', 'Failed');
  if (answerText.hidden) answerPlaceholder.textContent = 'The run ended before returning an answer.';
}

function appendText(element, value) {
  const follow = element.scrollHeight - element.scrollTop - element.clientHeight < 12;
  if (!element.firstChild) element.append(document.createTextNode(''));
  element.firstChild.appendData(value);
  element.hidden = false;
  if (follow) element.scrollTop = element.scrollHeight;
}

function showAnswer(event) {
  byId('answer-route').textContent = routes[event.decision];
  answerPlaceholder.hidden = true;
  answerSource = event.answer;
  answerText.innerHTML = markdown.render(answerSource);
  answerText.hidden = false;
  byId('copy-answer').hidden = false;

  const previewText = answerText.querySelector('p, li')?.textContent.trim() || answerText.textContent.trim();
  byId('answer-preview-text').textContent = previewText.replace(/\s+/g, ' ').slice(0, 480);
  answerPreview.hidden = false;
  answerLink.textContent = 'Read answer';
  answerLink.dataset.ready = 'true';
  setCurrentStage('answer-link');
}

function handleEvent(event) {
  const elapsed = event.elapsed_ms;
  switch (event.type) {
    case 'draft_started':
      setStep('draft', 'running', 'Generating');
      startStepTiming('draft', elapsed);
      byId('draft-provider').textContent = event.model;
      byId('draft-body').hidden = false;
      setStatus('running', 'Drafting');
      break;
    case 'reasoning_delta':
      if (reasoningText.hidden) {
        reasoning.open = true;
        reasoningPlaceholder.hidden = true;
      }
      appendText(reasoningText, event.text);
      break;
    case 'draft_delta':
      appendText(byId('draft-text'), event.text);
      break;
    case 'draft_completed': {
      finishStepTiming(elapsed);
      setStep('draft', 'done', 'Completed');
      const draftText = byId('draft-text');
      if (draftText.textContent !== event.draft) draftText.textContent = event.draft;
      draftText.hidden = false;
      if (reasoningText.hidden) {
        reasoningPlaceholder.textContent = 'The endpoint returned draft text only.';
      }
      break;
    }
    case 'judge_started':
      setStep('handoff', 'done', 'GPT‑6.2 Sol');
      setStepTime('handoff', 'At ' + formatDuration(elapsed));
      byId('judge-input').textContent = JSON.stringify(event.input, null, 2);
      byId('judge-question').textContent = event.input.query;
      byId('judge-draft').textContent = event.input.draft;
      byId('handoff-body').hidden = false;
      handoffLink.dataset.unread = 'true';
      handoffLink.setAttribute('aria-label', 'Judge input, draft sent');
      setCurrentStage('handoff-link');
      setStep('judge', 'running', 'Reviewing');
      startStepTiming('judge', elapsed);
      setStatus('running', 'Draft sent to judge');
      break;
    case 'verdict':
      finishStepTiming(elapsed);
      setStep('judge', 'done', labels[event.decision]);
      byId('judge-step').dataset.decision = event.decision;
      byId('rationale').textContent = event.rationale;
      byId('guidance').textContent = event.guidance;
      byId('guidance-block').hidden = !event.guidance;
      byId('verdict-body').hidden = false;
      setCurrentStage('ruling-link');
      setStatus('running', 'Judge ruling · ' + labels[event.decision]);
      break;
    case 'revision_started':
      setStep('revision', 'running', event.decision === 'tweak' ? 'Applying guidance' : 'Regenerating');
      startStepTiming('revision', elapsed);
      setCurrentStage('answer-link');
      setStatus('running', event.decision === 'tweak' ? 'Revising the draft' : 'Writing a fresh answer');
      break;
    case 'final_answer':
      finishTraceTiming(elapsed);
      setStep('revision', event.decision === 'accept' ? 'skipped' : 'done',
        event.decision === 'accept' ? 'Skipped' : 'Completed');
      showAnswer(event);
      break;
    case 'closed': {
      finishTraceTiming();
      const restoreFocus = document.activeElement === stopButton
        || (event.outcome === 'stopped' && document.activeElement === document.body);
      setRunning(false);
      if (restoreFocus) (runButton.disabled ? byId('edit-question') : runButton).focus({ preventScroll: true });
      const activeStep = stepNames.find((name) => byId(name + '-step').dataset.state === 'running');
      if (activeStep === 'draft' && reasoningText.hidden) {
        reasoningPlaceholder.textContent = 'The draft ended before any reasoning arrived.';
      }
      if (event.outcome === 'success') {
        setStatus('done', 'Answer ready');
      } else if (event.outcome === 'stopped') {
        setStatus('idle', 'Stopped');
        if (activeStep) setStep(activeStep, 'skipped', 'Stopped');
        markUnreachedSteps();
        if (answerText.hidden) answerPlaceholder.textContent = 'The run was stopped.';
      } else {
        if (activeStep) setStep(activeStep, 'error', 'Failed');
        showFailure(event.message, event.draftLimitReached);
      }
      break;
    }
  }
}

window.esandel.onEvent(handleEvent);
window.esandel.config().then((result) => {
  config = result;
}, () => {
  config = null;
}).finally(showSetup);

query.addEventListener('input', updateRunButton);
draftModel.addEventListener('change', updateRunButton);
draftModelId.addEventListener('input', updateRunButton);
document.addEventListener('keydown', (event) => {
  if (!runButton.disabled && event.key === 'Enter' && (isMac ? event.metaKey : event.ctrlKey)) {
    event.preventDefault();
    form.requestSubmit();
  }
});

byId('edit-question').addEventListener('click', () => {
  showEditor(true);
  query.focus();
});

byId('adjust-budget').addEventListener('click', () => {
  showEditor(true);
  settings.open = true;
  draftBudget.focus();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (runButton.disabled) return;
  if (!draftBudget.validity.valid) {
    showEditor(true);
    settings.open = true;
    draftBudget.reportValidity();
    return;
  }

  const moveFocus = form.contains(document.activeElement);
  resetTimeline();
  byId('run-navigation').hidden = false;
  byId('question-preview').textContent = query.value.trim();
  showEditor(false);
  setRunning(true);
  if (moveFocus) stopButton.focus({ preventScroll: true });
  setStatus('running', 'Starting run');
  try {
    await window.esandel.start({
      query: query.value,
      draftModel: selectedDraftModel(),
      draftMaxTokens: draftBudget.value ? draftBudget.valueAsNumber : null,
    });
  } catch (error) {
    const restoreFocus = document.activeElement === stopButton;
    setRunning(false);
    if (restoreFocus) runButton.focus({ preventScroll: true });
    showFailure(error.message);
  }
});

stopButton.addEventListener('click', async () => {
  if (stopButton.hasAttribute('aria-disabled')) return;
  stopButton.setAttribute('aria-disabled', 'true');
  try {
    await window.esandel.stop();
  } catch (error) {
    errorMessage.textContent = error.message;
    errorMessage.hidden = false;
  } finally {
    stopButton.removeAttribute('aria-disabled');
  }
});

function bindCopy(id, getText, successMessage) {
  const button = byId(id);
  button.addEventListener('click', async () => {
    const status = byId('copy-status');
    try {
      await window.esandel.copy(getText());
      button.textContent = 'Copied';
      status.textContent = successMessage;
    } catch {
      button.textContent = 'Copy failed';
      status.textContent = 'Could not copy the text.';
    }
  });
}

bindCopy('copy-judge', () => byId('judge-input').textContent, 'Judge input JSON copied.');
bindCopy('copy-answer', () => answerSource, 'Answer source copied.');
