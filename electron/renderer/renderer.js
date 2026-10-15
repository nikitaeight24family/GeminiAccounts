const state = { accounts: new Map(), collapsed: {}, summaryCollapsed: {}, hidden: true, visible: {}, language:'en',theme:'dark',backendMode:'local',remoteServer:{},remoteServerConfig:{},remoteSnippets:null,providers: ['openai','openai-free','gemini','claude','grok','tokenharbor'] };
let omniLogoClicks=0, omniLogoClickTimer=null, omniEasterActive=false;
const names = {gemini:'Antigravity',openai:'ChatGPT','openai-free':'ChatGPT Free',claude:'Claude',grok:'Grok',tokenharbor:'TokenHarbor'};
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const translations={'Separate browser':'Отдельный браузер','Settings':'Настройки','Theme':'Тема','Language':'Язык','Dark':'Тёмная','Light':'Светлая','Refresh accounts':'Обновить аккаунты','Available':'Доступен','Paused':'Пауза','Limit exhausted':'Лимит исчерпан','Sign in again':'Войти заново','Account blocked':'Аккаунт заблокирован','Quota unavailable':'Квота недоступна','Loading quota':'Загрузка квоты','Updating…':'Обновление…','Recent response':'Недавний ответ','Verification required':'Нужна проверка','Access denied':'Доступ запрещён','Pause':'Приостановить','Resume':'Продолжить','Remove account':'Удалить аккаунт','Lower priority':'Уменьшить приоритет','Raise priority':'Увеличить приоритет','Reserve':'Граница остатка','Quota empty · rest stop':'Квота пуста · отстойник','Connected':'Подключено','Plan unknown':'Подписка неизвестна','Close':'Закрыть','Sign in':'Войти','API key':'API-ключ','Copy link':'Копировать ссылку','Open browser':'Открыть браузер','Paste':'Вставить','Complete sign-in':'Завершить вход','Add account':'Добавить аккаунт','Usage reset':'Сбросить квоту','Double-click to rename':'Двойной щелчок для переименования'};
Object.assign(translations,{'Appearance':'Внешний вид','Accounts and services':'Аккаунты и сервисы','Accounts':'Аккаунты','Archive':'Архив','Services':'Сервисы','Notifications':'Уведомления','Connections':'Подключения','Make Omni comfortable to use.':'Настройте Omni под себя.','Window and account card colors':'Цвета окна и карточек аккаунтов','Interface language':'Язык интерфейса','Latest release':'Последняя версия','Visible services':'Видимые сервисы','Hidden services remain connected.':'Скрытые сервисы остаются подключёнными.','Manage connected accounts and portable archives.':'Управляйте подключёнными аккаунтами и переносимыми архивами.','Move selected accounts between computers.':'Переносите выбранные аккаунты между компьютерами.','Get notified when an account needs attention.':'Уведомления об аккаунтах, которым нужно внимание.','Account alerts':'Уведомления об аккаунтах','Only meaningful account status changes':'Только существенные изменения состояния','Bot token':'Токен бота','Token saved':'Токен сохранён','No token saved':'Токен не сохранён','Paste bot token':'Вставьте токен бота','Save':'Сохранить','Chat ID':'ID чата','Find chat':'Найти чат','Send test notification':'Отправить тестовое уведомление','Connect':'Подключить','Choose how to connect':'Выберите способ подключения','Sign in with Google':'Войти через Google','MoreLogin / another browser':'MoreLogin / другой браузер','Sign in with ChatGPT':'Войти через ChatGPT','Sign in with Claude':'Войти через Claude','Sign in with Grok':'Войти через Grok','Import auth.json':'Импорт auth.json','Resume sign-in':'Продолжить вход','Free model':'Бесплатная модель','Account name':'Название аккаунта','Account added':'Аккаунт добавлен','API billing is separate from subscriptions.':'API оплачивается отдельно от подписки.','Cancel sign-in':'Отменить вход','Sign-in cancelled':'Вход отменён','Callback URL / code':'Ссылка обратного вызова / код','Code accepted':'Код принят','Checking connections…':'Проверка подключений…','Configuration and model catalog verified':'Настройки и каталог моделей проверены','Not connected':'Не подключено','Application detected':'Приложение обнаружено','Application not detected':'Приложение не обнаружено','Restart application…':'Перезапустить приложение…','Restart':'Перезапустить','Running tasks may be interrupted. Save your work first.':'Текущие задачи могут прерваться. Сначала сохраните работу.','Catalog verification does not send a message to the model.':'Проверка каталога не отправляет сообщение модели.','Connected applications are checked and repaired automatically. Restarting always requires your permission.':'Подключения проверяются и восстанавливаются автоматически. Перезапуск — только с вашего разрешения.','Restart the application to load updated settings. Save your work first.':'Перезапустите приложение для применения настроек. Сначала сохраните работу.','Connection restored automatically':'Подключение восстановлено автоматически','A configured model is unavailable':'Одна из выбранных моделей недоступна','Choose an available model in the application:':'Выберите доступную модель в приложении. Сейчас недоступны:'});
translations['Checking sign-in']='Проверка входа';
translations['Account archive']='Архив аккаунтов';
Object.assign(translations,{'What Omni checked':'Что Omni проверил','App found':'Приложение найдено','App not found':'Приложение не найдено','Files Omni manages':'Файлы, которыми управляет Omni','Settings written':'Какие настройки записаны','Models in gateway':'Моделей в шлюзе','Models selected in app':'Модели, выбранные в приложении','User action needed':'Что нужно от вас','Save work, then restart to apply these settings.':'Сохраните работу и перезапустите приложение, чтобы применить настройки.','Start a new terminal session to apply these settings.':'Откройте новый сеанс терминала, чтобы применить настройки.','Everything is ready':'Всё готово','Settings are verified and active.':'Настройки проверены и уже действуют.','Connected; waiting for you to apply changes':'Подключено; осталось применить изменения','Show setup details':'Показать, что меняется','Hide setup details':'Скрыть подробности','Omni writes these files when you connect:':'При подключении Omni записывает эти файлы:','Connect this application to install Omni settings and its current model catalog.':'Подключите приложение, чтобы записать настройки Omni и текущий каталог моделей.','Catalog checked without sending a model request.':'Каталог проверен без отправки запроса модели.','Models currently used':'Модель, используемая сейчас','No model request is active':'Сейчас нет активного запроса модели','Configure connection':'Настроить подключение','Select an available model in the app:':'Выберите доступную модель в приложении:'});
Object.assign(translations,{'What Omni checked':'Что проверил Omni','App found':'Приложение найдено','App not found':'Приложение не найдено','Files Omni manages':'Файлы Omni','Settings written':'Записанные настройки','Models in gateway':'Моделей в шлюзе','Models selected in app':'Модели в приложении','User action needed':'Требуется от вас','Save work, then restart to apply these settings.':'Сохраните работу и перезапустите приложение, чтобы применить настройки.','Start a new terminal session to apply these settings.':'Откройте новый сеанс терминала, чтобы применить настройки.','Everything is ready':'Всё готово','Settings are verified and active.':'Настройки проверены и применяются.','Connected; waiting for you to apply changes':'Подключено; осталось применить изменения','Show setup details':'Показать подробности подключения','Hide setup details':'Скрыть подробности подключения','Omni writes these files when you connect:':'При подключении Omni записывает эти файлы:','Connect this application to install Omni settings and its current model catalog.':'Подключите приложение, чтобы записать настройки Omni и актуальный каталог моделей.','Catalog checked without sending a model request.':'Каталог проверен без отправки запроса модели.','Models currently used':'Текущая модель','No model request is active':'Сейчас нет активного запроса модели','Configure connection':'Настроить подключение','Select an available model in the app:':'Выберите доступную модель в приложении:','Verified':'Проверено','Will be created on connect':'Будет создан при подключении','No fixed model is set; the app uses its model picker.':'Модель не закреплена: приложение использует собственный список.','Omni connection':'Подключение Omni','Omni settings are not installed for this application.':'Настройки Omni для приложения ещё не записаны.','Restart is needed to load the settings.':'Нужен перезапуск, чтобы применить настройки.','Complete the connection step below.':'Выполните подключение ниже.'});
translations['Connection needs attention']='Подключение требует внимания';translations['Check and repair']='Проверить и исправить';
Object.assign(translations,{'Apply Omni patch':'Применить патч Omni','Check connection':'Проверить подключение','Restore stock settings':'Вернуть стоковые настройки','Restore stock settings for this application?':'Вернуть стоковые настройки этого приложения?','Stock settings restored':'Стоковые настройки восстановлены','Connections are checked only. Nothing changes until you apply a patch.':'Проверка только читает состояние. Изменения появятся после явного применения патча.','Patch applied; restart is still manual.':'Патч применён; перезапуск выполняется вручную.'});
Object.assign(translations,{'Codex settings':'Настройки Codex','Omni provider profile':'Профиль провайдера Omni','Omni model catalog':'Каталог моделей Omni','Claude Desktop settings':'Настройки Claude Desktop','Active profile index':'Индекс активного профиля','Omni model profile':'Профиль моделей Omni','Claude Code CLI settings':'Настройки Claude Code CLI','Local gateway address':'Адрес локального шлюза','Gateway access key':'Ключ доступа к шлюзу','OpenAI-compatible Responses protocol':'Протокол Responses для OpenAI','OpenAI sign-in bypass':'Вход OpenAI не требуется','Automatic model discovery':'Автоматическое обнаружение моделей','Gateway provider':'Провайдер шлюза','Available model list':'Список доступных моделей','Present; not managed by Omni':'Файл есть, но Omni им не управляет.'});
Object.assign(translations,{'Remote server':'Удалённый сервер','Host / IP address':'Хост / IP-адрес','SSH port':'SSH-порт','SSH username':'SSH-логин','SSH password':'SSH-пароль','Password (optional if using key)':'Пароль (необязательно при ключе)','SSH private key file':'Файл приватного ключа SSH','Select private key file…':'Выберите файл ключа…','FIDO / Security Key':'FIDO / Ключ безопасности','Authenticate via Windows Hello / hardware FIDO key (requires touch)':'Вход через Windows Hello / FIDO-ключ (требуется касание)','Test connection':'Проверить соединение','Deploy backend to server':'Перенести бекенд на сервер','Backend routing mode':'Режим работы бекенда','Local backend (127.0.0.1)':'Локальный бекенд (127.0.0.1)','Connect clients to server':'Подключение клиентов к серверу','Copy PowerShell':'Копировать PowerShell','Copy Bash':'Копировать Bash','Copy JSON':'Копировать JSON','Copied!':'Скопировано!','Deploying…':'Развёртывание…','Connection test failed':'Ошибка подключения'});
const t=value=>state.language==='ru'?(translations[value]||value):value;
const aliases=new Map();
function formatModel(name){
  if(!name) return '';
  const s = String(name).trim();
  if(s==='gemini-3.8-flash-high' || s==='3.8 Flash High' || s==='3.8 Flash') return '3.8 флеш';
  if(s==='gemini-3.8-flash-medium' || s==='3.8 Flash Med') return '3.8 флеш мед';
  if(s==='gemini-3.8-flash-low' || s==='3.8 Flash Low') return '3.8 флеш лоу';
  if(s==='gemini-3.5-flash-lite' || s==='3.5 Flash Lite') return '3.5 флеш лайт';
  if(s==='gemini-3.5-flash-low' || s==='3.5 Flash Med' || s==='3.5 Flash Medium') return '3.5 флеш мед';
  if(s==='gemini-3.5-flash-extra-low' || s==='3.5 Flash Low') return '3.5 флеш лоу';
  if(s==='gemini-3-flash' || s==='3 Flash') return '3 флеш';
  if(s.startsWith('gemini-')) {
    return s.slice(7).split('-').map(w=>w.charAt(0).toUpperCase()+w.slice(1)).join(' ');
  }
  return s;
}
function accountName(a){return a.customLabel|| (state.hidden?(a.privateLabel||a.label):a.label);}
function icon(kind){const shapes={pause:'<path d="M7 5v14M17 5v14" stroke-width="4"/>',play:'<path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',up:'<path d="m7 10 5-5 5 5M12 5v14"/>',down:'<path d="m7 14 5 5 5-5M12 5V5"/>',remove:'<path d="m7 7 10 10M7 17 17 7"/>',reset:'<path d="M4 10a8 8 0 1 1 2 9M4 4v6h6"/>',settings:'<path d="M9.6 2.5h4.8l.5 2.7 1.4.8 2.6-.9 2.4 4.2-2.1 1.8v1.8l2.1 1.8-2.4 4.2-2.6-.9-1.4.8-.5 2.7H9.6l-.5-2.7-1.4-.8-2.6.9-2.4-4.2 2.1-1.8v-1.8L2.7 9.1l2.4-4.2 2.6.9 1.4-.8Z"/><circle cx="12" cy="12" r="4"/>',pin:'<path d="m9 3 9 3-3 5 1 5-5-2-5 3 2-6ZM8 14l-4 7"/>',eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',closed:'<path d="M3 10c2 7 16 7 18 0M6 14l-2 3m8-1v4m6-6 2 3"/>'};return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${shapes[kind]||shapes.eye}</svg>`;}
$('settings').innerHTML=icon('settings');
document.querySelector('.brand')?.addEventListener('click',()=>{if(omniEasterActive)return;omniLogoClicks++;clearTimeout(omniLogoClickTimer);if(omniLogoClicks>=3){omniLogoClicks=0;triggerOmniEasterEgg();}else omniLogoClickTimer=setTimeout(()=>{omniLogoClicks=0;},900);});
function providerIcon(p){const file=p==='gemini'?'antigravity':p.startsWith('openai')?'openai':p==='claude'?'claude':p==='grok'?'grok':'omni';return `<img class="provider-icon ${p}" src="assets/${file}.png" alt="">`;}
function buttonIcon(kind){const file=kind==='pause'?'pause':kind==='play'?'play':kind==='up'?'up':kind==='down'?'down':kind==='remove'?'remove':'reset';return `<img class="button-icon" src="assets/${file}.png" alt="">`;}
function exhausted(a){return a.severity!=='error'&&(String(a.status).toLowerCase().includes('exhaust')||(a.windows||[]).some(w=>w.remaining!=null&&w.remaining<=1));}
function effectiveRemaining(a,w){if(w.remaining==null)return null;const enclosing=(a.windows||[]).find(x=>x.family===w.family&&((w.label==='5h'&&(x.label==='1w'||x.label==='1mo'))||(w.label==='1w'&&x.label==='1mo')));if(enclosing&&enclosing.remaining!=null){if(enclosing.remaining<=1)return 0;return Math.min(w.remaining,enclosing.remaining);}return w.remaining;}
function bucket(a){return a.provider==='openai'&&String(a.plan).toLowerCase()==='free'?'openai-free':a.provider;}
function severityClass(a){ return a.severity || (a.status==='Available'?'normal':'warning'); }
function formatTokens(value){const n=Number(value)||0;if(n>=1e9)return (n/1e9).toFixed(n>=1e10?0:1).replace(/\.0$/,'')+'B tokens';if(n>=1e6)return (n/1e6).toFixed(n>=1e7?0:1).replace(/\.0$/,'')+'M tokens';if(n>=1e3)return (n/1e3).toFixed(n>=1e4?0:1).replace(/\.0$/,'')+'K tokens';return Math.round(n)+' tokens';}
function totalAccountTokens(){return [...state.accounts.values()].reduce((total,account)=>total+Math.max(0,Number(account.tokens)||0),0);}
function triggerOmniEasterEgg(){if(omniEasterActive)return;const brand=document.querySelector('.brand');if(!brand)return;omniEasterActive=true;brand.classList.add('omni-spin');setTimeout(()=>{brand.classList.remove('omni-spin');const total=document.createElement('span');total.className='easter-total';total.textContent=formatTokens(totalAccountTokens());brand.replaceChildren(total);brand.title='Total tokens through all accounts';},900);}
function dot(value,label){ const known=Number.isFinite(value), percent=known?Math.round(Math.max(0,Math.min(1,value))*100):null; const cls=!known?'unknown':percent<1?'empty':percent<30?'warn':'full'; return `<span class="dot ${cls}" style="--quota:${percent??0}%" title="${esc(label)} · ${percent==null?'—':percent+'%'}" aria-label="${esc(label)}: ${percent==null?'—':percent+'%'}"><span>${esc(label)}</span></span>`; }
function displayWindowLabel(label){return String(label||'').toLowerCase()==='1mo'?'1m':String(label||'');}
function windowRank(label){const s=String(label||'').toLowerCase();return s==='5h'||s.includes('5h')||s.includes('hour')?1:s==='1w'||s.includes('1w')||s.includes('week')?2:s==='1mo'||s==='1m'||s.includes('month')?3:4;}
function familyRank(family,provider){const f=String(family||provider||'').toLowerCase();return f==='gemini'||f==='google'?1:f==='claude'||f==='claude-native'?2:3;}
function sortWindows(windows,provider){return [...(windows||[])].sort((a,b)=>(familyRank(a.family,provider)-familyRank(b.family,provider))||(windowRank(a.label)-windowRank(b.label))||String(a.id||'').localeCompare(String(b.id||'')));}
const groupNodes = new Map();
const cardNodes = new Map();
// Patch a retained tree. Quota updates never recreate controls or focused inputs.
function patchNode(current,next){
  if(current.nodeType===3){if(current.nodeValue!==next.nodeValue)current.nodeValue=next.nodeValue;return;}
  for(const attr of [...current.attributes])if(!next.hasAttribute(attr.name))current.removeAttribute(attr.name);
  for(const attr of [...next.attributes])if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
  const old=[...current.childNodes];
  for(let i=0;i<next.childNodes.length;i++){
    const fresh=next.childNodes[i];
    const key=fresh.nodeType===1?fresh.getAttribute('data-key'):null;
    let existing=key?old.find(n=>n.nodeType===1&&n.getAttribute('data-key')===key):current.childNodes[i];
    if(!existing||existing.nodeType!==fresh.nodeType||existing.nodeName!==fresh.nodeName){existing=fresh.cloneNode(true);current.insertBefore(existing,current.childNodes[i]||null);}
    else {if(current.childNodes[i]!==existing)current.insertBefore(existing,current.childNodes[i]||null);patchNode(existing,fresh);}
  }
  while(current.childNodes.length>next.childNodes.length)current.lastChild.remove();
}
function patchMarkup(el,html){if(el._markup===html)return false;const next=el.cloneNode(false);next.innerHTML=html;patchNode(el,next);el._markup=html;return true;}
function orderChildren(parent,nodes){nodes.forEach((node,i)=>{if(parent.children[i]!==node)parent.insertBefore(node,parent.children[i]||null);});}
let renderQueued = false, scrollUntil = 0, scrollRenderTimer;
// Keep incoming data current, but commit the latest state once scrolling settles.
// Moving quota groups or rewriting text during a scroll invalidates its raster tiles.
function queueRender(){
  if(performance.now()<scrollUntil){clearTimeout(scrollRenderTimer);scrollRenderTimer=setTimeout(queueRender,Math.max(1,scrollUntil-performance.now()));return;}
  if(renderQueued)return;renderQueued=true;
  requestAnimationFrame(()=>{renderQueued=false;if(performance.now()<scrollUntil){queueRender();return;}render();});
}
document.querySelector('.sidebar').addEventListener('scroll',()=>{scrollUntil=performance.now()+120;},{passive:true,capture:true});
function setText(node,text){if(node.textContent!==text)node.textContent=text;}
function accountSort(a,b){ return (a.severity==='error'?0:1)-(b.severity==='error'?0:1)||(b.priority||0)-(a.priority||0)||String(a.id).localeCompare(String(b.id)); }
function render(){
  const groups = new Map();
  for(const a of state.accounts.values()){const p=bucket(a);if(!groups.has(p))groups.set(p,[]);groups.get(p).push(a);}
  for(const p of state.providers) if(!groups.has(p)) groups.set(p,[]);
  const visibleProviders = state.providers.filter(p=>p!=='tokenharbor').map(p=>[p,groups.get(p)]).filter(([p,rows])=>state.visible[p==='openai-free'?'openai':p]!==false && rows.length);
  for(const [provider, rows] of visibleProviders){
    let node=groupNodes.get(provider);
    if(!node){
      node=document.createElement('section'); node.className='group';
      node.innerHTML=`<button class="group-header">${providerIcon(provider)}<span class="chevron"></span><span class="title"></span><span class="dots"></span></button><div class="cards"></div>`;
      node.querySelector('.group-header').dataset.toggle=provider;
      groupNodes.set(provider,node);
    }
    if(!node.parentElement)$('groups').appendChild(node);
    const header=node.querySelector('.group-header'), cards=node.querySelector('.cards');
    const collapsed=!!state.collapsed[provider];
    const active=collapsed&&rows.some(a=>a.active);if(header.classList.contains('active')!==active)header.classList.toggle('active',active);
    setText(header.querySelector('.chevron'),collapsed?'▸':'▾');
    setText(header.querySelector('.title'),`${names[provider]} · ${rows.length}pcs`);
    let currentModel=collapsed?rows.find(a=>a.active&&a.model)?.model:'';
    let modelNode=header.querySelector('.header-model');
    if(currentModel&&!modelNode){modelNode=document.createElement('span');modelNode.className='header-model';modelNode.dataset.key='current-model';header.insertBefore(modelNode,header.querySelector('.dots'));}
    if(modelNode){modelNode.hidden=!currentModel||!collapsed;if(currentModel){setText(modelNode,formatModel(currentModel));modelNode.title=t('Models currently used')+': '+currentModel;}}
    const families=provider==='gemini'?['gemini','claude']:[provider];
    const limitLabels=[...new Set(rows.flatMap(a=>(a.windows||[]).map(w=>w.label)).filter(Boolean))].sort((a,b)=>windowRank(a)-windowRank(b));
     patchMarkup(header.querySelector('.dots'),families.map(family=>limitLabels.filter(label=>rows.some(a=>(a.windows||[]).some(w=>w.label===label&&(provider!=='gemini'||w.family===family)))).map(label=>{const xs=rows.filter(a=>!a.disabled&&a.severity!=='error').flatMap(a=>(a.windows||[]).filter(w=>w.label===label&&(provider!=='gemini'||w.family===family)).map(w=>effectiveRemaining(a,w))).filter(Number.isFinite);return dot(xs.length?xs.reduce((x,y)=>x+y,0)/xs.length/100:null,displayWindowLabel(label));}).join('')).join(''));
    if(cards.hidden!==collapsed)cards.hidden=collapsed;const dots=header.querySelector('.dots');if(dots.hidden===collapsed)dots.hidden=!collapsed;
    const ordered=[...rows].sort(accountSort);
    const usable=ordered.filter(a=>!exhausted(a));
    const empty=ordered.filter(exhausted);
    const wanted=[...usable,...empty];
    if(empty.length){
      let divider=cards.querySelector('.divider'), label=cards.querySelector('.divider-label');
      if(!divider){divider=document.createElement('div');divider.className='divider';label=document.createElement('div');label.className='divider-label';cards.append(divider,label);}
      setText(label,t('Quota empty · rest stop'));
    } else cards.querySelectorAll('.divider,.divider-label').forEach(n=>n.remove());
    for(const a of wanted){
      let el=cardNodes.get(a.id);
      if(!el){el=document.createElement('article');el.className='account';el.dataset.id=a.id;cardNodes.set(a.id,el);}
      updateCard(el,a); if(el.parentElement!==cards)cards.appendChild(el);
    }
    for(const [id,el] of cardNodes){if(el.parentElement===cards && !wanted.some(a=>a.id===id))el.remove();}
    orderChildren(cards,[...usable.map(a=>cardNodes.get(a.id)),...cards.querySelectorAll('.divider,.divider-label'),...empty.map(a=>cardNodes.get(a.id))]);
  }
  for(const [provider,node] of groupNodes){if(!visibleProviders.some(([p])=>p===provider))node.remove();}
  orderChildren($('groups'),visibleProviders.map(([p])=>groupNodes.get(p)));
  for(const [id,el] of cardNodes)if(!state.accounts.has(id)){el.remove();cardNodes.delete(id);}
  renderSummary();
}
function renderSummary(){
  const box=$('summaries');if(!box)return;
  const groups=['gemini','openai','claude','grok','tokenharbor'].filter(p=>state.visible[p]!==false);
  const html=groups.map(provider=>{
    const accounts=[...state.accounts.values()].filter(a=>a.provider===provider),collapsed=state.summaryCollapsed?.[provider]!==false;
    const labels=provider==='tokenharbor'?[]:[...new Set(accounts.flatMap(a=>(a.windows||[]).filter(w=>provider!=='gemini'||w.family==='gemini').map(w=>w.label)).filter(Boolean))].sort((a,b)=>windowRank(a)-windowRank(b));
    const averages=labels.map(label=>{const values=accounts.filter(a=>!a.disabled&&a.severity!=='error').flatMap(a=>(a.windows||[]).filter(w=>w.label===label&&(provider!=='gemini'||w.family==='gemini')).map(w=>effectiveRemaining(a,w))).filter(v=>v!=null);return values.length?values.reduce((a,b)=>a+b,0)/values.length/100:null;});
    const title=provider==='gemini'?'Google Gemini':provider==='openai'?'OpenAI':names[provider]+(provider==='tokenharbor'?` · ${accounts.length}pcs`:'');
     const body=labels.map((label,i)=>{const value=averages[i],windows=accounts.flatMap(a=>(a.windows||[]).filter(w=>w.label===label&&(provider!=='gemini'||w.family==='gemini'))).filter(w=>w.reset).sort((a,b)=>a.reset-b.reset);let position=(value||0)*100;const markers=windows.slice(0,8).map(w=>{const left=position;position+=((100-(value||0)*100)/Math.max(1,windows.length));return `<span class="forecast" data-position="${left}" title="${countdown(w.reset)}">${countdown(w.reset)}</span>`;}).join('');return `<div class="summary-line" style="--quota-color:${quotaColor(value==null?null:value*100)}"><div class="summary-label"><span>${provider==='gemini'?'Gemini · ':''}${displayWindowLabel(label)} · pooled remaining</span><b>${value==null?'—':(value*100).toFixed(1).replace('.',',')+'%'}</b></div><div class="summary-bar"><i style="width:${(value||0)*100}%"></i></div><div class="forecast-row">${markers}</div></div>`;}).join('');
    const content=provider==='tokenharbor'?`<div class="harbor-cards">${accounts.sort(accountSort).map(a=>{const card=document.createElement('article');updateCard(card,a);card.dataset.key=a.id;return card.outerHTML;}).join('')||`<div class="empty-list">${t('No accounts added')}</div>`}</div>`:body;
    const groupActive=collapsed&&accounts.some(a=>a.active);
     return `<section class="summary-group" data-key="${provider}"><div class="summary-header ${groupActive?'active':''}"><button class="summary-toggle" data-summary="${provider}">${collapsed?'▸':'▾'} &nbsp; ${title}</button>${collapsed?`<span class="dots">${labels.map((label,i)=>dot(averages[i],displayWindowLabel(label))).join('')}</span>`:''}<button class="summary-add" data-add="${provider}" title="${t('Add account')}"><img src="assets/add.png" alt=""></button></div><div class="summary-body" ${collapsed?'hidden':''}>${content}</div></section>`;
  }).join('');
  if(patchMarkup(box,html))requestAnimationFrame(layoutForecasts);
}
function countdown(reset){
  if(!reset)return '—';let seconds=reset-Date.now()/1000;
  if(seconds<=0)return t('Updating…');if(seconds<60)return '< 1m';
  const minutes=Math.floor(seconds/60),days=Math.floor(minutes/1440),hours=Math.floor(minutes/60)%24;
  return days?`${days}d ${hours}h`:hours?`${hours}h ${minutes%60}m`:`${minutes%60}m`;
}
function resetColor(reset,label,now=Date.now()/1000){
  if(!reset)return 'var(--muted)';const seconds=reset-now;
  if(seconds<=0)return 'var(--muted)';
   const ratio=Math.max(0,Math.min(1,seconds/(label==='1mo'||label==='1m'?30*86400:label==='1w'?7*86400:5*3600)));
  const start=ratio<=.5?[102,226,167]:[245,197,107],end=ratio<=.5?[245,197,107]:[255,68,85],fraction=ratio<=.5?ratio*2:(ratio-.5)*2,factor=state.theme==='light'?.62:1;
  return '#'+start.map((a,i)=>Math.round((a+(end[i]-a)*fraction)*factor).toString(16).padStart(2,'0')).join('');
}
function layoutForecasts(){
  const measurements=[...document.querySelectorAll('.forecast-row')].map(row=>({row,width:row.clientWidth,labels:[...row.children].map(label=>({label,size:label.getBoundingClientRect().width}))}));
  for(const {width,labels} of measurements){if(!width)continue;let right=-3;for(const {label,size} of labels){const desired=width*Number(label.dataset.position||0)/100,left=Math.max(0,Math.min(width-size,desired-size-3)),visible=left>=right+3,position=left+'px',visibility=visible?'visible':'hidden';if(label.style.left!==position)label.style.left=position;if(label.style.visibility!==visibility)label.style.visibility=visibility;if(visible)right=left+size;}}
}
function quotaColor(value){return value==null?'var(--muted)':value>30?'var(--green)':value>10?'#f5c56b':'#ff8d8d';}
function updateCard(el,a){
  if(el.querySelector('.editor')||el.querySelector('.dragging'))return;
  const signature=JSON.stringify([state.hidden,state.language,state.theme,a]);
  if(el._markup!=null&&el._accountSignature===signature)return;
  el._accountSignature=signature;
  const preservedFills=new Map([...el.querySelectorAll('.fill[data-key="fill"]')].map(fill=>[fill.closest('.quota')?.dataset.key,fill]));
  const controls=(action,title,html,extra='')=>`<button class="control" data-action="${action}" data-id="${esc(a.id)}" title="${esc(t(title))}" ${extra}>${html}</button>`;
  const plan=String(a.plan||'Plan unknown').replace(/(^|[ _])([a-z])/g,(_,space,c)=>space+c.toUpperCase());
  const windows=sortWindows(a.windows||[],a.provider);
  const visibleWindows=windows.filter(w=>!(w.label==='5h'&&windows.some(x=>x.family===w.family&&x.label==='1w'&&x.remaining!=null&&x.remaining<1)));
  const rows=visibleWindows.map((w,index)=>{
    const color=quotaColor(w.remaining),floor=w.floor||0;
    const family=a.provider==='gemini'&&(index===0||visibleWindows[index-1].family!==w.family)?`<img class="quota-family" src="assets/${w.family}.png" alt="">`:a.provider==='gemini'?'<span class="quota-family"></span>':'';
     return `<div class="quota ${a.provider==='gemini'?'google-quota':''}" data-key="${esc(w.id)}" style="--quota-color:${color}">${family}<span class="quota-value">${esc(displayWindowLabel(w.label))} · ${w.remaining==null?'—':Math.round(w.remaining)+'%'}</span><span class="quota-slider" data-slider="${esc(w.id)}" data-id="${esc(a.id)}" style="--floor:${floor}%"><span class="track" data-key="track"><span class="fill" data-key="fill" style="width:${Math.max(0,Math.min(100,w.remaining||0))}%"></span></span><span class="marker" data-key="marker"></span><span class="bubble" data-key="bubble">${floor}%</span></span><span class="countdown" data-reset="${w.reset||''}" data-window="${esc(w.label)}" style="color:${resetColor(w.reset,w.label)}">${countdown(w.reset)}</span></div>`;
  }).join('');
  const resets=Array.from({length:Math.min(20,a.resetCredits||0)},(_,i)=>controls('reset','Usage reset',buttonIcon('reset'),`data-credit="${i}" ${a.resetAvailable?'':'disabled'}`)).join('');
  const html=`<div class="row heading" data-key="identity"><span class="name" data-rename="${esc(a.id)}" title="${t('Double-click to rename')}">${providerIcon(a.provider)}<span>${esc(accountName(a))}</span></span><span class="model" data-key="model">${esc(a.model||'')}</span><span class="controls" data-key="controls">${resets}<span class="priority">${controls('priority','Lower priority',buttonIcon('down'),'data-delta="-1"')}<span>${a.priority||0}</span>${controls('priority','Raise priority',buttonIcon('up'),'data-delta="1"')}</span>${controls('remove','Remove account','×')}${controls('pause',a.disabled?'Resume':'Pause',buttonIcon(a.disabled?'play':'pause'))}</span></div><div class="row status-row" data-key="status"><span class="plan ${a.provider==='gemini'?'google-plan':''}">${esc(t(plan))}</span><span class="status ${severityClass(a)}" title="${esc(a.detail||'')}">${esc(t(a.status))} · ${formatTokens(a.tokens)}${a.uptime?` · ${esc(a.uptime)}`:''}</span></div><div class="windows" data-key="windows">${rows}</div>`;
  patchMarkup(el,html);
  for(const [key,fill] of preservedFills){const fresh=el.querySelector(`.quota[data-key="${CSS.escape(key||'')}"] .fill[data-key="fill"]`);if(fresh&&fresh!==fill){fresh.replaceWith(fill);}}
  for(const w of windows){const fill=el.querySelector(`.quota[data-key="${CSS.escape(w.id)}"] .fill[data-key="fill"]`);if(fill){const width=Math.max(0,Math.min(100,w.remaining||0))+'%';if(fill.style.width!==width)fill.style.width=width;}}
  const className=`account ${a.provider==='gemini'?'google-account':''} ${a.active?'active':''}`;if(el.className!==className)el.className=className;if(el.dataset.id!==a.id)el.dataset.id=a.id;
}
function command(action, fields){return window.omni.send(action,fields).catch(e=>{$('notice').textContent=e.message;return null;});}
let startupSnapshotPending=true, firstInventoryPending=true, bufferedAccountEvents=[];
function applyAccountEvent(e,paint=true){if(e.event==='account')state.accounts.set(e.account.id,e.account);if(e.event==='accounts'){const ids=new Set(e.ids);for(const id of state.accounts.keys())if(!ids.has(id))state.accounts.delete(id);}if(paint)queueRender();}
function acceptAccountEvent(e){if(firstInventoryPending){bufferedAccountEvents.push(e);if(e.event!=='accounts')return;for(const buffered of bufferedAccountEvents)applyAccountEvent(buffered,false);bufferedAccountEvents=[];firstInventoryPending=false;queueRender();return;}applyAccountEvent(e);}
window.omni.onEvent(e=>{if(e.event==='account'||e.event==='accounts'){if(startupSnapshotPending)bufferedAccountEvents.push(e);else acceptAccountEvent(e);} if(e.event==='preferences')applyPreferences(e.preferences); if(e.event==='ready')$('notice').textContent='● '+t('Connected'); if(e.event==='error'||e.event==='notice')$('notice').textContent=e.message; if(e.event==='remote_deploy_progress'){const m=$('ssh-deploy-msg'),b=$('ssh-deploy-progress');if(m&&b){b.style.display='block';m.textContent='● '+e.message;}}});
function applyPreferences(p){if(!p)return;state.language=p.language||'en';state.theme=p.theme||'dark';state.telegram=p.telegram||{};state.summaryCollapsed=p.summaryCollapsed||{};state.hidden=!!p.private;state.visible=p.visible||state.visible;state.backendMode=p.backendMode||'local';state.remoteServer=p.remoteServer||{};state.remoteServerConfig=p.remoteServerConfig||{};state.remoteSnippets=p.remoteSnippets||null;localStorage.setItem('private',state.hidden?'1':'0');for(const [k,v] of Object.entries(p.collapsed||{}))state.collapsed[k]=v;document.documentElement.dataset.theme=p.theme||'dark';$('privacy').innerHTML=`<img src="assets/eye-${state.hidden?'closed':'open'}.png" alt="">`;$('pin').innerHTML='<img src="assets/pin.png" alt="">';render();}
document.querySelector('.sidebar').addEventListener('click',e=>{const toggle=e.target.closest('[data-toggle]');if(toggle){const p=toggle.dataset.toggle;state.collapsed[p]=!state.collapsed[p];command('collapse',{provider:p,value:state.collapsed[p]});render();return}const b=e.target.closest('[data-action]');if(!b)return;const action=b.dataset.action;if(action==='priority'){const a=state.accounts.get(b.dataset.id);if(!a)return;const previous=Number(a.priority)||0;const next=Math.max(0,Math.min(999,previous+(Number(b.dataset.delta)||0)));if(next===previous)return;a.priority=next;render();command('priority',{id:b.dataset.id,delta:next-previous}).then(result=>{if(result===null){a.priority=previous;render();}});return;}if(action==='remove'&&!confirm(t('Remove account')+'?'))return;command(action,{id:b.dataset.id});});
document.querySelector('.sidebar').addEventListener('dblclick',e=>{const name=e.target.closest('[data-rename]');if(!name||name.querySelector('input'))return;const id=name.dataset.rename,a=state.accounts.get(id),input=document.createElement('input');input.className='editor';input.value=a.customLabel||a.label||'';name.replaceChildren(input);input.focus();input.select();let saved=false;const finish=cancel=>{if(saved)return;saved=true;if(!cancel)command('rename',{id,label:input.value.trim()});if(input.isConnected)input.remove();const card=cardNodes.get(id);if(card){card._markup=null;updateCard(card,state.accounts.get(id)||a);}};input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();finish(false);}if(event.key==='Escape'){event.preventDefault();finish(true);}};input.onblur=()=>finish(false);});
$('privacy').onclick=()=>{state.hidden=!state.hidden;localStorage.setItem('private',state.hidden?'1':'0');render();command('private',{value:state.hidden});};
$('pin').onclick=()=>window.omni.pin().then(v=>{$('pin').classList.toggle('active',v);$('notice').textContent=v?'Pinned above other windows':'Window pin disabled';});
$('summaries').addEventListener('click',e=>{const toggle=e.target.closest('[data-summary]');if(toggle){const p=toggle.dataset.summary;state.summaryCollapsed[p]=state.summaryCollapsed[p]===false;command('summary_collapse',{provider:p,value:state.summaryCollapsed[p]});renderSummary();return;}const add=e.target.closest('[data-add]');if(add){$('settings-view').hidden=true;window.omni.panel(false);window.omni.accountManager(add.dataset.add).catch(error=>{$('notice').textContent=error.message;});}});
$('settings').onclick=()=>{connectionsVisible=false;const open=$('settings-view').hidden;$('settings-view').hidden=!open;window.omni.panel(open);if(open)settings();};
function archiveInlinePrompt(title, confirm=false){
 const value=window.prompt(title+'\n'+t('At least 8 characters.')); if(value===null||value.length<8)return '';
 if(confirm){const again=window.prompt(t('Confirm password'));if(again!==value)return '';}
 return value;
}
async function renderInlineArchive(){
 const host=$('inline-archive-list');if(!host)return;host.replaceChildren();const rows=await command('archive_inventory');if(!Array.isArray(rows)||!rows.length){host.textContent=t('No portable Google or OpenAI accounts found.');return;}
 const groups=new Map();for(const row of rows){const provider=row.provider==='antigravity'?'antigravity':'openai';const area=String(row.area||t('No subscription')).replace(/[-_]/g,' ');const key=provider+':'+area;if(!groups.has(key))groups.set(key,{provider,area,rows:[]});groups.get(key).rows.push(row);}
 for(const group of groups.values()){const section=document.createElement('section');section.className='inline-archive-group';const head=document.createElement('h3');head.innerHTML=`<img src="assets/${group.provider}.png" alt=""><span>${esc(group.area)}</span>`;section.append(head);for(const row of group.rows){const line=document.createElement('label');line.className='inline-archive-row';line.innerHTML=`<input type="checkbox" data-inline-archive-id="${esc(row.id)}"><img src="assets/${group.provider}.png" alt=""><span><b>${esc(row.email||row.id)}</b><small>${esc(row.label||'')}</small></span>`;section.append(line);}host.append(section);}
 const all=$('inline-archive-select-all');if(all){all.checked=false;all.onchange=()=>host.querySelectorAll('[data-inline-archive-id]').forEach(box=>box.checked=all.checked);host.onchange=()=>{const boxes=[...host.querySelectorAll('[data-inline-archive-id]')];all.checked=boxes.length>0&&boxes.every(box=>box.checked);};}
}
function setupInlineArchive(){const exportButton=$('inline-archive-export'),importButton=$('inline-archive-import');if(exportButton)exportButton.onclick=async()=>{const ids=[...document.querySelectorAll('[data-inline-archive-id]:checked')].map(box=>box.dataset.inlineArchiveId);if(!ids.length){$('notice').textContent=t('Nothing selected');return;}const password=archiveInlinePrompt(t('Export archive'),true);if(password){const result=await window.omni.archiveExport({ids,password});$('notice').textContent=result?.cancelled?'':`${t('Archive exported')}: ${result?.accounts||ids.length}`;}};if(importButton)importButton.onclick=async()=>{const password=archiveInlinePrompt(t('Import archive'));if(!password)return;const result=await window.omni.archiveImport(password);if(!result?.cancelled){$('notice').textContent=`${t('Imported')}: ${(result.imported||[]).length} · ${t('Skipped')}: ${(result.skipped||[]).length}`;renderInlineArchive();}};renderInlineArchive();}
function settings(){ $('settings-view').querySelector('h1').textContent=t('Settings');
  const visible=state.visible||{};const telegram=state.telegram||{};const remoteServer=state.remoteServer||{};
  const remoteConfig=state.remoteServerConfig||{};const remoteSnippets=state.remoteSnippets;
  const backendMode=state.backendMode||'local';
  const counts={};for(const a of state.accounts.values()){counts[a.provider]=(counts[a.provider]||0)+1;}
  $('settings-content').innerHTML=`<nav class="settings-nav" aria-label="${t('Settings')}">
    <button class="selected" data-settings-tab="appearance">${t('Appearance')}</button>
    <button data-settings-tab="accounts">${t('Accounts')}</button>
    <button data-settings-tab="server">${t('Remote server')}</button>
    <button data-settings-tab="notifications">${t('Notifications')}</button>
    <button data-settings-connections>${t('Connections')}</button></nav>
  <div class="settings-pages">
    <section class="settings-page" data-settings-page="appearance">
      <div class="settings-card"><h2>${t('Appearance')}</h2>
        <p class="settings-description">${t('Make Omni comfortable to use.')}</p>
        <label class="settings-row"><span><b>${t('Theme')}</b><small>${t('Window and account card colors')}</small></span>
          <select id="theme"><option value="dark">${t('Dark')}</option><option value="light">${t('Light')}</option></select></label>
        <label class="settings-row"><span><b>${t('Language')}</b><small>${t('Interface language')}</small></span>
          <select id="language"><option value="en">English</option><option value="ru">Русский</option></select></label></div>
      <div class="settings-card settings-actions"><button id="refresh">${t('Refresh accounts')}</button>
        <button id="github">${t('Latest release')}</button></div></section>
    <section class="settings-page" data-settings-page="accounts" hidden>
      <div class="settings-card"><h2>${t('Accounts')}</h2>
        <p class="settings-description">${t('Manage connected accounts and visibility in Omni.')}</p>
        <div class="settings-service-switches">${[['gemini','Antigravity'],['openai','OpenAI'],['claude','Claude'],['grok','Grok'],['tokenharbor','TokenHarbor']].map(([p,n])=>`<label class="settings-row"><span class="settings-provider">${providerIcon(p)}<b>${n}</b><small>${counts[p]?counts[p]+' '+t('connected accounts'):t('No accounts connected')}</small></span><input class="switch" type="checkbox" data-service="${p}" ${visible[p]!==false?'checked':''}></label>`).join('')}</div></div>
      <div class="settings-card inline-archive-card"><div class="inline-archive-head"><h2>${t('Archive')}</h2>
        <div class="inline-archive-actions"><button id="inline-archive-export">${t('Export archive')}</button>
        <button id="inline-archive-import">${t('Import archive')}</button></div></div>
        <label class="inline-archive-select"><input id="inline-archive-select-all" type="checkbox">${t('Select all')}</label>
        <div id="inline-archive-list"></div></div></section>
    <section class="settings-page" data-settings-page="server" hidden>
      <div class="settings-card">
        <div class="settings-card-head-row">
          <div><h2>${t('Remote server')}</h2>
            <p class="settings-description" style="margin:4px 0 0">${t('Run Omni backend 24/7 on Ubuntu server with zero desktop stalls.')}</p></div>
          <button id="ssh-help-btn" class="help-circle-btn" title="${t('Detailed guide: how remote backend works')}">?</button></div>
        <div class="ssh-form">
          <div class="ssh-row-2col">
            <div class="ssh-input-group"><label for="ssh-host">${t('Host / IP address')}</label>
              <input id="ssh-host" value="${esc(remoteConfig.host||remoteServer.host||'')}" placeholder="e.g. 93.127.223.106"></div>
            <div class="ssh-input-group"><label for="ssh-port">${t('SSH port')}</label>
              <input id="ssh-port" type="number" value="${esc(remoteConfig.port||22)}"></div></div>
          <div class="ssh-row-equal">
            <div class="ssh-input-group"><label for="ssh-user">${t('SSH username')}</label>
              <input id="ssh-user" value="${esc(remoteConfig.user||'root')}" placeholder="root"></div>
            <div class="ssh-input-group"><label for="ssh-password">${t('SSH password')}</label>
              <input id="ssh-password" type="password" placeholder="${t('Password (optional if using key)')}"></div></div>
          <div class="ssh-input-group"><label for="ssh-key-path">${t('SSH private key file')}<small>${t('RSA / Ed25519 (.pem, .key, id_rsa, id_ed25519)')}</small></label>
            <div class="ssh-file-picker"><input id="ssh-key-path" value="${esc(remoteConfig.key_path||'')}" placeholder="${t('Select private key file…')}">
              <button id="ssh-key-browse">${t('Browse…')}</button></div></div>
          <div class="ssh-fido-box"><div><b>${t('FIDO / Security Key')}</b>
            <small>${t('Authenticate via Windows Hello / hardware FIDO key (requires touch)')}</small></div>
            <input class="switch" id="ssh-fido" type="checkbox" ${remoteConfig.use_fido?'checked':''}></div>
          <div class="ssh-actions-bar">
            <button id="ssh-test" class="btn-secondary-action">${t('Test connection')}</button>
            <button id="ssh-deploy" class="btn-primary-action">${t('Deploy backend to server')}</button>
            <span id="ssh-status" class="ssh-status-tag"></span></div>
          <div id="ssh-deploy-progress" style="display:none;margin-top:10px">
            <div id="ssh-deploy-msg" style="font-size:12px;font-family:Consolas,monospace;color:var(--green)"></div></div></div></div>
      <div class="settings-card" id="remote-backend-mode-card"><h2>${t('Backend routing mode')}</h2>
        <p class="settings-description">${t('Switch active inference and quota management between local machine and remote server.')}</p>
        <div class="segmented-switch">
          <button class="backend-switch-btn ${backendMode==='local'?'active':''}" data-backend-mode="local">${t('Local backend (127.0.0.1)')}</button>
          <button class="backend-switch-btn ${backendMode==='remote'?'active':''}" data-backend-mode="remote">${t('Remote server')} (${esc(remoteServer.host||remoteConfig.host||t('Not configured'))})</button></div></div>
      <div class="settings-card" id="remote-client-snippets-card" ${remoteServer.host?'':'hidden'}>
        <h2>${t('Connect clients to server')}</h2>
        <p class="settings-description">${t('Run these one-liners in your terminal to instantly connect Codex, Claude Code, and Claude Desktop directly to your server backend.')}</p>
        <div class="client-snippet-row"><div class="client-snippet-head"><b>Claude Code CLI</b>
          <div class="client-snippet-actions">
            <button class="copy-snippet-btn" data-snippet="claude-ps">${t('Copy PowerShell')}</button>
            <button class="copy-snippet-btn" data-snippet="claude-bash">${t('Copy Bash')}</button></div></div>
          <pre class="client-snippet-code"><code>${esc(remoteSnippets?.claude_code_ps||'')}</code></pre></div>
        <div class="client-snippet-row"><div class="client-snippet-head"><b>Codex Desktop &amp; CLI (~/.codex/config.toml)</b>
          <div class="client-snippet-actions">
            <button class="copy-snippet-btn" data-snippet="codex-ps">${t('Copy PowerShell')}</button>
            <button class="copy-snippet-btn" data-snippet="codex-bash">${t('Copy Bash')}</button></div></div>
          <pre class="client-snippet-code"><code>${esc(remoteSnippets?.codex_ps||'')}</code></pre></div>
        <div class="client-snippet-row"><div class="client-snippet-head"><b>Claude Desktop (claude_desktop_config.json)</b>
          <button class="copy-snippet-btn" data-snippet="desktop-json">${t('Copy JSON')}</button></div>
          <pre class="client-snippet-code"><code>${esc(remoteSnippets?.claude_desktop_json||'')}</code></pre></div></div></section>
    <section class="settings-page" data-settings-page="notifications" hidden>
      <div class="settings-card"><h2>Telegram</h2>
        <p class="settings-description">${t('Get notified when an account needs attention.')}</p>
        <label class="settings-row"><span><b>${t('Account alerts')}</b><small>${t('Only meaningful account status changes')}</small></span>
          <input class="switch" id="tg-enabled" type="checkbox" ${telegram.enabled?'checked':''}></label>
        <label class="settings-field" for="tg-token">${t('Bot token')}<span id="tg-token-status" class="settings-description" style="${telegram.tokenSaved?'color:var(--green)':''}">${t(telegram.tokenSaved?'Token saved':'No token saved')}</span></label>
        <div class="settings-input-action"><input id="tg-token" type="password" autocomplete="off" placeholder="${t('Paste bot token')}">
          <button id="tg-save">${t('Save')}</button></div>
        <label class="settings-field" for="tg-chat">${t('Chat ID')}</label>
        <div class="settings-input-action"><input id="tg-chat" value="${esc(telegram.chatId||'')}" placeholder="${t('Chat ID')}">
          <button id="tg-find">${t('Find chat')}</button></div>
        <div class="settings-actions"><button id="tg-test">${t('Send test notification')}</button></div></div></section>
    <section class="settings-page" data-settings-page="connections" id="inline-connections-page" hidden></section>
  </div>
  <div id="ssh-help-modal" class="omni-modal" hidden>
    <div class="omni-modal-backdrop"></div>
    <div class="omni-modal-dialog">
      <div class="omni-modal-header">
        <div class="omni-modal-title">
          <span class="omni-modal-badge">${t('Omni Cloud Engine')}</span>
          <h3>${t('Remote Server Backend')}</h3></div>
        <button class="omni-modal-close" id="ssh-help-close">&times;</button></div>
      <div class="omni-modal-body">
        <div class="help-section">
          <h4 class="help-section-title help-accent">${t('Why run Omni backend on a remote server? (Benefits)')}</h4>
          <div class="help-benefits-grid">
            <div class="help-benefit-card">
              <b>⚡ ${t('24/7 Continuous Uptime')}</b>
              <p>${t('Your accounts pool never resets or drops. The backend works round the clock even when your laptop sleeps, battery dies, or Wi-Fi reconnects.')}</p></div>
            <div class="help-benefit-card">
              <b>🛡️ ${t('Zero Codex Stalls & Disconnects')}</b>
              <p>${t('OpenAI Codex, Claude Code, and Claude Desktop talk directly to a dedicated server with gigabit connectivity, completely bypassing local PC sleep loops.')}</p></div>
            <div class="help-benefit-card">
              <b>🌐 ${t('Connect From Any Device')}</b>
              <p>${t('Once deployed, connect multiple computers, laptops, or mobile devices to the exact same centralized pool of 44+ accounts using single-line terminal commands.')}</p></div>
            <div class="help-benefit-card">
              <b>🔋 ${t('Zero Battery & RAM Load')}</b>
              <p>${t('Heavy request routing, quota tracking, background token refreshing, and proxy failovers run entirely on the server. Your desktop stays completely lightweight.')}</p></div></div></div>
        <div class="help-section">
          <h4 class="help-section-title">${t('How Omni automated deployment works (Technical Details)')}</h4>
          <ol class="help-steps-list">
            <li><b>${t('1. One-Click SSH Automation')}</b>
              <p>${t('Omni connects to your Ubuntu server via SSH (supporting password, RSA/Ed25519 private keys, or hardware FIDO YubiKey). All commands and payload transfers are piped in a single batch to avoid multiple logins or hardware touch prompts.')}</p></li>
            <li><b>${t('2. High-Performance Daemon Installation')}</b>
              <p>${t('Omni downloads and verifies the official Linux 64-bit CLIProxyAPI binary (v8.0.16) and registers a persistent background systemd user service (`omni.service`). User lingering is enabled so the daemon stays active even when no SSH session is open.')}</p></li>
            <li><b>${t('3. Secure Token & Account Migration')}</b>
              <p>${t('All existing OAuth tokens and account configurations (Google Antigravity, OpenAI Codex, Claude, Grok) and custom models catalogs are bundled and copied to `~/.omni-server/auth/` with restricted 0600 Linux permissions (accessible only by the server user).')}</p></li>
            <li><b>${t('4. Security & Network Isolation')}</b>
              <p>${t('Omni automatically configures the Ubuntu UFW firewall to allow port 8317/tcp and generates an isolated 256-bit cryptographically secure Bearer client key. Only authorized clients with this key can access your models.')}</p></li>
            <li><b>${t('5. Instant Client Switching')}</b>
              <p>${t('Use the "Backend routing mode" switch to seamlessly toggle between your local machine (127.0.0.1) and the remote server without restarting apps or losing account sessions.')}</p></li></ol></div></div></div></div>`;
  const getSSHConfig=()=>({host:($('ssh-host')?.value||'').trim(),port:parseInt($('ssh-port')?.value||'22',10),user:($('ssh-user')?.value||'root').trim(),password:$('ssh-password')?.value||'',key_path:($('ssh-key-path')?.value||'').trim(),use_fido:!!$('ssh-fido')?.checked});
  const saveSSHConfig=()=>command('remote_server_save',{config:getSSHConfig()});
  ['ssh-host','ssh-port','ssh-user','ssh-key-path'].forEach(id=>{const el=$(id);if(el)el.onchange=saveSSHConfig;});
  if($('ssh-fido')) $('ssh-fido').onchange=saveSSHConfig;
  if($('ssh-key-browse')){$('ssh-key-browse').onclick=async()=>{const chosen=await window.omni.pickKeyFile();if(chosen&&$('ssh-key-path')){$('ssh-key-path').value=chosen;saveSSHConfig();}};}
  if($('ssh-test')){$('ssh-test').onclick=async()=>{const status=$('ssh-status');if(status){status.className='ssh-status-badge';status.textContent=t('Testing…');}saveSSHConfig();const res=await command('remote_server_test',{config:getSSHConfig()});if(status){if(res&&res.connected){status.className='ssh-status-badge ok';status.textContent=`✓ ${t('Connected')}: ${res.os} (${res.user})`;}else{status.className='ssh-status-badge error';status.textContent=`✕ ${res?.error||t('Connection test failed')}`;}}};}
  if($('ssh-deploy')){$('ssh-deploy').onclick=async()=>{const status=$('ssh-status'),prog=$('ssh-deploy-progress'),msg=$('ssh-deploy-msg');if(!confirm(t('Deploy backend to server')+'? '+t('Existing accounts will be transferred in encrypted form.')))return;if(prog)prog.style.display='block';if(msg)msg.textContent=t('Deploying…');saveSSHConfig();try{const res=await command('remote_server_deploy',{config:getSSHConfig()});if(res&&res.success){if(msg)msg.textContent=`✓ ${t('Backend successfully deployed to')} ${res.server_ip}!`;if(status){status.className='ssh-status-badge ok';status.textContent=`✓ ${t('Connected')}`;}settings();}else{if(msg)msg.textContent=`✕ ${res?.error||t('Deployment failed')}`;}}catch(err){if(msg)msg.textContent=`✕ ${err.message}`;}};}
  document.querySelectorAll('.backend-switch-btn').forEach(btn=>{btn.onclick=async()=>{const mode=btn.dataset.backendMode;await command('remote_server_switch',{mode});document.querySelectorAll('.backend-switch-btn').forEach(b=>b.classList.toggle('active',b.dataset.backendMode===mode));};});
  document.querySelectorAll('.copy-snippet-btn').forEach(btn=>{btn.onclick=()=>{const type=btn.dataset.snippet,s=state.remoteSnippets;let text='';if(type==='claude-ps')text=s?.claude_code_ps||'';else if(type==='claude-bash')text=s?.claude_code_bash||'';else if(type==='codex-ps')text=s?.codex_ps||'';else if(type==='codex-bash')text=s?.codex_bash||'';else if(type==='desktop-json')text=s?.claude_desktop_json||'';if(text){window.omni.copy(text);const orig=btn.textContent;btn.textContent=t('Copied!');setTimeout(()=>{if(btn.isConnected)btn.textContent=orig;},1200);}};});
  if($('ssh-help-btn')) $('ssh-help-btn').onclick=()=>{$('ssh-help-modal').hidden=false;};
  if($('ssh-help-close')) $('ssh-help-close').onclick=()=>{$('ssh-help-modal').hidden=true;};
  $('ssh-help-modal')?.querySelector('.omni-modal-backdrop')?.addEventListener('click',()=>{$('ssh-help-modal').hidden=true;});
  document.querySelectorAll('[data-settings-tab]').forEach(button=>button.onclick=()=>{
    document.querySelectorAll('[data-settings-tab]').forEach(b=>b.classList.toggle('selected',b===button));
    document.querySelector('[data-settings-connections]')?.classList.remove('selected');
    connectionsVisible=false;
    document.querySelectorAll('[data-settings-page]').forEach(page=>page.hidden=page.dataset.settingsPage!==button.dataset.settingsTab);
    if(button.dataset.settingsTab==='accounts'){
      setupInlineArchive();
    }
  });
  document.querySelector('[data-settings-connections]').onclick=()=>{
    connectionsVisible=true;
    document.querySelectorAll('[data-settings-tab]').forEach(b=>b.classList.remove('selected'));
    document.querySelector('[data-settings-connections]').classList.add('selected');
    document.querySelectorAll('[data-settings-page]').forEach(page=>page.hidden=page.id!=='inline-connections-page');
    openConnectionsPanel();
  };
  $('theme').value=state.theme;
  $('language').value=state.language;
  document.querySelectorAll('[data-service]').forEach(input=>input.onchange=e=>command('visibility',{provider:e.target.dataset.service,value:e.target.checked}));
  $('theme').onchange=e=>command('theme',{value:e.target.value});
  $('language').onchange=e=>command('language',{value:e.target.value});
  $('tg-enabled').onchange=e=>command('telegram_preferences',{enabled:e.target.checked,chatId:$('tg-chat').value});
  $('tg-chat').onchange=e=>command('telegram_preferences',{enabled:$('tg-enabled').checked,chatId:e.target.value});
  $('tg-save').onclick=async()=>{
    const input=$('tg-token');
    const token=(input.value||'').trim();
    if(!token)return;
    const status=$('tg-token-status');
    if(status){status.textContent=t('Saving…');status.style.color='';}
    try{
      const result=await command('telegram_token',{token});
      if(result){
        state.telegram=result.telegram||state.telegram;
        if(status){
          status.style.color='var(--green)';
          status.textContent='✓ '+t('Token saved');
        }
        if(input.isConnected)input.value='';
      }else{
        if(status){
          status.style.color='#ff6b7a';
          status.textContent='✕ '+t('Could not save token');
        }
      }
    }catch(err){
      if(status){
        status.style.color='#ff6b7a';
        status.textContent='✕ '+(err.message||t('Error'));
      }
    }
  };
  $('tg-find').onclick=()=>command('telegram_find');
  $('tg-test').onclick=()=>command('telegram_test');
  $('refresh').onclick=()=>command('refresh');
  $('github').onclick=()=>window.omni.open('https://github.com/nikitaeight24family/Omni/releases/latest');
  setupInlineArchive();
}
command('snapshot').then(result=>{if(result){applyPreferences(result.preferences);for(const a of result.accounts||[])state.accounts.set(a.id,a);firstInventoryPending=!result.inventoryComplete;}const events=bufferedAccountEvents;bufferedAccountEvents=[];startupSnapshotPending=false;for(const e of events)acceptAccountEvent(e);queueRender();});

