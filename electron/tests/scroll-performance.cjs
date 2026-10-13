const {app,BrowserWindow,ipcMain,contentTracing}=require('electron');
const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../..');
app.setPath('userData',path.join(root,'build','scroll-test-profile'));
ipcMain.handle('bridge-send',()=>null);
ipcMain.handle('window-panel',()=>true);
app.whenReady().then(async()=>{
 const win=new BrowserWindow({width:280,height:1000,show:false,webPreferences:{preload:path.join(root,'electron/preload.js'),contextIsolation:true,sandbox:true,backgroundThrottling:false}});
 try{
 await win.loadFile(path.join(root,'electron/renderer/index.html'));
 await win.webContents.executeJavaScript(`for(let i=0;i<48;i++)state.accounts.set('perf-'+i,{id:'perf-'+i,label:'Account '+i,provider:'openai',plan:'Plus',status:'Available',severity:'normal',active:i<4,windows:[{id:'5h',label:'5h',remaining:80,reset:Date.now()/1000+3600,floor:0}]});render();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));`);
 win.showInactive();
 await contentTracing.startRecording({included_categories:['devtools.timeline','blink.user_timing']});
 const metrics=await win.webContents.executeJavaScript(`(async()=>{
  const frames=[],scroller=document.getElementById('groups'),first=document.querySelector('.account');let mutations=0;const observer=new MutationObserver(rows=>mutations+=rows.length);observer.observe(scroller,{subtree:true,attributes:true,childList:true,characterData:true});
  let previous=performance.now(),started=previous,lastResponse=0;for(let i=0;performance.now()-started<18000;i++){await new Promise(requestAnimationFrame);const now=performance.now();frames.push(now-previous);previous=now;scroller.scrollTop=(i%100)*(scroller.scrollHeight-scroller.clientHeight)/100;if(i%3===0){lastResponse=i;const a=state.accounts.get('perf-0');state.accounts.set(a.id,{...a,responses:i});queueRender();}}
  observer.disconnect();await new Promise(r=>setTimeout(r,250));const sorted=[...frames].sort((a,b)=>a-b);return {frames:frames.length,p95ms:sorted[Math.floor(sorted.length*.95)],maxMs:Math.max(...frames),slowFrames:frames.filter(x=>x>34).length,mutations,stable:first===document.querySelector('.account'),finalResponse:document.querySelector('.account .status').textContent.includes(lastResponse+' resp.'),animations:document.getAnimations().length};})()`);
 const label=process.env.OMNI_PERF_LABEL||'after';const tracePath=path.join(root,'build','scroll-'+label+'.trace.json');await contentTracing.stopRecording(tracePath);
 const trace=JSON.parse(fs.readFileSync(tracePath));const events=trace.traceEvents.filter(e=>e.name==='Paint'&&e.ph==='X');metrics.paintCount=events.length;metrics.paintMs=events.reduce((s,e)=>s+(e.dur||0),0)/1000;metrics.gpu=app.getGPUFeatureStatus();
 fs.writeFileSync(path.join(root,'build','scroll-'+label+'.json'),JSON.stringify(metrics,null,2));app.exit(metrics.stable&&metrics.finalResponse&&metrics.mutations===0&&metrics.animations===0?0:1);
 }catch(e){fs.writeFileSync(path.join(root,'build','scroll-error.txt'),String(e.stack));app.exit(1);}
});
