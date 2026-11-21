const byId = (id) => document.getElementById(id);
const form = byId('run-form');
const query = byId('query');
const editor = byId('question-editor');
const draftModel = byId('draft-model');
const draftModelId = byId('draft-model-id');
const draftBudget = byId('draft-budget');
const runButton = byId('run');
const stopButton = byId('stop');
const runRecovery = byId('run-recovery');
const errorMessage = byId('run-error');
const reasoning = byId('reasoning');
const reasoningText = byId('reasoning-text');
const reasoningPlaceholder = byId('reasoning-placeholder');
const judgePayload = byId('judge-payload');
const answerText = byId('answer-text');
const streamedAnswers = {
  draft: { element: byId('draft-text'), source: '' },
  revision: { element: byId('revision-text'), source: '' },
};
const settings = byId('run-settings');
const stepNames = ['draft', 'judge', 'revision', 'answer'];
const steps = Object.fromEntries(stepNames.map((name) => [name, byId(name + '-step')]));
const labels = { accept: 'Accept', tweak: 'Tweak', regenerate: 'Regenerate' };
const routes = { accept: 'Original draft', tweak: 'Revised draft', regenerate: 'Regenerated' };
const setupMessages = {
  draft_key_missing: 'Set DEEPINFRA_API_KEY in your terminal and relaunch Esandel.',
  draft_settings_missing: 'Check ESANDEL_DRAFT_BASE_URL and ESANDEL_DRAFT_MODEL, then relaunch Esandel.',
  draft_url_invalid: 'Set ESANDEL_DRAFT_BASE_URL to an HTTP or HTTPS URL, then relaunch Esandel.',
  judge_key_missing: 'Set OPENAI_API_KEY in your terminal and relaunch Esandel.',
};
const markdown = window.markdownit({ html: false, breaks: true });
markdown.use(window.mdItPluginTex.tex, {
  delimiters: 'all',
  mathFence: true,
  render(source, displayMode) {
    let markup;
    try {
      markup = window.katex.renderToString(source, { displayMode, output: 'mathml', trust: false });
    } catch (error) {
      if (!(error instanceof window.katex.ParseError)) throw error;
      markup = '<code>' + markdown.utils.escapeHtml(source) + '</code>';
    }
    return displayMode ? '<div class="math-display">' + markup + '</div>' : markup;
  },
});
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

function setStep(name, state, label) {
  const step = steps[name];
  step.dataset.state = state;
  step.querySelector('.step-status').textContent = label;
  const summary = step.firstElementChild;
  if (state === 'pending' || state === 'unreached') {
    summary.setAttribute('aria-disabled', 'true');
    summary.tabIndex = -1;
  } else {
    summary.removeAttribute('aria-disabled');
    summary.removeAttribute('tabindex');
  }
}

function formatDuration(milliseconds) {
  const rounded = Math.max(0, Math.round(milliseconds));
  return rounded < 1000 ? rounded + ' ms' : (rounded / 1000).toFixed(2) + ' s';
}

function setStepTime(name, text) {
  steps[name].querySelector('.step-time').textContent = text;
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

function openStep(name) {
  const step = steps[name];
  const previous = Object.values(steps).find((candidate) => candidate.open);
  const focused = document.activeElement;
  const summary = step.firstElementChild;
  const focusWillBeHidden = previous && previous !== step && previous.contains(focused)
    && !previous.firstElementChild.contains(focused);

  step.open = true;
  if (focusWillBeHidden) summary.focus({ preventScroll: true });

  const bounds = summary.getBoundingClientRect();
  const headerBottom = document.querySelector('.topbar').getBoundingClientRect().bottom;
  // Bring the new phase into view without moving an already visible phase.
  if (bounds.top < headerBottom || bounds.bottom + 96 > window.innerHeight) {
    window.scrollBy({ top: bounds.top - headerBottom - 12 });
  }
}

for (const step of Object.values(steps)) {
  const summary = step.firstElementChild;
  summary.addEventListener('click', (event) => {
    if (summary.hasAttribute('aria-disabled')) event.preventDefault();
  });
}

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
    steps[name].open = false;
    setStep(name, 'pending', 'Pending');
    setStepTime(name, '');
  }
  byId('trace-time').textContent = '—';
  for (const id of ['draft-output', 'verdict-body', 'guidance-block', 'reasoning-text', 'revision-text',
    'run-recovery', 'adjust-budget']) {
    byId(id).hidden = true;
  }
  for (const output of Object.values(streamedAnswers)) {
    cancelOutputRender(output);
    output.source = '';
    output.element.replaceChildren();
  }
  for (const id of ['reasoning-text', 'judge-input', 'judge-question', 'judge-draft',
    'rationale', 'guidance', 'revision-note', 'answer-text', 'copy-status']) {
    byId(id).textContent = '';
  }
  answerSource = '';
  byId('copy-answer').textContent = 'Copy answer';
  byId('copy-judge').textContent = 'Copy exact JSON';
  delete steps.judge.dataset.decision;
  reasoning.open = false;
  judgePayload.open = false;
  byId('judge-raw').open = false;
  reasoningPlaceholder.hidden = false;
  reasoningPlaceholder.textContent = 'Waiting for reasoning from the endpoint…';
}

function markUnreachedSteps() {
  for (const name of stepNames) {
    if (steps[name].dataset.state === 'pending') setStep(name, 'unreached', 'Did not run');
  }
}

