const { app, BrowserWindow, ipcMain, shell, Menu, dialog, safeStorage } = require('electron');
const {CredentialStore} = require('./credential_store');
function credentialStore(){return new CredentialStore(path.join(app.getPath('userData'),'automatic-sign-in.bin'),safeStorage);}
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');
const { parseCredentialLine, totp, pageAutomationScript } = require('./chatgpt_auto_login');

function chatGPTAuthLog(stage, details = {}) {
  try {
    const directory = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(directory, { recursive: true });
    const record = { time: new Date().toISOString(), stage };
    if (details.host && /^[a-z0-9.:-]+$/i.test(details.host)) record.host = details.host;
    if (details.urlShape) record.url = details.urlShape;
    if (details.pageStage && /^[a-z-]+$/i.test(details.pageStage)) record.pageStage = details.pageStage;
    if (details.status && /^[a-z-]+$/i.test(details.status)) record.status = details.status;
    if (Number.isInteger(details.errorCode)) record.errorCode = details.errorCode;
    if (details.diagnostics) {
      const safe = {};
      for (const key of ['email','password','otp','workspace','consent']) {
        if (typeof details.diagnostics[key] === 'boolean') safe[key] = details.diagnostics[key];
      }
      if (Number.isInteger(details.diagnostics.buttons)) safe.buttons = details.diagnostics.buttons;
      if (Array.isArray(details.diagnostics.buttonLabels)) safe.buttonLabels = details.diagnostics.buttonLabels.filter(label => typeof label === 'string').slice(0, 6);
      record.screen = safe;
    }
    fs.appendFileSync(path.join(directory, 'chatgpt-auto-login.log'), `${JSON.stringify(record)}\n`, 'utf8');
  } catch { /* Diagnostics must never interrupt sign-in. */ }
}

function authHostname(value) {
  try { return new URL(value).hostname.toLowerCase(); } catch { return ''; }
}
function authUrlShape(value) {
  try { const u = new URL(value); return {host:u.hostname.toLowerCase(), port:u.port, path:u.pathname}; } catch { return {}; }
}

// The browser callback is accepted before the gateway has finished exchanging
// the authorization code and writing the auth file.  A single status request
// at that point races the gateway and makes a successful sign-in look like a
// failure.  Keep the retry local to recovery so the UI never flashes a false
// "Sign in again" state while the provider is completing the exchange.
async function waitForLoginStatus(provider, state) {
  const waits = [0, 700, 1100, 1500, 2000, 2500, 3000, 3500];
  let lastError = '';
  for (let attempt = 0; attempt < waits.length; attempt++) {
    if (attempt) await new Promise(resolve => setTimeout(resolve, waits[attempt]));
    try {
      const status = await send('login_status', {provider, state});
      const value = String(status?.status || '').toLowerCase();
      chatGPTAuthLog('recovery-login-status', {status: value || 'unknown'});
      if (value === 'ok' || value === 'error') return status;
      lastError = value || 'pending';
    } catch (error) {
      lastError = String(error?.message || error || 'status-check-failed').slice(0, 120);
      chatGPTAuthLog('recovery-login-status-error');
    }
  }
  chatGPTAuthLog('recovery-login-status-timeout');
  return {status: 'error', error: lastError || 'The gateway did not finish the sign-in in time.'};
}

