const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omni', {
  send: (action, fields) => ipcRenderer.invoke('bridge-send', action, fields || {}),
  accountManager: provider => ipcRenderer.invoke('open-account-manager', provider),
  open: url => ipcRenderer.invoke('open-external', url),
  pin: () => ipcRenderer.invoke('window-pin'),
  panel: expanded => ipcRenderer.invoke('window-panel', expanded),
  copy: text => ipcRenderer.invoke('clipboard-copy', text),
  importAuth: () => ipcRenderer.invoke('import-auth'),
  paste: () => ipcRenderer.invoke('clipboard-paste'),
  onEvent: handler => ipcRenderer.on('bridge-event', (_, event) => handler(event))
});
