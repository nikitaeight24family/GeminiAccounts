const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omni', {
  version: '1.6.5',
  send: (action, fields) => ipcRenderer.invoke('bridge-send', action, fields || {}),
  chatgptAutoLogin: credentials => ipcRenderer.invoke('chatgpt-auto-login', credentials),
  chatgptAutoLoginCancel: state => ipcRenderer.invoke('chatgpt-auto-login-cancel', state),
  accountManager: (provider, mode) => ipcRenderer.invoke('open-account-manager', provider, mode),
  archiveWindow: () => ipcRenderer.invoke('open-account-archive'),
  archiveExport: fields => ipcRenderer.invoke('archive-export', fields || {}),
  archiveImport: password => ipcRenderer.invoke('archive-import', {password}),
  connectionsWindow: () => ipcRenderer.invoke('open-connections-window'),
  open: url => ipcRenderer.invoke('open-external', url),
  pin: () => ipcRenderer.invoke('window-pin'),
  panel: expanded => ipcRenderer.invoke('window-panel', expanded),
  copy: text => ipcRenderer.invoke('clipboard-copy', text),
  importAuth: () => ipcRenderer.invoke('import-auth'),
  pickKeyFile: () => ipcRenderer.invoke('pick-key-file'),
  paste: () => ipcRenderer.invoke('clipboard-paste'),
  onEvent: handler => ipcRenderer.on('bridge-event', (_, event) => handler(event))
});
