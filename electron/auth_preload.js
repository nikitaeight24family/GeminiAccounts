const {contextBridge} = require('electron');
// This flow has a password and TOTP. Decline optional passkey requests rather
// than opening a Windows credential dialog in a hidden sign-in window.
contextBridge.executeInMainWorld({func: () => {
  const original = navigator.credentials?.get?.bind(navigator.credentials);
  if (!original) return;
  Object.defineProperty(navigator.credentials, 'get', {configurable:true, value: options => {
    if (options?.publicKey) return Promise.reject(new DOMException('Use password sign-in.', 'NotAllowedError'));
    return original(options);
  }});
}});
