const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('esandel', {
  start: (options) => ipcRenderer.invoke('esandel:start', options),
  stop: () => ipcRenderer.invoke('esandel:stop'),
  config: () => ipcRenderer.invoke('esandel:config'),
  copy: (text) => ipcRenderer.invoke('esandel:copy', text),
  onEvent: (receive) => {
    ipcRenderer.on('esandel:event', (_event, message) => receive(message));
  },
});