let windowRef;
const managerWindows = new Set();
let connectionsWindowRef;
const autoLoginWindows = new Map();
const recoveryAttempts = new Map();
let recoveryBusy=false;
async function repairExpiredAccounts(){
  if(recoveryBusy||quitting||autoLoginWindows.size)return;
  recoveryBusy=true;
  try{
    const snapshot=await send('snapshot');
    for(const account of snapshot?.accounts||[]){
      if(account.provider!=='openai'||account.disabled)continue;
      const needsRecovery = account.status === 'Sign in again' || account.severity === 'error' || /sign in|invalid|expired|auth/i.test(String(account.detail||''));
      if(!needsRecovery)continue;
      if(Date.now()-(recoveryAttempts.get(account.id)||0)<30*60*1000)continue;
      const identity=await send('account_identity',{id:account.id});
      const email=identity?.email||account.email;
      if(!email){chatGPTAuthLog('recovery-skipped',{reason:'missing-email'});continue;}
      const saved=credentialStore().get(email);
      if(!saved){chatGPTAuthLog('recovery-skipped',{reason:'credentials-not-saved'});continue;}
      recoveryAttempts.set(account.id,Date.now());
      const inventory=await send('account_inventory',{email});
      const target=inventory.find(row=>row.id===account.id);
      if(!target){chatGPTAuthLog('recovery-skipped',{reason:'workspace-record-not-found'});continue;}
      Object.assign(target,await send('recovery_target',{id:account.id}));
      const result=await beginChatGPTAutoLogin(null,`${saved.email} | ${saved.password} | ${saved.secret}`,target);
      await new Promise(resolve=>{const timer=setInterval(()=>{if(quitting||!autoLoginWindows.has(result.state)){clearInterval(timer);resolve();}},500);});
      const status=await waitForLoginStatus('openai',result.state);
      if(status?.status==='ok'){
        await send('refresh');
        let verification={verified:false};
        for(let attempt=0;attempt<3&&!verification.verified;attempt++){
          if(attempt) await new Promise(resolve=>setTimeout(resolve,1500));
          verification=await send('recovery_verify',{id:account.id});
        }
        chatGPTAuthLog(verification.verified?'recovery-verified':'recovery-not-verified');
      } else {
        chatGPTAuthLog('recovery-login-failed');
      }
      break;
    }
  }catch{chatGPTAuthLog('recovery-check-failed');}finally{recoveryBusy=false;}
}
const accountProviders = new Set(['gemini','openai','claude','grok','tokenharbor']);
function broadcast(channel, message) {
  for (const win of [windowRef, connectionsWindowRef, ...managerWindows]) if (win && !win.isDestroyed()) win.webContents.send(channel, message);
}
let bridge;
let quitting=false, bridgeRestarts=0, bridgeRetryTimer;
let requestId = 0;
const pending = new Map();
const selfTest = process.argv.includes('--self-test');
const demo = selfTest || process.argv.includes('--demo');
if (!demo && !app.requestSingleInstanceLock()) { app.quit(); } else {
app.on('second-instance',()=>{if(windowRef){if(windowRef.isMinimized())windowRef.restore();windowRef.show();windowRef.focus();}});
}
let windowSettings = {};
let saveWindowTimer;
function settingsPath(){return path.join(app.getPath('userData'),'window.json');}
function saveWindow(){if(!windowRef||windowRef.isDestroyed())return;try{const bounds=windowRef.getNormalBounds();fs.writeFileSync(settingsPath(),JSON.stringify({...bounds,width:280,pinned:windowRef.isAlwaysOnTop()}));}catch{}}
function scheduleSaveWindow(){clearTimeout(saveWindowTimer);saveWindowTimer=setTimeout(saveWindow,150);}

function sourceRoot() {
  if (process.env.OMNI_SOURCE_ROOT) return process.env.OMNI_SOURCE_ROOT;
  return path.resolve(__dirname, '..');
}

function startBridge() {
  const root = sourceRoot();
  const bundledExe = path.join(process.resourcesPath || '', process.platform === 'win32' ? 'Omni-Backend.exe' : 'Omni-Backend');
  let command;
  let args;
  if (app.isPackaged && fs.existsSync(bundledExe)) {
    command = bundledExe;
    args = [];
  } else {
    const script = path.join(root, 'native_bridge.py');
    command = process.platform === 'win32' ? 'python' : 'python3';
    args = [script];
  }
  bridge = spawn(command, args, { cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  bridge.stderr.setEncoding('utf8');
  bridge.stderr.on('data', chunk => broadcast('bridge-log', String(chunk)));
  let buffer = '';
  bridge.stdout.setEncoding('utf8');
  bridge.stdout.on('data', chunk => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      if (!line.trim()) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message.id !== undefined) {
        const resolve = pending.get(message.id); pending.delete(message.id);
        if (!resolve) continue;
        message.error ? resolve.reject(new Error(message.error)) : resolve.resolve(message.result);
      } else broadcast('bridge-event', message);
    }
  });
  const child = bridge;
  bridge.on('exit', () => {
    if(bridge!==child)return;
    bridge = null;
    broadcast('bridge-event',{event:'error',message:'Omni backend stopped. Restart Omni.'});
    for (const { reject, timer } of pending.values()){clearTimeout(timer);reject(new Error('Omni backend stopped.'));}
    pending.clear();
    if(!quitting&&bridgeRestarts<3){const delay=1000*2**bridgeRestarts++;bridgeRetryTimer=setTimeout(()=>{if(!quitting)startBridge();},delay);}
  });
  bridge.on('error', () => {
    bridge=null;
    for (const { reject,timer } of pending.values()){clearTimeout(timer);reject(new Error('Could not start Omni backend.'));}
    pending.clear();
  });
}