let dragging=null;
document.querySelector('.sidebar').addEventListener('pointerdown',e=>{const slider=e.target.closest('[data-slider]');if(!slider)return;dragging={slider,id:slider.dataset.id,window:slider.dataset.slider,value:0};slider.classList.add('dragging');slider.setPointerCapture(e.pointerId);moveFloor(e);});
function moveFloor(e){if(!dragging)return;const r=dragging.slider.getBoundingClientRect();dragging.value=Math.round(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*100);dragging.slider.style.setProperty('--floor',dragging.value+'%');dragging.slider.querySelector('.bubble').textContent=dragging.value+'%';}
document.querySelector('.sidebar').addEventListener('pointermove',moveFloor);
document.querySelector('.sidebar').addEventListener('pointerup',()=>{if(!dragging)return;const d=dragging;dragging=null;d.slider.classList.remove('dragging');command('floor',{id:d.id,window:d.window,value:d.value});});
let countdownTimer;
const countdownStyle=document.createElement('span').style;
function refreshCountdowns(){
  clearTimeout(countdownTimer);
  if(document.hidden)return;
  if(performance.now()<scrollUntil){countdownTimer=setTimeout(refreshCountdowns,Math.max(1,scrollUntil-performance.now()));return;}
  document.querySelectorAll('[data-reset]').forEach(n=>{
    if(n.closest('[hidden]'))return;
    const text=countdown(Number(n.dataset.reset));if(n.textContent!==text)n.textContent=text;
    countdownStyle.color=resetColor(Number(n.dataset.reset),n.dataset.window);
    if(n.style.color!==countdownStyle.color)n.style.color=countdownStyle.color;
  });
}
setInterval(refreshCountdowns,15000);
document.querySelector('.sidebar').addEventListener('pointercancel',()=>{if(!dragging)return;dragging.slider.classList.remove('dragging');dragging=null;queueRender();});

