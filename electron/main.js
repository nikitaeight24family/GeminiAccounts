const { app, BrowserWindow, ipcMain, shell, Menu, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let windowRef;
const managerWindows = new Set();
const accountProviders = new Set(['gemini','openai','claude','grok','tokenharbor']);
function broadcast(channel, message) {
  for (const win of [windowRef, ...managerWindows]) if (win && !win.isDestroyed()) win.webContents.send(channel, message);
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

function openAccountManager(provider) {
  if (!accountProviders.has(provider)) throw new Error('Unsupported account provider');
  const win = new BrowserWindow({width:520,height:570,minWidth:440,minHeight:440,title:`Omni · ${provider}`,
    backgroundColor:'#10141d',show:false,autoHideMenuBar:true,
    webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,sandbox:true,nodeIntegration:false}});
  managerWindows.add(win);
  win.loadFile(path.join(__dirname,'renderer','manager.html'),{query:{provider}});
  win.once('ready-to-show',()=>win.show());
  win.on('closed',()=>managerWindows.delete(win));
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',event=>event.preventDefault());
  return true;
}

app.whenReady().then(() => { if(!demo&&!app.hasSingleInstanceLock())return; Menu.setApplicationMenu(null); if(!demo)startBridge(); createWindow(); if(demo)windowRef.webContents.once('did-finish-load',()=>runDemo()); });
app.on('before-quit',()=>{quitting=true;clearTimeout(bridgeRetryTimer);});
app.on('window-all-closed', () => {quitting=true;clearTimeout(bridgeRetryTimer); clearTimeout(saveWindowTimer); if (bridge) {const child=bridge;bridge.stdin.end();if(process.platform==='win32')spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true});else child.kill();} if (process.platform !== 'darwin') app.quit(); });
ipcMain.handle('bridge-send', (_, action, fields) => send(action, fields));
ipcMain.handle('open-account-manager',(_,provider)=>openAccountManager(provider));
ipcMain.handle('open-external', (_, url) => {const target=new URL(url);if(target.protocol!=='https:'||!['github.com','accounts.google.com','auth.openai.com','claude.ai','grok.com','x.ai','accounts.x.ai','auth.x.ai'].includes(target.hostname))throw new Error('Unsupported link');return shell.openExternal(target.href);});
ipcMain.handle('window-pin',()=>{windowRef.setAlwaysOnTop(!windowRef.isAlwaysOnTop());saveWindow();return windowRef.isAlwaysOnTop();});
ipcMain.handle('window-panel',(_,expanded)=>{const [x,y]=windowRef.getPosition();const [,height]=windowRef.getSize();windowRef.setBounds({x,y,width:expanded?1120:280,height});return expanded;});
ipcMain.handle('import-auth',async(event)=>{const owner=BrowserWindow.fromWebContents(event.sender)||windowRef;const result=await dialog.showOpenDialog(owner,{title:'Import ChatGPT auth.json',properties:['openFile'],filters:[{name:'JSON',extensions:['json']}]});if(result.canceled)return {cancelled:true};return send('import',{path:result.filePaths[0]});});
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