function showFailure(message, draftLimitReached = false) {
  markUnreachedSteps();
  errorMessage.textContent = draftLimitReached
    ? 'The draft reached its token limit. Raise the limit or shorten the question, then run again.'
    : message;
  runRecovery.hidden = false;
  byId('adjust-budget').hidden = !draftLimitReached;
  setStatus('error', 'Failed');
}

function appendText(element, value) {
  const follow = element.scrollHeight - element.scrollTop - element.clientHeight < 12;
  if (!element.firstChild) element.append(document.createTextNode(''));
  element.firstChild.appendData(value);
  element.hidden = false;
  if (follow) element.scrollTop = element.scrollHeight;
}

function cancelOutputRender(output) {
  window.clearTimeout(output.renderTimer);
  output.renderTimer = undefined;
}

function renderOutput(output, source = output.source) {
  cancelOutputRender(output);
  output.source = source;
  const { element } = output;
  const scrollTop = element.scrollTop;
  const follow = element.scrollHeight - scrollTop - element.clientHeight < 12;
  element.innerHTML = markdown.render(source);
  element.hidden = false;
  element.scrollTop = follow ? element.scrollHeight : scrollTop;
}

function appendOutput(output, delta) {
  output.source += delta;
  // Batch rapid tokens because a delimiter can complete math from an earlier chunk.
  output.renderTimer ??= window.setTimeout(() => renderOutput(output), 75);
}

function showAnswer(event) {
  answerSource = event.answer;
  answerText.innerHTML = markdown.render(answerSource);
  setStep('answer', 'done', routes[event.decision]);
  openStep('answer');
}

function handleEvent(event) {
  const elapsed = event.elapsed_ms;
  switch (event.type) {
    case 'draft_started':
      setStep('draft', 'running', 'Generating');
      startStepTiming('draft', elapsed);
      byId('draft-provider').textContent = event.model;
      openStep('draft');
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
      byId('draft-output').hidden = false;
      appendOutput(streamedAnswers.draft, event.text);
      break;
    case 'draft_completed':
      finishStepTiming(elapsed);
      setStep('draft', 'done', 'Completed');
      byId('draft-output').hidden = false;
      renderOutput(streamedAnswers.draft, event.draft);
      if (reasoningText.hidden) {
        reasoningPlaceholder.textContent = 'The endpoint returned draft text only.';
      }
      break;
    case 'judge_started':
      byId('handoff-time').textContent = 'at ' + formatDuration(elapsed);
      byId('judge-input').textContent = JSON.stringify(event.input, null, 2);
      byId('judge-question').textContent = event.input.query;
      byId('judge-draft').textContent = event.input.draft;
      setStep('judge', 'running', 'Reviewing');
      startStepTiming('judge', elapsed);
      openStep('judge');
      setStatus('running', 'Draft sent to judge');
      break;
    case 'verdict':
      finishStepTiming(elapsed);
      setStep('judge', 'done', labels[event.decision]);
      steps.judge.dataset.decision = event.decision;
      byId('rationale').textContent = event.rationale;
      byId('guidance').textContent = event.guidance;
      byId('guidance-block').hidden = !event.guidance;
      byId('verdict-body').hidden = false;
      setStatus('running', 'Judge ruling · ' + labels[event.decision]);
      break;
    case 'revision_started': {
      const tweaking = event.decision === 'tweak';
      setStep('revision', 'running', tweaking ? 'Applying guidance' : 'Regenerating');
      byId('revision-note').textContent = tweaking ? byId('guidance').textContent
        : 'Writing a fresh answer from the original question.';
      startStepTiming('revision', elapsed);
      openStep('revision');
      setStatus('running', tweaking ? 'Revising the draft' : 'Writing a fresh answer');
      break;
    }
    case 'revision_delta':
      appendOutput(streamedAnswers.revision, event.text);
      break;
    case 'final_answer':
      finishTraceTiming(elapsed);
      setStep('revision', event.decision === 'accept' ? 'skipped' : 'done',
        event.decision === 'accept' ? 'Skipped' : 'Completed');
      if (event.decision === 'accept') byId('revision-note').textContent = 'The judge accepted the draft.';
      if (event.decision === 'regenerate') byId('revision-note').textContent = 'A fresh answer was written from the original question.';
      if (event.decision !== 'accept') renderOutput(streamedAnswers.revision, event.answer);
      showAnswer(event);
      break;
    case 'closed': {
      finishTraceTiming();
      for (const output of Object.values(streamedAnswers)) {
        if (output.renderTimer !== undefined) renderOutput(output);
      }
      const restoreFocus = document.activeElement === stopButton
        || (event.outcome === 'stopped' && document.activeElement === document.body);
      setRunning(false);
      if (restoreFocus) (runButton.disabled ? byId('edit-question') : runButton).focus({ preventScroll: true });
      const activeStep = stepNames.find((name) => steps[name].dataset.state === 'running');
      if (activeStep === 'draft' && reasoningText.hidden) {
        reasoningPlaceholder.textContent = 'The draft ended before any reasoning arrived.';
      }
      if (event.outcome === 'success') {
        setStatus('done', 'Answer ready');
      } else if (event.outcome === 'stopped') {
        setStatus('idle', 'Stopped');
        if (activeStep) setStep(activeStep, 'skipped', 'Stopped');
        markUnreachedSteps();
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

  const focused = document.activeElement;
  const moveFocus = form.contains(focused) || focused.closest('.step');
  resetTimeline();
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
    runRecovery.hidden = false;
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