function send(action, fields = {}) {
  if(demo){if(action==='preferences')return Promise.resolve({private:true,theme:'dark',language:'en',visible:{}});return Promise.resolve({});}
  if (!bridge || bridge.killed || bridge.exitCode !== null || !bridge.stdin.writable) return Promise.reject(new Error('Omni backend is not running.'));
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Request timed out.'));},60000);
    pending.set(id, { resolve: value=>{clearTimeout(timer);resolve(value);}, reject: error=>{clearTimeout(timer);reject(error);},timer });
    bridge.stdin.write(JSON.stringify({ ...fields, action, request: id }) + '\n',error=>{if(error){clearTimeout(timer);pending.delete(id);reject(new Error('Omni backend disconnected.'));}});
  });
}

function createWindow() {
  try{windowSettings=JSON.parse(fs.readFileSync(settingsPath(),'utf8'));}catch{}
  const saved = windowSettings.height >= 600 && windowSettings.height <= 1600 ? windowSettings : {};
  const {pinned, width, ...savedBounds}=saved;
  windowRef = new BrowserWindow({ width: 280, height: 1040,...savedBounds, minWidth: 280, minHeight: 680,
    title: 'Omni', backgroundColor: '#10141d', show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: !selfTest } });
  windowRef.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  windowRef.setAlwaysOnTop(!!windowSettings.pinned);
  windowRef.once('ready-to-show', () => {if(!selfTest)windowRef.show();});
  windowRef.on('move',scheduleSaveWindow);
  windowRef.on('resize',scheduleSaveWindow);
  windowRef.on('close',saveWindow);
  windowRef.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  windowRef.webContents.on('will-navigate',event=>event.preventDefault());
  if(selfTest)windowRef.webContents.on('console-message',(_event,...args)=>{fs.appendFileSync(path.join(sourceRoot(),'build','electron-console.log'),JSON.stringify(args)+'\n');});
  windowRef.on('closed', () => { windowRef = null; });
}

function openAccountManager(provider, mode = '') {
  if (!accountProviders.has(provider)) throw new Error('Unsupported account provider');
  const win = new BrowserWindow({width:520,height:570,minWidth:440,minHeight:440,title:`Omni · ${provider}`,
    backgroundColor:'#10141d',show:false,autoHideMenuBar:true,
    webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,sandbox:true,nodeIntegration:false}});
  managerWindows.add(win);
  win.loadFile(path.join(__dirname,'renderer','manager.html'),{query:{provider, mode}});
  win.once('ready-to-show',()=>win.show());
  win.on('closed',()=>managerWindows.delete(win));
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',event=>event.preventDefault());
  return true;
}

function openArchiveWindow() {
  const win = new BrowserWindow({width: 920, height: 760, minWidth: 700, minHeight: 560,
    title: 'Omni · Account archive', backgroundColor: '#10141d', show: false, autoHideMenuBar: true,
    webPreferences: {preload: path.join(__dirname, 'preload.js'), contextIsolation: true,
      sandbox: true, nodeIntegration: false}});
  managerWindows.add(win);
  win.loadFile(path.join(__dirname, 'renderer', 'manager.html'), {query: {mode: 'archive'}});
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => managerWindows.delete(win));
  win.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  win.webContents.on('will-navigate', event => event.preventDefault());
  return true;
}

function openConnectionsWindow() {
  if (connectionsWindowRef && !connectionsWindowRef.isDestroyed()) {
    connectionsWindowRef.show(); connectionsWindowRef.focus(); return true;
  }
  connectionsWindowRef = new BrowserWindow({width:980,height:780,minWidth:720,minHeight:560,
    title:'Omni · Connections', backgroundColor:'#10141d',show:false,autoHideMenuBar:true,
    webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,sandbox:true,nodeIntegration:false}});
  connectionsWindowRef.loadFile(path.join(__dirname,'renderer','index.html'));
  connectionsWindowRef.once('ready-to-show',()=>connectionsWindowRef.show());
  connectionsWindowRef.webContents.once('did-finish-load',()=>connectionsWindowRef.webContents.executeJavaScript("document.body.classList.add('connections-window');document.getElementById('connections').click();").catch(()=>{}));
  connectionsWindowRef.on('closed',()=>{connectionsWindowRef=null;});
  connectionsWindowRef.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  connectionsWindowRef.webContents.on('will-navigate',event=>event.preventDefault());
  return true;
}

function trustedChatGPTAuthUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname) && ((url.port === '1455' && url.pathname.startsWith('/auth/callback')) || (url.port === '8318' && url.pathname.startsWith('/codex/callback')))) return true;
    return url.protocol === 'https:' && (url.hostname === 'openai.com' || url.hostname.endsWith('.openai.com') || url.hostname === 'chatgpt.com' || url.hostname.endsWith('.chatgpt.com') || url.hostname === 'login.microsoftonline.com' || url.hostname.endsWith('.login.microsoftonline.com') || url.hostname === 'login.live.com');
  } catch { return false; }
}

function closeAutoLogin(state, status, message) {
  const session = autoLoginWindows.get(state);
  if (!session) return;
  autoLoginWindows.delete(state);
  clearInterval(session.timer);
  clearTimeout(session.expiry);
  if (session.window && !session.window.isDestroyed()) session.window.destroy();
  if (status) broadcast('bridge-event', {event:'chatgpt-auto-login', state, status, message});
}

async function beginChatGPTAutoLogin(event, line, target = null) {
  chatGPTAuthLog('request-received');
  const credentials = parseCredentialLine(line);
  credentialStore().save(credentials);
  const owner = event?.sender ? BrowserWindow.fromWebContents(event.sender) : windowRef;
  const result = await send('login', {provider:'openai'});
  if (!result?.state || !trustedChatGPTAuthUrl(result.url)) {
    chatGPTAuthLog('provider-login-start-failed');
    throw new Error('Omni could not start a secure ChatGPT sign-in.');
  }
  chatGPTAuthLog('provider-login-started', { host: authHostname(result.url) });
  if(target){
    const url=new URL(result.url);
    url.searchParams.set('codex_cli_simplified_flow','false');
    if(target.accountId)url.searchParams.set('organization_id',target.accountId);
    result.url=url.href;
    chatGPTAuthLog('target-workspace-login-started');
  }
  const win = new BrowserWindow({
    width: 480, height: 640, show: false, parent: owner || undefined,
    webPreferences: { preload:path.join(__dirname,'auth_preload.js'),partition:`omni-chatgpt-auth-${randomUUID()}`, contextIsolation:true, sandbox:true, nodeIntegration:false, backgroundThrottling:false }
  });
  win.webContents.setUserAgent(`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${process.versions.chrome} Safari/537.36`);
  const session = {window:win, credentials, status:'starting', pageStage:'starting', startedAt:Date.now(), timer:null, expiry:null};
  autoLoginWindows.set(result.state, session);
  const fail = message => {
    chatGPTAuthLog('flow-failed', { host: authHostname(win.webContents.getURL()), pageStage: session.pageStage });
    closeAutoLogin(result.state, 'error', message);
  };
  const inspect = async () => {
    if (!autoLoginWindows.has(result.state) || win.isDestroyed() || session.inspectBusy) return;
    session.inspectBusy = true;
    try {
    const url = win.webContents.getURL();
    if (url && !trustedChatGPTAuthUrl(url)) { chatGPTAuthLog('untrusted-redirect', {urlShape: authUrlShape(url)}); fail('The provider redirected to an untrusted sign-in page.'); return; }
    try {
      if (url) { const callback = new URL(url); if ((callback.port === '1455' && callback.pathname.startsWith('/auth/callback')) || (callback.port === '8318' && callback.pathname.startsWith('/codex/callback'))) { chatGPTAuthLog('callback-reached', { host: authHostname(url) }); closeAutoLogin(result.state, 'callback', 'ChatGPT sign-in completed.'); return; } }
      if (!url) return;
      const host = authHostname(url);
      if (!['auth.openai.com','login.openai.com','login.microsoftonline.com','login.live.com','chatgpt.com','www.chatgpt.com'].includes(host)) {
        if (session.status !== `waiting:${host}`) { session.status = `waiting:${host}`; session.pageStage = 'unsupported-page'; chatGPTAuthLog('unsupported-auth-page', { host }); }
        return;
      }
      const code = totp(credentials.secret);
      if(session.mfaSubmitted){
        const shape=await win.webContents.executeJavaScript(`(()=>{const visible=n=>!!(n.offsetWidth||n.offsetHeight||n.getClientRects().length);const scrub=s=>String(s||'').replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+/gi,'[email]').replace(/\\b\\d{6}\\b/g,'[code]').slice(0,120);return {path:location.pathname,headings:[...document.querySelectorAll('h1,h2')].map(n=>scrub(n.textContent)),controls:[...document.querySelectorAll('button,select,[role="combobox"],[role="option"],input[type="radio"]')].filter(visible).map(n=>({tag:n.tagName,role:n.getAttribute('role'),type:n.getAttribute('type'),name:n.getAttribute('name'),value:n.value||'',label:scrub(n.textContent||n.parentElement?.textContent),html:scrub(n.outerHTML).slice(0,500),options:n.tagName==='SELECT'?[...n.options].map(o=>({text:scrub(o.textContent),value:o.value})):undefined}))}})()`);
        const key=JSON.stringify(shape);if(session.shapeKey!==key){session.shapeKey=key;fs.appendFileSync(path.join(app.getPath('userData'),'logs','workspace-structure.log'),key+'\n');}
      }
      const script = pageAutomationScript(credentials, code, session.mfaSubmitted, target?.area, target?.accountId);
      const outcome = await win.webContents.executeJavaScript(script, true);
      const diagnosticKey = JSON.stringify(outcome?.diagnostics);
      if (outcome?.diagnostics && session.diagnosticKey !== diagnosticKey) {
        session.diagnosticKey = diagnosticKey;
        chatGPTAuthLog('screen-detected', {host: authHostname(url), diagnostics: outcome.diagnostics});
      }
      if (outcome?.status === 'verification') { chatGPTAuthLog('verification-required', { host: authHostname(url) }); fail('ChatGPT requires a security check that Omni cannot complete automatically.'); return; }
      if (outcome?.status === 'target-workspace-unavailable') { fail('The required workspace was not found. Sign-in has not been restored.'); return; }
      if (outcome?.status === 'single-workspace-picker') { chatGPTAuthLog('single-workspace-picker', { host: authHostname(url) }); fail('ChatGPT only allows one workspace per sign-in on this page, so Omni did not choose one at random.'); return; }
      if (outcome?.status === 'rejected') { chatGPTAuthLog('provider-rejected-sign-in', { host: authHostname(url) }); fail('ChatGPT rejected the sign-in details. Check the saved values and try again.'); return; }
      if (outcome?.status === 'submitted-code') session.mfaSubmitted = true;
      const labels = {starting:'Signing in to ChatGPT…','submitted-email':'Email submitted; continuing sign-in…','submitted-password':'Password submitted; continuing sign-in…','submitted-code':'Two-factor code submitted…','selected-all-workspaces':'All available workspaces selected…','submitted-consent':'Confirming sign-in to Codex…','waiting-consent':'Waiting for sign-in confirmation…'};
      const next = labels[outcome?.status] || 'Signing in to ChatGPT…';
      if (session.status !== next) {
        session.status = next;
        session.pageStage = outcome?.status || 'waiting';
        chatGPTAuthLog('page-step', { host: authHostname(url), pageStage: outcome?.status || 'waiting' });
        broadcast('bridge-event', {event:'chatgpt-auto-login',state:result.state,status:'progress',message:next});
      }
    } catch { chatGPTAuthLog('page-navigation-during-step', { host: authHostname(url) }); /* Navigation may replace the document while an automation step is running. */ }
    } finally { session.inspectBusy = false; }
  };
  win.webContents.on('did-finish-load', inspect);
  win.webContents.on('did-navigate-in-page', inspect);
  win.webContents.on('did-fail-load', (_event, code, _description, url) => {
    if (code !== -3) { chatGPTAuthLog('page-load-failed', { host: authHostname(url), errorCode: code }); fail('The hidden ChatGPT sign-in page could not be loaded.'); }
  });
  win.webContents.setWindowOpenHandler(({url}) => {
    if (trustedChatGPTAuthUrl(url)) { win.loadURL(url).catch(()=>fail('The ChatGPT sign-in page could not be opened.')); }
    else fail('ChatGPT tried to open an unsupported sign-in page.');
    return {action:'deny'};
  });
  win.webContents.on('will-navigate', (navigationEvent, url) => { if (!trustedChatGPTAuthUrl(url)) { navigationEvent.preventDefault(); fail('The provider redirected to an untrusted sign-in page.'); } });
  session.timer = setInterval(inspect, 700);
  session.expiry = setTimeout(()=>fail('ChatGPT sign-in timed out.'), 15*60*1000);
  win.on('closed',()=>{if(autoLoginWindows.has(result.state))closeAutoLogin(result.state,'error','ChatGPT sign-in was interrupted.');});
  win.loadURL(result.url).catch(()=>{ chatGPTAuthLog('initial-page-load-failed', { host: authHostname(result.url) }); fail('The hidden ChatGPT sign-in page could not be loaded.'); });
  return {state:result.state, expires_at:result.expires_at, automatic:true};
}

