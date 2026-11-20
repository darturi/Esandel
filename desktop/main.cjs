const { app, BrowserWindow, clipboard, ipcMain, nativeTheme } = require('electron');
const { execFile, spawn } = require('node:child_process');
const { existsSync } = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const page = path.join(__dirname, 'index.html');
const pageUrl = pathToFileURL(page).href;
const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.ESANDEL_PYTHON || (existsSync(venvPython) ? venvPython : 'python3');
let activeRun;

function checkSender(event) {
  if (event.senderFrame !== event.sender.mainFrame || event.senderFrame?.url !== pageUrl) {
    throw new Error('Invalid run request.');
  }
}

ipcMain.handle('esandel:config', async (event) => {
  checkSender(event);
  return new Promise((resolve, reject) => {
    execFile(python, ['-X', 'utf8', '-m', 'esandel.cli', '--check-config'],
      { cwd: root, timeout: 10000, maxBuffer: 16384 }, (error, stdout) => {
        if (error) {
          reject(new Error('Esandel could not check local setup.'));
          return;
        }
        try {
          resolve(JSON.parse(stdout));
        } catch {
          reject(new Error('Esandel returned invalid setup information.'));
        }
      });
  });
});

ipcMain.handle('esandel:copy', (event, text) => {
  checkSender(event);
  if (typeof text !== 'string') throw new Error('There is no text to copy.');
  clipboard.writeText(text);
});

ipcMain.handle('esandel:start', (event, options) => {
  checkSender(event);
  if (activeRun) throw new Error('A run is already active.');
  const { query, draftModel = null, draftMaxTokens = null } = options ?? {};
  if (typeof query !== 'string' || !query.trim()) {
    throw new Error('Enter a question to run.');
  }
  if (draftModel !== null && (typeof draftModel !== 'string' || !draftModel.trim() || draftModel.includes('\0'))) {
    throw new Error('Enter a valid draft model ID.');
  }

  const args = ['-X', 'utf8', '-m', 'esandel.cli', '--events', '--live-draft', '--live-judge'];
  if (draftMaxTokens !== null) {
    if (!Number.isSafeInteger(draftMaxTokens) || draftMaxTokens < 1) {
      throw new Error('Enter a positive whole number for the draft token limit.');
    }
    args.push('--draft-max-tokens', String(draftMaxTokens));
  }

  const env = draftModel === null ? process.env : { ...process.env, ESANDEL_DRAFT_MODEL: draftModel.trim() };
  const child = spawn(python, args, { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'] });
  const run = { child, stopped: false };
  activeRun = run;
  let errorMessage;
  let draftLimitReached = false;
  let gotAnswer = false;

  const send = (message) => {
    if (!event.sender.isDestroyed()) event.sender.send('esandel:event', message);
  };

  readline.createInterface({ input: child.stdout }).on('line', (line) => {
    if (run.stopped) return;
    try {
      const message = JSON.parse(line);
      if (!message || typeof message.type !== 'string') throw new Error('Invalid event');
      if (message.type === 'draft_limit') {
        draftLimitReached = true;
        return;
      }
      if (message.type === 'final_answer') gotAnswer = true;
      send(message);
    } catch {
      errorMessage = 'Esandel returned an invalid workflow event.';
      child.kill();
    }
  });
  readline.createInterface({ input: child.stderr }).on('line', (line) => {
    if (line.startsWith('esandel: ')) {
      errorMessage = line.slice('esandel: '.length).replace(/^error: /, '');
    } else if (line.includes("No module named 'esandel'") || line.includes('No module named esandel')) {
      errorMessage = 'Install Esandel in the project’s Python environment and try again.';
    }
  });
  child.on('error', (error) => {
    errorMessage = error.code === 'ENOENT'
      ? 'Python could not be found. Set up Esandel’s Python environment and try again.'
      : 'Esandel’s Python process could not be started.';
  });
  child.stdin.on('error', (error) => {
    if (!run.stopped && error.code !== 'EPIPE') errorMessage = 'Esandel could not read the question.';
  });
  child.on('close', (code) => {
    activeRun = undefined;
    if (run.stopped) send({ type: 'closed', outcome: 'stopped' });
    else if (code === 0 && gotAnswer && !errorMessage) send({ type: 'closed', outcome: 'success' });
    else send({ type: 'closed', outcome: 'error', draftLimitReached,
      message: errorMessage || 'Esandel exited before the run completed.' });
  });
  child.stdin.end(query, 'utf8');
});

function stopRun() {
  if (!activeRun) return;
  activeRun.stopped = true;
  activeRun.child.kill();
}

ipcMain.handle('esandel:stop', (event) => {
  checkSender(event);
  stopRun();
});

function createWindow() {
  nativeTheme.themeSource = 'light';
  const window = new BrowserWindow({
    title: 'Esandel',
    width: 1180,
    height: 880,
    minWidth: 650,
    minHeight: 520,
    backgroundColor: '#f3f5f9',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.on('closed', stopRun);
  window.loadFile(page);
}

app.whenReady().then(createWindow);
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
