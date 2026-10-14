const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {webcrypto}=require('node:crypto');
const {JSDOM}=require('jsdom');
const {parseCredentialLine,totp,pageAutomationScript}=require('../chatgpt_auto_login');
const {CredentialStore}=require('../credential_store');
test('automatic inventory only includes saved automatic sign-in identities and all their areas',()=>{
 const store=new CredentialStore('',{});
 store.read=()=>({'auto@example.com':{email:'auto@example.com',password:'private',secret:'private'}});
 const rows=[{id:'free',email:'AUTO@example.com'},{id:'edu',email:'auto@example.com'},{id:'manual',email:'manual@example.com'}];
 assert.deepEqual(store.filterInventory(rows),rows.slice(0,2));
 store.read=()=>({});assert.deepEqual(store.filterInventory(rows),[]);
});
function setup(snapshot,loginStatus){
 const dom=new JSDOM(fs.readFileSync(path.join(__dirname,'../renderer/index.html'),'utf8'),{url:'https://omni.test',runScripts:'outside-only',pretendToBeVisual:true});
 const calls=[];const w=dom.window;const listeners=[];
 w.dispatchBridge=e=>listeners.forEach(callback=>callback(e));
 w.omni={send:async(action,fields)=>{calls.push({action,fields});if(action==='snapshot')return snapshot??null;if(action==='login_pending')return [{state:'pending',url:'https://auth.openai.com',created_at:1}];if(action==='login')return {state:'test',url:'https://claude.ai',user_code:fields.provider==='grok'?'1234':undefined};if(action==='login_status')return loginStatus??{status:'wait'};return {};},onEvent(callback){listeners.push(callback);},panel:async()=>{},pin:async()=>{},copy:async()=>{},paste:async()=>'',open:async()=>{},accountManager:async provider=>{calls.push({action:'accountManager',provider});},importAuth:async()=>({cancelled:true})};
 w.eval(fs.readFileSync(path.join(__dirname,'../renderer/renderer.js'),'utf8'));
 return {dom,w,calls};
}
test('startup displays saved accounts and applies live changes arriving during hydration',async()=>{
 let resolveSnapshot;
 const pending=new Promise(resolve=>{resolveSnapshot=resolve;});
 const {dom,w}=setup(pending);
 try{
  const cached={id:'one',provider:'openai',label:'One',status:'Available',windows:[{id:'5h',label:'5h',remaining:80}]};
  w.dispatchBridge({event:'account',account:{...cached,windows:[{...cached.windows[0],remaining:72}]}});
  resolveSnapshot({preferences:{},accounts:[cached],inventoryComplete:false});
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(w.state.accounts.get('one').windows[0].remaining,80,'Keep cached quota until inventory is complete');
  w.dispatchBridge({event:'accounts',ids:['one']});
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(w.state.accounts.get('one').windows[0].remaining,72);
  assert.match(w.document.querySelector('.account')?.textContent||'',/72%/);
 }finally{dom.window.close();}
});
test('adding an account opens a separate window and keeps the sidebar narrow',async()=>{
 const {dom,w,calls}=setup();try{
  w.state.accounts.set('one',{id:'one',provider:'openai',label:'One',status:'Available',windows:[]});w.render();
  const add=w.document.querySelector('[data-add="openai"]');assert.ok(add);add.click();await new Promise(r=>setImmediate(r));
  assert.ok(calls.some(x=>x.action==='accountManager'&&x.provider==='openai'));
  assert.equal(w.document.getElementById('settings-view').hidden,true);
 }finally{dom.window.close();}
});
function setupManager(provider,loginStatus,reviewResult,mode=''){
 const html=fs.readFileSync(path.join(__dirname,'../renderer/manager.html'),'utf8');
 const dom=new JSDOM(html,{url:`https://omni.test/manager.html?provider=${provider}&mode=${mode}`,runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,calls=[],listeners=[];Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle});w.Date.now=()=>59000;
 w.omni={send:async(action,fields)=>{calls.push({action,fields});if(action==='preferences')return {language:'en'};if(action==='login_pending')return [{state:'pending',url:'https://auth.openai.com',created_at:Date.now()/1000}];if(action==='login')return {state:'test',url:'https://auth.openai.com',expires_at:Date.now()/1000+600};if(action==='login_status')return loginStatus??{status:'wait'};if(action==='login_review')return reviewResult??{status:'checking'};return {};},chatgptAutoLogin:async line=>{calls.push({action:'chatgpt-auto-login',line});return {state:'auto-test',automatic:true,expires_at:Date.now()/1000+600};},chatgptAutoLoginCancel:async state=>{calls.push({action:'chatgpt-auto-login-cancel',state});},onEvent:fn=>listeners.push(fn),copy:async()=>{calls.push({action:'copy'});},open:async()=>{calls.push({action:'open'});},paste:async()=>'',importAuth:async()=>({cancelled:true})};
 w.eval(fs.readFileSync(path.join(__dirname,'../renderer/manager.js'),'utf8'));
 return {dom,w,calls,listeners};
}
test('ChatGPT automatic sign-in sends the input directly to its hidden flow without opening a browser',async()=>{
 const {dom,w,calls}=setupManager('openai',null,null,'automatic');try{
  await new Promise(r=>setTimeout(r,10));
  const field=w.document.querySelector('#credential-line');field.value='person@example.com | private-test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
  w.document.querySelector('#automatic-login .submit').click();await new Promise(r=>setTimeout(r,20));
  assert.equal(w.document.querySelector('#credential-line').value,'');
  assert.equal(calls.some(call=>call.action==='chatgpt-auto-login'&&call.line.includes('private-test-password')),true);
  assert.equal(calls.some(call=>call.action==='open'||call.action==='copy'),false);
  assert.equal(calls.some(call=>call.action==='login'),false);
  assert.equal(w.document.querySelector('#session #callback'),null);
  assert.equal(w.document.querySelector('#session .actions'),null);
 }finally{dom.window.close();}
});
test('ChatGPT automatic sign-in accepts bulk records pasted or loaded from text',async()=>{
 const {dom,w,calls,listeners}=setupManager('openai',null,null,'automatic');try{
  await new Promise(r=>setTimeout(r,10));
  const field=w.document.querySelector('#credential-line');field.value='first@example.com | pass-one | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ\nsecond@example.com; pass-two; GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
  w.document.querySelector('#automatic-login .submit').click();await new Promise(r=>setTimeout(r,20));
  assert.equal(calls.filter(call=>call.action==='chatgpt-auto-login').length,1);
  listeners.forEach(fn=>fn({event:'chatgpt-auto-login',state:'auto-test',status:'callback'}));await new Promise(r=>setTimeout(r,20));
  const lines=calls.filter(call=>call.action==='chatgpt-auto-login').map(call=>call.line);
  assert.equal(lines.length,2);assert.match(lines[0],/first@example\.com/);assert.match(lines[1],/second@example\.com/);
  assert.equal(w.document.querySelector('#credential-line').value,'');
 }finally{dom.window.close();}
});
test('automatic window has a multi-file drop zone and no file picker',async()=>{
 const {dom,w}=setupManager('openai',null,null,'automatic');try{
  await new Promise(r=>setTimeout(r,10));
  assert.equal(w.document.querySelector('#methods').hidden,true);
  const drop=w.document.querySelector('.file-drop');assert.ok(drop);
  assert.equal(w.document.querySelector('#credential-file').hidden,true);
  const event=new w.Event('drop',{bubbles:true,cancelable:true});
  Object.defineProperty(event,'dataTransfer',{value:{files:[{name:'one.txt',text:async()=> 'first@example.com | password | SECRET'},{name:'two.txt',text:async()=> 'second@example.com | password | SECRET'}]}});
  drop.dispatchEvent(event);await new Promise(r=>setTimeout(r,10));
  assert.match(w.document.querySelector('textarea').value,/first@example.com[\s\S]*\nsecond@example.com/);
 }finally{dom.window.close();}
});
test('ChatGPT credentials validate and TOTP matches the RFC 6238 SHA-1 vector',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 assert.equal(credentials.email,'person@example.com');assert.equal(credentials.password,'test-password');assert.equal(totp(credentials.secret,59000),'287082');
 assert.throws(()=>parseCredentialLine('person@example.com | test-password | not-base32'));
});
test('pin highlight cannot draw an account border over the window',async()=>{
 const {dom,w}=setup();try{
  w.omni.pin=async()=>true;
  w.document.querySelector('#pin').click();await new Promise(r=>setImmediate(r));
  assert.equal(w.document.querySelector('#pin').classList.contains('active'),true);
  const css=fs.readFileSync(path.join(__dirname,'../renderer/styles.css'),'utf8');
  assert.doesNotMatch(css,/(?:^|\})\.active:before\{/);
  assert.match(css,/\.account\.active:before\{/);
 }finally{dom.window.close();}
});
test('password submission ignores the passkey button before Continue',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<form><input type="password"><button type="submit">Use a passkey</button><button type="submit">Продолжить</button></form>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{
  for(const node of dom.window.document.querySelectorAll('input,button'))Object.defineProperty(node,'offsetWidth',{value:120});
  let passkey=0,continued=0;const buttons=dom.window.document.querySelectorAll('button');
  buttons[0].onclick=()=>passkey++;buttons[1].onclick=()=>continued++;
  dom.window.document.querySelector('form').onsubmit=e=>e.preventDefault();
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456')).status,'submitted-password');
  assert.equal(passkey,0);assert.equal(continued,1);
 }finally{dom.window.close();}
});
test('recovery selects Personal Free instead of K12 when both workspaces exist',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<h1>Choose workspace</h1><label><input type="radio" name="w">K12</label><label><input type="radio" name="w">Personal workspace</label><button>Continue</button>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{
  for(const node of dom.window.document.querySelectorAll('label,input,button'))Object.defineProperty(node,'offsetWidth',{value:120});
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456',true,'free')).status,'selected-target-workspace');
  assert.deepEqual([...dom.window.document.querySelectorAll('input')].map(node=>node.checked),[false,true]);
 }finally{dom.window.close();}
});
test('workspace radio page is detected without chooser text',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<label>EDU<input type="radio" name="workspace_id" value="edu"></label><label>RLRЛичная учетная запись<input type="radio" name="workspace_id" value="free"></label><button>Продолжить</button>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{for(const node of dom.window.document.querySelectorAll('label,input,button'))Object.defineProperty(node,'offsetWidth',{value:120});assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456',true,'free','free')).status,'selected-target-workspace');assert.deepEqual([...dom.window.document.querySelectorAll('input')].map(n=>n.checked),[false,true]);}finally{dom.window.close();}
});
test('hidden sign-in script submits only supported auth fields on the provider login origin',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<form><input type="email"><button type="submit">Continue</button></form>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{let submitted=0;Object.defineProperty(dom.window.document.querySelector('input'),'offsetWidth',{value:160});dom.window.document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();submitted++;});
  const result=dom.window.eval(pageAutomationScript(credentials,'123456'));
  assert.equal(result.status,'submitted-email');assert.equal(dom.window.document.querySelector('input').value,credentials.email);assert.equal(submitted,1);
  const outside=new JSDOM('<input type="email">',{url:'https://example.com',runScripts:'outside-only'});assert.equal(outside.window.eval(pageAutomationScript(credentials,'123456')).status,'waiting');outside.window.close();
 }finally{dom.window.close();}
});
test('hidden sign-in script advances through email, password and TOTP fields without a visible browser',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<form><input type="email"><input type="password"><input name="code"><button type="submit">Continue</button></form>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{const inputs=[...dom.window.document.querySelectorAll('input')];for(const input of inputs)Object.defineProperty(input,'offsetWidth',{value:120});let submissions=0;dom.window.document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();submissions++;});
  const statuses=[1,2,3].map(()=>dom.window.eval(pageAutomationScript(credentials,'654321')).status);
  assert.deepEqual(statuses,['submitted-email','submitted-password','submitted-code']);
  assert.deepEqual(inputs.map(input=>input.value),['person@example.com','test-password','654321']);assert.equal(submissions,3);
 }finally{dom.window.close();}
});
test('hidden sign-in selects all available workspaces when the provider offers multi-select',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<main><h1>Choose a workspace</h1><form><label><input type="checkbox">Personal workspace</label><label><input type="checkbox">Team workspace</label><button type="submit">Continue</button></form></main>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{const boxes=[...dom.window.document.querySelectorAll('input')];for(const node of [...boxes,...dom.window.document.querySelectorAll('button')])Object.defineProperty(node,'offsetWidth',{value:120});let submitted=0;dom.window.document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();submitted++;});
  const result=dom.window.eval(pageAutomationScript(credentials,'123456'));
  assert.equal(result.status,'selected-all-workspaces');assert.deepEqual(boxes.map(box=>box.checked),[true,true]);assert.equal(submitted,1);
 }finally{dom.window.close();}
});
test('hidden sign-in completes Codex consent after MFA exactly once',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<h1>Sign in to Codex</h1><form><button type="submit">Continue</button></form>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{
  Object.defineProperty(dom.window.document.querySelector('button'),'offsetWidth',{value:120});
  let submissions=0;dom.window.document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();submissions++;});
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456')).status,'submitted-consent');
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456')).status,'waiting-consent');
  assert.equal(submissions,1);
 }finally{dom.window.close();}
});
test('hidden sign-in never confirms an unrelated consent screen',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<h1>Authorize Another Application</h1><button>Allow</button><input value="private-value">',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{
  Object.defineProperty(dom.window.document.querySelector('button'),'offsetWidth',{value:120});
  let clicks=0;dom.window.document.querySelector('button').onclick=()=>clicks++;
  const result=dom.window.eval(pageAutomationScript(credentials,'123456'));
  assert.equal(result.status,'waiting');assert.equal(clicks,0);
  assert.equal(JSON.stringify(result).includes('private-value'),false);
  assert.equal(JSON.stringify(result).includes(credentials.password),false);
 }finally{dom.window.close();}
});
test('hidden sign-in selects the only offered workspace and continues',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<h1>Select a workspace</h1><form><input type="checkbox"><button type="submit">Continue</button></form>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{
  for(const node of dom.window.document.querySelectorAll('input,button'))Object.defineProperty(node,'offsetWidth',{value:120});
  let submissions=0;dom.window.document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();submissions++;});
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456')).status,'selected-all-workspaces');
  assert.equal(dom.window.document.querySelector('input').checked,true);assert.equal(submissions,1);
 }finally{dom.window.close();}
});
test('hidden sign-in refuses to guess when the provider only allows one workspace',()=>{
 const credentials=parseCredentialLine('person@example.com | test-password | GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
 const dom=new JSDOM('<main><h1>Select a workspace</h1><label><input type="radio" name="workspace">Personal workspace</label><label><input type="radio" name="workspace">Team workspace</label></main>',{url:'https://auth.openai.com',runScripts:'outside-only'});
 try{for(const node of dom.window.document.querySelectorAll('input'))Object.defineProperty(node,'offsetWidth',{value:120});
  assert.equal(dom.window.eval(pageAutomationScript(credentials,'123456')).status,'single-workspace-picker');assert.equal([...dom.window.document.querySelectorAll('input')].some(input=>input.checked),false);
 }finally{dom.window.close();}
});
for(const provider of ['gemini','openai','claude','grok','tokenharbor'])test(`${provider}: separate manager has provider-specific methods`,async()=>{
 const {dom,w,calls}=setupManager(provider);try{
 await new Promise(r=>setTimeout(r,10));
 assert.match(w.document.querySelector('h1').textContent,provider==='gemini'?/Antigravity/:new RegExp(provider==='openai'?'ChatGPT':provider,'i'));
 assert.ok([...w.document.querySelectorAll('#methods button')].some(b=>b.textContent==='API key'));
 if(provider==='tokenharbor'){assert.equal(w.document.querySelector('#methods .primary').textContent,'Free model');w.document.querySelector('#methods .primary').click();await new Promise(r=>setImmediate(r));w.document.querySelector('#session input[type=password]').value='test';w.document.querySelector('#session .submit').click();await new Promise(r=>setImmediate(r));assert.ok(calls.some(x=>x.action==='harbor_connect'));}
 else {w.document.querySelector('#methods .primary').click();await new Promise(r=>setTimeout(r,10));assert.equal(!!w.document.getElementById('callback'),['gemini','openai'].includes(provider));assert.ok(w.document.querySelector('#session .cancel'));}
 if(provider==='openai'){assert.ok([...w.document.querySelectorAll('#methods button')].some(b=>b.textContent==='Import auth.json'));assert.match(w.document.getElementById('pending').textContent,/Resume sign-in/);}
 }finally{dom.window.close();}
});
test('unfinished sign-in can resume after manager window is recreated',async()=>{
 const first=setupManager('openai');first.dom.window.close();const {dom,w,calls}=setupManager('openai');try{
  await new Promise(r=>setTimeout(r,10));w.document.querySelector('#pending-list button').click();await new Promise(r=>setTimeout(r,20));
  assert.ok(calls.some(x=>x.action==='login_status'&&x.fields.state==='pending'));
 }finally{dom.window.close();}
});
test('Sign in shows link choices without opening a browser automatically',async()=>{
 const {dom,w,calls}=setupManager('openai');try{
  await new Promise(r=>setTimeout(r,10));w.document.querySelector('#methods .primary').click();await new Promise(r=>setTimeout(r,15));
  assert.equal(calls.filter(x=>x.action==='open'||x.action==='login_browser').length,0);
  const choices=[...w.document.querySelectorAll('#session .actions button')];
  assert.deepEqual(choices.map(x=>x.textContent),['Copy link','Open browser']);
  choices[0].click();choices[1].click();await new Promise(r=>setImmediate(r));
  assert.ok(calls.some(x=>x.action==='copy'));assert.ok(calls.some(x=>x.action==='open'));
 }finally{dom.window.close();}
});
test('completed OAuth is checked before success and warns about an existing identity',async()=>{
 const {dom,w,calls}=setupManager('openai',{status:'ok'},{status:'verified',duplicate:true});try{
  await new Promise(r=>setTimeout(r,10));w.document.querySelector('#methods .primary').click();await new Promise(r=>setTimeout(r,35));
  assert.ok(calls.some(x=>x.action==='login_review'&&x.fields.state==='test'));
  assert.match(w.document.getElementById('message').textContent,/already connected/);
  assert.equal(calls.filter(x=>x.action==='open').length,0);
 }finally{dom.window.close();}
});
test('quota rings distinguish zero, missing and real values without text outlines',()=>{
 const {dom,w}=setup();try{
 for(const [value,cls,percent] of [[0,'empty','0%'],[null,'unknown','0%'],[.75,'full','75%']]){
 const box=w.document.createElement('div');box.innerHTML=w.eval(`dot(${value},'1mo')`);assert.ok(box.firstChild.classList.contains(cls));assert.equal(box.firstChild.style.getPropertyValue('--quota'),percent);
 }
 const css=fs.readFileSync(path.join(__dirname,'../renderer/styles.css'),'utf8');assert.ok(!css.includes('text-shadow:-1px'));
 }finally{dom.window.close();}
});

test('group rings use existing family windows and exclude paused quota from available average',()=>{
 const {dom,w}=setup();try{
  const a={id:'rings',provider:'gemini',label:'One',status:'Available',windows:[{id:'gemini/5h',family:'gemini',label:'5h',remaining:20},{id:'claude/weekly',family:'claude',label:'1w',remaining:null}]};
  w.state.accounts.set(a.id,a);
  w.state.accounts.set('paused',{...a,id:'paused',disabled:true,windows:[{...a.windows[0],remaining:100}]});
  w.state.collapsed.gemini=true;w.render();
  const dots=[...w.document.querySelectorAll('[data-toggle="gemini"] .dot')];
  assert.equal(dots.length,2,'Do not invent Gemini weekly or Claude hourly windows');
  assert.equal(dots[0].getAttribute('aria-label'),'5h: 20%');
  assert.equal(dots[1].getAttribute('aria-label'),'1w: —');
 }finally{dom.window.close();}
});

test('countdown ticks wait for scrolling, preserve hidden cards and avoid unchanged DOM writes',async()=>{
 const {dom,w}=setup();try{
  w.Date.now=()=>1800000000000;
  const account={id:'timer',provider:'openai',label:'Timer',status:'Available',windows:[{id:'5h',label:'5h',remaining:80,reset:1800000600}]};
  w.state.accounts.set(account.id,account);w.render();
  const node=w.document.querySelector('.account .countdown');
  const observer=new w.MutationObserver(()=>{});observer.observe(node,{subtree:true,attributes:true,childList:true,characterData:true});
  w.refreshCountdowns();w.refreshCountdowns();
  assert.equal(observer.takeRecords().length,0,'Identical countdown must not invalidate paint');
  node.dataset.reset='1799999999';observer.takeRecords();
  w.document.getElementById('groups').dispatchEvent(new w.Event('scroll'));
  w.refreshCountdowns();
  assert.equal(observer.takeRecords().length,0,'Timer must not mutate the scrolling list');
  assert.equal(node.textContent,'10m');
  await new Promise(r=>setTimeout(r,180));
  assert.equal(node.textContent,'Updating…','Overdue countdown is refreshed after scroll settles');
  w.state.collapsed.openai=true;w.render();
  node.dataset.reset='1800001200';observer.takeRecords();w.refreshCountdowns();
  assert.equal(observer.takeRecords().length,0,'Hidden cards do not need timer paint');
  observer.disconnect();
 }finally{dom.window.close();}
});

test('rename finishes on Enter and Escape and applies account updates received while editing',()=>{
 const {dom,w,calls}=setup();try{
  const account={id:'rename',provider:'openai',label:'Original',status:'Available',windows:[]};
  w.state.accounts.set(account.id,account);w.render();
  const card=w.document.querySelector('.account');
  for(const key of ['Enter','Escape']){
   card.querySelector('[data-rename]').dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
   const input=card.querySelector('.editor');assert.ok(input);input.value='Updated';
    w.state.accounts.set(account.id,{...account,tokens:42000});w.render();
   assert.equal(card.querySelector('.editor'),input);
   const before=calls.filter(c=>c.action==='rename').length;
   input.dispatchEvent(new w.KeyboardEvent('keydown',{key,bubbles:true}));
   assert.equal(card.querySelector('.editor'),null);
    assert.match(card.querySelector('.status').textContent,/42K tokens/);
   assert.equal(calls.filter(c=>c.action==='rename').length,before+(key==='Enter'?1:0));
  }
 }finally{dom.window.close();}
});

test('quota window ordering everywhere: 5h above 1w, monthly after weekly, multiple families and collapsed summaries',()=>{
 const {dom,w}=setup();try{
 // 1. Set up Gemini account with reversed incoming windows across multiple families (Claude before Gemini, 1w before 5h)
 const geminiAcc={
  id:'gemini-1',provider:'gemini',label:'Google 1',status:'Available',severity:'normal',active:true,plan:'Pro',
  windows:[
   {id:'claude/weekly',label:'1w',family:'claude',remaining:80,reset:1800000000,floor:10},
   {id:'gemini/weekly',label:'1w',family:'gemini',remaining:90,reset:1800000000,floor:15},
   {id:'claude/5h',label:'5h',family:'claude',remaining:70,reset:1800000000,floor:20},
   {id:'gemini/5h',label:'5h',family:'gemini',remaining:60,reset:1800000000,floor:25}
  ]
 };
 // 2. Set up OpenAI account with reversed incoming windows (1mo, 1w, 5h with null remaining)
 const openaiAcc={
  id:'openai-1',provider:'openai',label:'ChatGPT 1',status:'Available',severity:'normal',active:false,plan:'Plus',
  windows:[
   {id:'openai/monthly',label:'1mo',family:'openai',remaining:null,reset:null,floor:0},
   {id:'openai/weekly',label:'1w',family:'openai',remaining:85,reset:1800000000,floor:10},
   {id:'openai/5h',label:'5h',family:'openai',remaining:45,reset:1800000000,floor:30}
  ]
 };
 w.state.accounts.set(geminiAcc.id,geminiAcc);
 w.state.accounts.set(openaiAcc.id,openaiAcc);
 w.state.collapsed={gemini:false,openai:false};
 w.render();

 // Verify Gemini card in DOM: 5h above 1w, Gemini family above Claude family
 const geminiCard=w.document.querySelector('.account[data-id="gemini-1"]');
 assert.ok(geminiCard,'Gemini card rendered');
 const geminiQuotaKeys=[...geminiCard.querySelectorAll('.quota')].map(q=>q.dataset.key);
 assert.deepEqual(geminiQuotaKeys,['gemini/5h','gemini/weekly','claude/5h','claude/weekly']);

 // Verify family icons: first row has gemini icon, claude 5h row has claude icon
 const geminiFamilies=[...geminiCard.querySelectorAll('.quota')].map(q=>{
  const img=q.querySelector('.quota-family');
  return img&&img.tagName==='IMG'?img.getAttribute('src'):'';
 });
 assert.equal(geminiFamilies[0],'assets/gemini.png');
 assert.equal(geminiFamilies[1],''); // same family gets empty span
 assert.equal(geminiFamilies[2],'assets/claude.png');
 assert.equal(geminiFamilies[3],''); // same family gets empty span

 // Verify that if 1w is exhausted (<1%), 5h is hidden and the remaining 1w row still gets the family icon
 const exhaustedGeminiAcc={
  ...geminiAcc,id:'gemini-exhausted',
  windows:[
   {id:'gemini/weekly',label:'1w',family:'gemini',remaining:0,reset:1800000000,floor:0},
   {id:'gemini/5h',label:'5h',family:'gemini',remaining:50,reset:1800000000,floor:0}
  ]
 };
 w.state.accounts.set(exhaustedGeminiAcc.id,exhaustedGeminiAcc);
 w.render();
 const exhaustedCard=w.document.querySelector('.account[data-id="gemini-exhausted"]');
 const exhaustedQuotaKeys=[...exhaustedCard.querySelectorAll('.quota')].map(q=>q.dataset.key);
 assert.deepEqual(exhaustedQuotaKeys,['gemini/weekly']); // 5h hidden
 const exhaustedImg=exhaustedCard.querySelector('.quota .quota-family');
 assert.equal(exhaustedImg&&exhaustedImg.tagName==='IMG'?exhaustedImg.getAttribute('src'):'','assets/gemini.png');

 // Verify OpenAI card in DOM: 5h above 1w, 1mo after 1w; unknown/missing quota preserved
 const openaiCard=w.document.querySelector('.account[data-id="openai-1"]');
 assert.ok(openaiCard,'OpenAI card rendered');
 const openaiQuotaKeys=[...openaiCard.querySelectorAll('.quota')].map(q=>q.dataset.key);
 assert.deepEqual(openaiQuotaKeys,['openai/5h','openai/weekly','openai/monthly']);
 const openaiValues=[...openaiCard.querySelectorAll('.quota-value')].map(v=>v.textContent.trim());
 assert.match(openaiValues[0],/^5h · 45%$/);
 assert.match(openaiValues[1],/^1w · 85%$/);
 assert.match(openaiValues[2],/^1mo · —$/); // unknown remaining preserved as '—'

 // Verify group header highlights: expanded group highlights ONLY the active account, NOT the header
 const geminiHeader=w.document.querySelector('.group-header[data-toggle="gemini"]');
 assert.ok(!geminiHeader.classList.contains('active'),'Expanded group header must not be active');
 assert.ok(geminiCard.classList.contains('active'),'Active account card must be active');

 // Verify group header highlights when collapsed
 w.state.collapsed.gemini=true;
 w.render();
 assert.ok(geminiHeader.classList.contains('active'),'Collapsed group header with active account must be active');
 assert.ok(w.document.querySelector('.group-header[data-toggle="gemini"] + .cards').hidden,'Cards must be hidden when collapsed');

 // Verify collapsed group header dots order: Gemini 5h, 1w; Claude 5h, 1w
 const geminiDots=[...geminiHeader.querySelectorAll('.dots .dot')].map(d=>d.getAttribute('aria-label'));
 assert.equal(geminiDots.length,4);
 assert.match(geminiDots[0],/^5h:/);
 assert.match(geminiDots[1],/^1w:/);
 assert.match(geminiDots[2],/^5h:/);
 assert.match(geminiDots[3],/^1w:/);

 // Collapsed group with no active accounts must not highlight header
 const openaiHeader=w.document.querySelector('.group-header[data-toggle="openai"]');
 w.state.collapsed.openai=true;
 w.render();
 assert.ok(!openaiHeader.classList.contains('active'),'Collapsed group header with no active accounts must not be active');

 // Collapsed group with active account must highlight header and summary
 const firstAccount=[...w.state.accounts.values()].find(a=>a.provider==='openai');
 if(firstAccount){
   firstAccount.active=true;
   firstAccount.model='gpt-6.1-sol';
   w.render();
   assert.ok(openaiHeader.classList.contains('active'),'Collapsed group header with active account must be active');
   const modelSpan=openaiHeader.querySelector('.header-model');
   assert.ok(modelSpan&&!modelSpan.hidden,'Collapsed group header must show active model');
   assert.equal(modelSpan.textContent,'gpt-6.1-sol');

   w.state.summaryCollapsed={openai:true};
   w.renderSummary();
   const summaryHeader=w.document.querySelector('.summary-group[data-key="openai"] .summary-header');
   assert.ok(summaryHeader.classList.contains('active'),'Collapsed summary header with active account must be active');
   firstAccount.active=false;
 }

 // Verify collapsed summaries: dots in summary-header must be ordered 5h before 1w before 1mo
 w.state.summaryCollapsed={openai:true};
 w.renderSummary();
 const openaiSummary=w.document.querySelector('.summary-group[data-key="openai"]');
 const summaryDots=[...openaiSummary.querySelectorAll('.summary-header .dots .dot')].map(d=>d.getAttribute('aria-label'));
 assert.equal(summaryDots.length,3);
 assert.match(summaryDots[0],/^5h:/);
 assert.match(summaryDots[1],/^1w:/);
 assert.match(summaryDots[2],/^1mo:/);
 assert.match(summaryDots[2],/—/); // null average preserved

 // Verify expanded summaries: summary lines ordered 5h above 1w above 1mo
 w.state.summaryCollapsed={openai:false};
 w.renderSummary();
 const summaryLabels=[...openaiSummary.querySelectorAll('.summary-line .summary-label')].map(l=>l.textContent.trim());
 assert.equal(summaryLabels.length,3);
 assert.match(summaryLabels[0],/^5h · pooled remaining/);
 assert.match(summaryLabels[1],/^1w · pooled remaining/);
 assert.match(summaryLabels[2],/^1mo · pooled remaining/);
 }finally{dom.window.close();}
});