function cancelChatGPTAutoLogin(state) { closeAutoLogin(state, null, null); return true; }

app.whenReady().then(() => { if(!demo&&!app.hasSingleInstanceLock())return; Menu.setApplicationMenu(null); if(!demo)startBridge(); createWindow(); if(demo)windowRef.webContents.once('did-finish-load',()=>runDemo()); });
app.on('before-quit',()=>{quitting=true;clearTimeout(bridgeRetryTimer);for(const state of [...autoLoginWindows.keys()])closeAutoLogin(state,null,null);});
app.on('window-all-closed', () => {quitting=true;clearTimeout(bridgeRetryTimer); clearTimeout(saveWindowTimer); if (bridge) {const child=bridge;bridge.stdin.end();if(process.platform==='win32')spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true});else child.kill();} if (process.platform !== 'darwin') app.quit(); });
ipcMain.handle('bridge-send', async (event, action, fields) => {
  if (['automatic_account_inventory', 'automatic_account_update', 'automatic_account_remove'].includes(action)) {
    const url = new URL(event.sender.getURL());
    if (path.basename(url.pathname) !== 'manager.html' || url.searchParams.get('mode') !== 'automatic') throw new Error('Open the automatic sign-in manager first.');
    const store = credentialStore();
    if (action === 'automatic_account_update') {
      store.update(fields.email, parseCredentialLine(fields.value));
      return {saved: true};
    }
    if (action === 'automatic_account_remove') {
      store.remove(fields.email);
      return {removed: true};
    }
    return store.inventory(await send('account_inventory', {}));
  }
  return send(action, fields);
});
ipcMain.handle('chatgpt-auto-login', beginChatGPTAutoLogin);
app.whenReady().then(()=>{if(!demo){const timer=setInterval(repairExpiredAccounts,60000);timer.unref();setTimeout(repairExpiredAccounts,15000);}});
ipcMain.handle('chatgpt-auto-login-cancel',(_,state)=>cancelChatGPTAutoLogin(state));
ipcMain.handle('open-account-manager',(_,provider,mode)=>openAccountManager(provider,mode));
ipcMain.handle('open-account-archive', () => openArchiveWindow());
ipcMain.handle('archive-export', async (event, fields = {}) => {
  const owner = BrowserWindow.fromWebContents(event.sender) || windowRef;
  const ids = Array.isArray(fields.ids) ? fields.ids.map(String).filter(Boolean) : [];
  const password = String(fields.password || '');
  if (!ids.length) throw new Error('Select at least one account to export.');
  if (password.length < 8) throw new Error('Archive password must contain at least 8 characters.');
  const result = await dialog.showSaveDialog(owner, {title: 'Export Omni account archive',
    defaultPath: 'omni-accounts.omni-archive', filters: [{name: 'Omni account archive', extensions: ['omni-archive']}]});
  if (result.canceled || !result.filePath) return {cancelled: true};
  const inventory = await send('archive_inventory');
  const selected = new Set(ids);
  const emails = new Set((inventory || []).filter(row => selected.has(row.id)).map(row => String(row.email || '').trim().toLowerCase()).filter(Boolean));
  let automaticCredentials = [];
  try {
    const store = credentialStore();
    automaticCredentials = Object.values(store.read()).filter(row => emails.has(String(row.email || '').trim().toLowerCase()));
  } catch { /* OAuth records remain portable even when no auto-login data is saved. */ }
  return send('archive_export', {path: result.filePath, ids, password, automatic_credentials: automaticCredentials});
});
ipcMain.handle('archive-import', async (event, fields = {}) => {
  const owner = BrowserWindow.fromWebContents(event.sender) || windowRef;
  const password = String(fields.password || '');
  if (password.length < 8) throw new Error('Archive password must contain at least 8 characters.');
  const result = await dialog.showOpenDialog(owner, {title: 'Import Omni account archive', properties: ['openFile'],
    filters: [{name: 'Omni account archive', extensions: ['omni-archive']}]});
  if (result.canceled || !result.filePaths[0]) return {cancelled: true};
  const imported = await send('archive_import', {path: result.filePaths[0], password});
  const automaticCredentials = Array.isArray(imported?.automatic_credentials) ? imported.automatic_credentials : [];
  try {
    const store = credentialStore();
    for (const credentials of automaticCredentials) store.save(credentials);
  } catch { /* Import still succeeds for OAuth records if local secure storage is unavailable. */ }
  if (imported && typeof imported === 'object') delete imported.automatic_credentials;
  await send('refresh');
  return imported;
});
ipcMain.handle('open-connections-window',()=>openConnectionsWindow());
ipcMain.handle('open-external', (_, url) => {const target=new URL(url);if(target.protocol!=='https:'||!['github.com','accounts.google.com','auth.openai.com','claude.ai','grok.com','x.ai','accounts.x.ai','auth.x.ai'].includes(target.hostname))throw new Error('Unsupported link');return shell.openExternal(target.href);});
ipcMain.handle('window-pin',()=>{windowRef.setAlwaysOnTop(!windowRef.isAlwaysOnTop());saveWindow();return windowRef.isAlwaysOnTop();});
ipcMain.handle('window-panel',(event,expanded)=>{const target=BrowserWindow.fromWebContents(event.sender)||windowRef;const [x,y]=target.getPosition();const [,height]=target.getSize();if(target===windowRef)target.setBounds({x,y,width:expanded?1120:280,height});return expanded;});
ipcMain.handle('import-auth',async(event)=>{const owner=BrowserWindow.fromWebContents(event.sender)||windowRef;const result=await dialog.showOpenDialog(owner,{title:'Import ChatGPT auth.json',properties:['openFile'],filters:[{name:'JSON',extensions:['json']}]});if(result.canceled)return {cancelled:true};return send('import',{path:result.filePaths[0]});});
ipcMain.handle('pick-key-file',async(event)=>{const owner=BrowserWindow.fromWebContents(event.sender)||windowRef;const result=await dialog.showOpenDialog(owner,{title:'Select Private Key File',properties:['openFile','showHiddenFiles'],filters:[{name:'All Files',extensions:['*']},{name:'SSH Private Keys',extensions:['pem','key','id_rsa','id_ed25519','id_ecdsa']}]});if(result.canceled||!result.filePaths[0])return null;return result.filePaths[0];});
ipcMain.handle('clipboard-copy',(_,text)=>require('electron').clipboard.writeText(String(text)));
ipcMain.handle('clipboard-paste',()=>require('electron').clipboard.readText());