let connectionRows=[], connectionsVisible=false;
const connectionMessages={configured:'Configuration and model catalog verified',not_connected:'Not connected',transport_settings:'Connection settings need attention',provider_selection:'Provider selection needs attention',invalid_config:'Configuration cannot be read safely',missing_config:'Configuration is missing',other_provider:'Another provider is selected',gateway_auth:'Gateway rejected authorization',gateway_unavailable:'Local gateway is unavailable',gateway_busy:'Gateway is temporarily busy',gateway_error:'Gateway error',invalid_gateway_response:'Unexpected gateway response',model_unavailable:'A configured model is unavailable',check_failed:'Could not verify this connection'};
function renderConnections(){
 if(!connectionsVisible)return;
 const host=$('inline-connections-page');if(!host)return;
 patchMarkup(host,`<p>${t('Connections are checked only. Nothing changes until you apply a patch.')}</p><div class="connection-list">${connectionRows.map(row=>{
  const ready=row.connected&&row.status==='configured'&&!row.restartRequired;
  const details=!!row.detailsOpen;
  const fileRows=(row.files||[]).map(file=>{const verified=file.exists&&row.connected;return `<li><b>${esc(t(file.role))}</b><code>${esc(file.path)}</code><span class="connection-file-state ${verified?'ok':''}">${verified?'✓ '+t('Verified'):file.exists?t('Present; not managed by Omni'):'○ '+t('Will be created on connect')}</span></li>`;}).join('');
  const check=(ok,label,detail='')=>{const s=row.checking?'checking':ok?'ok':'pending';return `<div class="connection-step ${s}"><span class="step-mark">${s==='ok'?'✓':s==='checking'?'':'•'}</span><div><b>${t(label)}</b>${detail?`<small>${detail}</small>`:''}</div></div>`;};
  const managed=(row.managedSettings||[]).map(x=>`<div class="connection-setting"><code>${esc(x.name)}</code><span>${esc(x.value)}</span></div>`).join('');
  const configuredModels=(row.configuredModels||[]).map(x=>`<code>${esc(x)}</code>`).join(' ')||`<span class="connection-note">${t('No fixed model is set; the app uses its model picker.')}</span>`;
  const connectionVerified=row.connected&&row.status==='configured';
  const broken=row.connected&&!row.repaired&&(row.status==='missing_config'||row.status==='invalid_config');
  const needsPatch=(!row.maintenanceEnabled&&(!row.connected||['missing_config','invalid_config','transport_settings','provider_selection','model_unavailable'].includes(row.status)))||(row.maintenanceEnabled&&row.status==='not_connected');
  const stock=row.connected||row.status!=='not_connected';
  const applyButton=`<button data-connect="${esc(row.id)}">${t('Apply Omni patch')}</button>`;
  const action=row.checking?'':row.restartRequired?`<div class="connection-user-action"><b>${t('User action needed')}</b><span>${t(row.id==='claude_cli'?'Start a new terminal session to apply these settings.':'Save work, then restart to apply these settings.')}</span><button data-restart="${esc(row.id)}">${t(row.id==='claude_cli'?'New terminal session required':'Restart application…')}</button></div>`:needsPatch?`<div class="connection-user-action"><b>${t('User action needed')}</b><span>${t('Connect this application to install Omni settings and its current model catalog.')}</span>${applyButton}</div>`:ready?`<div class="connection-good"><b>✓ ${t('Everything is ready')}</b><span>${t('Settings are verified and active.')}</span></div>`:`<div class="connection-user-action"><b>${t('Connection needs attention')}</b><span>${esc(t(connectionMessages[row.status]||row.status))}</span><button data-recheck="${esc(row.id)}">${t('Check connection')}</button></div>`;
  const restoreButton=stock?`<button class="connection-restore" data-restore="${esc(row.id)}">${t('Restore stock settings')}</button>`:'';
  return `<article class="connection-card ${ready?'is-ready':''}" data-key="${esc(row.id)}"><div class="connection-card-head"><div><h2>${esc(row.name)}</h2><span class="connection-overall ${row.checking?'checking':ready?'ok':'pending'}">${row.checking?t('Checking connections…'):ready?'✓ '+t('Everything is ready'):row.connected?esc(t(connectionMessages[row.status]||row.status)):t('Not connected')}</span></div><button class="connection-details-toggle" data-details="${esc(row.id)}">${t(details?'Hide setup details':'Show setup details')}</button></div><div class="connection-steps">${check(!!row.detected,row.detected?'App found':'App not found')}${check(connectionVerified,'Omni connection',connectionVerified?t('Configuration and model catalog verified'):t('Omni settings are not installed for this application.'))}${check(row.gatewayModelCount!=null&&!row.unavailableModels?.length,'Models in gateway',row.gatewayModelCount==null?'':`${row.gatewayModelCount} · ${t('Catalog checked without sending a model request.')}`)}${check(ready,'Everything is ready',ready?t('Settings are verified and active.'):t(row.restartRequired?'Restart is needed to load the settings.':'Complete the connection step below.'))}</div>${row.unavailableModels?.length?`<p class="connection-warning">${t('Select an available model in the app:')} ${row.unavailableModels.map(esc).join(', ')}</p>`:''}${details?`<div class="connection-details"><h3>${t('Files Omni manages')}</h3><ul class="connection-files">${fileRows}</ul><h3>${t('Settings written')}</h3><div class="connection-chips">${managed}</div><h3>${t('Models selected in app')}</h3><div class="connection-model-list">${configuredModels}</div><p class="connection-note">${t('Catalog checked without sending a model request.')}</p></div>`:''}${action}${restoreButton}</article>`;
 }).join('')}</div>`);
 host.querySelectorAll('[data-details]').forEach(button=>button.onclick=()=>{const row=connectionRows.find(r=>r.id===button.dataset.details);if(row){row.detailsOpen=!row.detailsOpen;renderConnections();}});
 host.querySelectorAll('[data-connect]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const rows=await command('connect',{client:button.dataset.connect});if(Array.isArray(rows)){connectionRows=rows;renderConnections();}}finally{if(button.isConnected)button.disabled=false;}});
 host.querySelectorAll('[data-recheck]').forEach(button=>button.onclick=async()=>{
   button.disabled=true;
   const label=button.textContent;
   button.textContent=t('Checking connections…');
   try{
     const rows=await command('connections');
     if(Array.isArray(rows))connectionRows=rows;
     renderConnections();
   }finally{
     if(button.isConnected){button.disabled=false;button.textContent=label;}
   }
 });
 host.querySelectorAll('[data-restore]').forEach(button=>button.onclick=async()=>{
   const row=connectionRows.find(item=>item.id===button.dataset.restore);
   if(!row||!confirm(t('Restore stock settings for this application?')))return;
   button.disabled=true;
   try{
     const result=await command('restore_client',{client:row.id});
     if(Array.isArray(result?.connections))connectionRows=result.connections;
     $('notice').textContent=t('Stock settings restored');
     renderConnections();
   }finally{if(button.isConnected)button.disabled=false;}
 });
 host.querySelectorAll('[data-restart]').forEach(button=>button.onclick=async()=>{
   const row=connectionRows.find(r=>r.id===button.dataset.restart);
   if(!confirm(t('Restart')+' '+row.name+'? '+t('Running tasks may be interrupted. Save your work first.')))return;
   button.disabled=true;
   try{
     // Restart only the application whose button was pressed. A Claude
     // restart must never close Codex (and vice versa).
     const result=await command('restart_client',{client:row.id,confirmed:true});
     if(result?.message)$('notice').textContent=t(result.message);
     row.restartRequired=false;
     if(result?.clients){
       for(const item of connectionRows){
         if(result.clients.includes(item.id))item.restartRequired=false;
       }
     }
     const rows=await command('connections');
     if(Array.isArray(rows))connectionRows=rows;
     renderConnections();
   }finally{if(button.isConnected)button.disabled=false;}
 });
}
async function openConnectionsPanel(){
  connectionsVisible=true;$('settings-view').hidden=false;window.omni.panel(true);
  if(!document.querySelector('[data-settings-page="connections"]'))settings();
  document.querySelectorAll('[data-settings-tab]').forEach(b=>b.classList.remove('selected'));
  document.querySelector('[data-settings-connections]')?.classList.add('selected');
  document.querySelectorAll('[data-settings-page]').forEach(page=>page.hidden=page.id!=='inline-connections-page');
  if(!connectionRows.length){
    connectionRows=[{id:'codex',name:'Codex',checking:true,status:'checking',connected:false,issues:[],restartRequired:false,files:[],managedSettings:[],configuredModels:[]},{id:'claude_desktop',name:'Claude Desktop',checking:true,status:'checking',connected:false,issues:[],restartRequired:false,files:[],managedSettings:[],configuredModels:[]},{id:'claude_cli',name:'Claude Code CLI',checking:true,status:'checking',connected:false,issues:[],restartRequired:false,files:[],managedSettings:[],configuredModels:[]}];
    renderConnections();
  }
  const rows=await command('connections');
  if(Array.isArray(rows))connectionRows=rows;
  renderConnections();
};
window.omni.onEvent(e=>{
  if(e.event==='connections'&&Array.isArray(e.connections)){
    connectionRows=e.connections;
    renderConnections();
  }
});
Object.assign(window,{state,render,renderSummary,updateCard,sortWindows,windowRank});