async function runDemo(){
  const account={id:'demo-openai',label:'OpenAI 1',provider:'openai',plan:'Plus',status:'Available',severity:'normal',priority:2,active:true,windows:[{id:'openai/5h',label:'5h',remaining:75,reset:Date.now()/1000+3600,floor:0},{id:'openai/weekly',label:'1w',remaining:50,reset:Date.now()/1000+86400,floor:25}]};
  for(let i=0;i<30;i++)windowRef.webContents.send('bridge-event',{event:'account',account:{...account,id:'demo-'+i,label:'OpenAI '+(i+1),active:i===0}});
  if(!selfTest)return;
  try{
    const report=await windowRef.webContents.executeJavaScript(`(async()=>{
      const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await frame();
      const first=document.querySelector('.account'),button=first.querySelector('[data-action="pause"]'),fill=first.querySelector('.fill');
      const before=window.scrollY;const start=performance.now();
      for(let i=0;i<100;i++){const a=state.accounts.get('demo-0');state.accounts.set('demo-0',{...a,windows:a.windows.map(w=>({...w,remaining:31+i%60}))});render();}
      const stable=first===document.querySelector('.account')&&button===first.querySelector('[data-action="pause"]');
      const time=performance.now()-start;
      document.getElementById('settings').click();const opened=!document.getElementById('settings-view').hidden;document.getElementById('settings').click();const closed=document.getElementById('settings-view').hidden;
      state.visible.openai=false;render();const visibility=!document.querySelector('[data-toggle="openai"]');state.visible.openai=true;render();
      state.summaryCollapsed.openai=false;renderSummary();await frame();layoutForecasts();
      const forecasts=[...document.querySelectorAll('.forecast-row')].every(row=>{let end=-1;return [...row.children].filter(n=>n.style.visibility!=='hidden').every(n=>{const r=n.getBoundingClientRect(),bounds=row.getBoundingClientRect();const ok=r.left>=bounds.left&&r.right<=bounds.right+1&&r.left>=end;end=r.right;return ok;});});
      state.accounts.set('demo-harbor',{...state.accounts.get('demo-0'),id:'demo-harbor',provider:'tokenharbor',label:'TokenHarbor 1',windows:[]});render();
      const harborToggle=document.querySelector('[data-summary="tokenharbor"]');harborToggle.click();await frame();
      const harborBody=document.querySelector('[data-key="tokenharbor"] .summary-body');
      const harborList=!harborBody.hidden&&!!harborBody.querySelector('.account[data-id="demo-harbor"] [data-action="pause"]');
      harborToggle.click();const harborCollapse=harborBody.hidden;
      const settingsIcon=!!document.querySelector('#settings svg circle')&&!document.getElementById('menu');
      state.accounts.set('demo-free',{...state.accounts.get('demo-0'),id:'demo-free',plan:'free',windows:[{id:'openai/monthly',label:'1mo',remaining:42,reset:Date.now()/1000+86400}]});state.collapsed['openai-free']=true;render();
      const freeDots=document.querySelector('[data-toggle="openai-free"] .dots');const freeMonthly=freeDots.children.length===1&&freeDots.textContent==='1mo'&&freeDots.firstElementChild.style.getPropertyValue('--quota')==='42%';
      const resetPalette=resetColor(1000+18000,'5h',1000)==='#ff4455'&&resetColor(1000+9000,'5h',1000)==='#f5c56b'&&resetColor(1000+604800,'1w',1000)==='#ff4455';
      const providerColors=['gemini','openai','claude','grok','tokenharbor'].every(provider=>[5,20,75].every(remaining=>{const card=document.createElement('article');updateCard(card,{...state.accounts.get('demo-0'),provider,windows:[{id:'test',label:'5h',remaining,reset:1000+18000,floor:0}]});return card.querySelector('.quota').style.getPropertyValue('--quota-color')===quotaColor(remaining)&&card.querySelector('.countdown').style.color!=='';}));
      return {freeMonthly,harborList,harborCollapse,settingsIcon,providerColors,stable,cardStable:first===document.querySelector('.account'),buttonStable:button===first.querySelector('[data-action="pause"]'),fillStable:fill===first.querySelector('.fill'),forecasts,resetPalette,updates100ms:time,settingsToggle:opened&&closed,visibility,cards:document.querySelectorAll('.account').length,scrollable:document.getElementById('groups').scrollHeight>document.getElementById('groups').clientHeight,scrollUnchanged:before===window.scrollY};
    })()`);
    const output=path.resolve(sourceRoot(),'build');fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'electron-self-test.json'),JSON.stringify(report,null,2));
    const image=await windowRef.webContents.capturePage();fs.writeFileSync(path.join(output,'electron-preview.png'),image.toPNG());
    windowRef.setSize(1120,900);
    await windowRef.webContents.executeJavaScript("document.getElementById('settings-view').hidden=false;settings();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");
    fs.writeFileSync(path.join(output,'electron-settings-preview.png'),(await windowRef.webContents.capturePage()).toPNG());
    app.exit(Object.entries(report).every(([key,value])=>key==='updates100ms'||key==='cards'||value===true)?0:1);
  }catch(error){fs.writeFileSync(path.resolve(sourceRoot(),'build','electron-self-test.json'),JSON.stringify({error:String(error)}));app.exit(1);}
}
