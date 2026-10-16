/* Production settings surface generated from the Google AI Studio prototype.
 * This file deliberately contains no provider logic. It adapts the prototype
 * controls to the existing Electron bridge exposed by preload.js. */
(function () {
  const providerNames = {gemini:'Antigravity', openai:'OpenAI', claude:'Claude', grok:'Grok', tokenharbor:'TokenHarbor'};
  const providerKeys = ['gemini','openai','claude','grok','tokenharbor'];
  const local = {screen:'appearance', archive:[], selected:new Set(), reveal:false, initialized:false, clients:[]};
  const el = id => document.getElementById(id);
  const send = (action, fields={}) => window.omni.send(action, fields);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const mask = value => { const text=String(value||''); const at=text.indexOf('@'); if(at<2)return text; return `${text.slice(0,2)}${'•'.repeat(Math.min(6,Math.max(1,at-2)))}${text.slice(at)}`; };
  const icon = name => ({check:'✓',warn:'!',error:'×',pending:'…',off:'—'}[name]||'');
  const setBadge = (node, kind, text) => { if(!node)return; node.className=`badge badge-${kind||'neutral'}`; const label=node.querySelector('span:last-child')||node; if(label===node)node.textContent=text; else label.textContent=text; };

  function modal(title, body, actions='') {
    const backdrop=el('modal-backdrop'); if(!backdrop)return;
    el('modal-title').textContent=title; el('modal-body-content').innerHTML=body; el('modal-footer-actions').innerHTML=actions;
    backdrop.classList.add('open');
  }
  function closeModal(){ el('modal-backdrop')?.classList.remove('open'); }
  function routeConfig(ctx){
    return {host:(el('ssh-host')?.value||'').trim(), port:Number(el('ssh-port')?.value||22), user:(el('ssh-user')?.value||'').trim(), password:el('ssh-pass')?.value||'', key_path:local.keyPath||'', use_fido:!!el('ssh-fido-toggle')?.checked};
  }
  function statusSummary(ctx){
    const accounts=[...(ctx.state.accounts?.values?.()||[])];
    const providers=new Set(accounts.map(a=>a.provider)).size;
    const route=ctx.state.backendMode==='remote'&&ctx.state.remoteBackendStatus?.connected ? 'Удалённый маршрут активен' : 'Локальный маршрут активен';
    const summary=el('global-status-summary');
    if(summary)summary.innerHTML=`<span class="badge badge-success"><span>${icon('check')}</span><span>${escapeHtml(route)}</span></span><span class="status-strip-dot">·</span><span><strong>${accounts.length}</strong> аккаунтов</span><span class="status-strip-dot">·</span><span><strong>${providers}</strong> провайдера активно</span>`;
    const count=el('nav-pill-accounts'); if(count)count.textContent=String(accounts.length);
    const remote=el('nav-pill-remote'); if(remote)remote.textContent=ctx.state.backendMode==='remote'?'SSH':'Лок.';
    const sync=el('global-last-sync'); if(sync)sync.textContent='Синхронизация доступна вручную';
  }
  function showScreen(name){
    local.screen=name;
    document.querySelectorAll('.screen-container').forEach(s=>s.classList.toggle('active',s.id===`screen-${name}`));
    document.querySelectorAll('.nav-btn').forEach(b=>{const active=b.dataset.screen===name;b.setAttribute('aria-current',active?'page':'false');b.classList.toggle('active',active);});
    if(name==='accounts')loadArchive(ctxRef);
    if(name==='connections')loadConnections(ctxRef);
  }
  let ctxRef=null;

  function renderProviders(ctx){
    const body=el('providers-table-body'); if(!body)return;
    const accounts=[...(ctx.state.accounts?.values?.()||[])];
    body.innerHTML=providerKeys.map(key=>{
      const rows=accounts.filter(a=>a.provider===key); const visible=ctx.state.visible?.[key]!==false;
      const error=rows.some(a=>a.severity==='error'); const state=rows.length?(error?'error':'connected'):'no_accounts';
      const stateText=state==='connected'?'Подключено':state==='error'?'Требует внимания':'Нет аккаунтов';
      const stateKind=state==='connected'?'success':state==='error'?'error':'neutral';
      return `<tr data-provider-row="${key}"><td><div class="table-primary"><strong>${providerNames[key]}</strong></div></td><td>${rows.length}</td><td><span class="badge badge-${stateKind}"><span>${state==='connected'?'✓':state==='error'?'!':'—'}</span><span>${stateText}</span></span></td><td><span class="badge ${visible?'badge-success':'badge-neutral'}"><span>${visible?'✓':'—'}</span><span>${visible?'Показываются':'Скрыты'}</span></span></td><td class="table-switch"><label class="switch-label"><input type="checkbox" class="switch-input" data-provider-toggle="${key}" ${visible?'checked':''}><span>${visible?'Показывать':'Скрывать'}</span></label></td></tr>`;
    }).join('');
    body.querySelectorAll('[data-provider-toggle]').forEach(input=>input.addEventListener('change',async e=>{const key=e.target.dataset.providerToggle;await send('visibility',{provider:key,value:e.target.checked});ctx.state.visible[key]=e.target.checked;renderProviders(ctx);statusSummary(ctx);}));
    body.querySelectorAll('[data-provider-row]').forEach(row=>row.addEventListener('click',e=>{if(e.target.closest('input'))return;const key=row.dataset.providerRow;el('archive-filter-provider').value=providerNames[key];showScreen('accounts');renderArchive();}));
  }
  async function loadArchive(ctx){
    if(!local.archive.length){try{const rows=await send('archive_inventory');if(Array.isArray(rows))local.archive=rows;}catch{} }
    renderArchive();
  }
  function renderArchive(){
    const body=el('archive-table-body'); if(!body)return;
    const query=(el('archive-search')?.value||'').trim().toLowerCase(); const provider=el('archive-filter-provider')?.value||'all'; const status=el('archive-filter-status')?.value||'all'; const tier=el('archive-filter-tier')?.value||'all';
    let rows=local.archive.filter(row=>{const name=providerNames[row.provider]||row.provider;const text=`${row.email||''} ${name} ${row.area||''} ${row.label||''}`.toLowerCase();return(!query||text.includes(query))&&(provider==='all'||name===provider)&&(status==='all'||(row.status||'active')===status)&&(tier==='all'||(row.area||'')===tier);});
    const sort=el('archive-sort')?.value||'provider'; rows.sort((a,b)=>sort==='status'?String(a.status||'').localeCompare(String(b.status||'')):String(a.provider||'').localeCompare(String(b.provider||''))||String(a.email||'').localeCompare(String(b.email||'')));
    const selectedCount=rows.filter(r=>local.selected.has(r.id)).length; const counter=el('archive-visible-counter'); if(counter)counter.textContent=`Показано записей: ${rows.length} · Выбрано: ${selectedCount}`;
    const all=el('archive-select-all'); if(all){all.checked=!!rows.length&&rows.every(r=>local.selected.has(r.id));all.indeterminate=selectedCount>0&&selectedCount<rows.length;}
    body.innerHTML=rows.length?rows.map(row=>{const name=providerNames[row.provider]||row.provider;const state=row.status|| (row.disabled?'expired':'active');const stateText=state==='active'?'Активен':state==='expired'?'Сессия истекла':state==='error'?'Ошибка доступа':'Не проверено';return `<tr><td><input type="checkbox" data-archive-id="${escapeHtml(row.id)}" ${local.selected.has(row.id)?'checked':''}></td><td><div class="table-primary"><strong>${escapeHtml(local.reveal?row.email:mask(row.email||row.id))}</strong><small>${escapeHtml(row.label||'Без пользовательской метки')}</small></div></td><td>${escapeHtml(name)}</td><td>${escapeHtml(row.area||'—')}</td><td><span class="badge badge-${state==='active'?'success':state==='error'?'error':'warn'}"><span>${state==='active'?'✓':state==='error'?'!':'↻'}</span><span>${stateText}</span></span></td><td><button type="button" class="btn btn-sm btn-ghost" data-archive-reveal="${escapeHtml(row.id)}">${local.reveal?'Скрыть':'Показать'}</button></td></tr>`;}).join(''):`<tr><td colspan="6" class="empty-state">Нет аккаунтов по выбранным условиям.</td></tr>`;
    body.querySelectorAll('[data-archive-id]').forEach(cb=>cb.addEventListener('change',e=>{const id=e.target.dataset.archiveId;if(e.target.checked)local.selected.add(id);else local.selected.delete(id);renderArchive();}));
    body.querySelectorAll('[data-archive-reveal]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();local.reveal=!local.reveal;renderArchive();}));
  }
  async function exportArchive(){const ids=[...local.selected];if(!ids.length){modal('Экспорт архива','Выберите хотя бы один аккаунт.','<button class="btn btn-primary" data-modal-close>Понятно</button>');return;}const password=window.prompt('Пароль для зашифрованного архива:');if(!password)return;try{const result=await window.omni.archiveExport({ids,password});modal('Архив экспортирован',`Экспортировано аккаунтов: <strong>${result?.accounts||ids.length}</strong>.`,'<button class="btn btn-primary" data-modal-close>Закрыть</button>');}catch(error){modal('Ошибка экспорта',escapeHtml(error.message||'Не удалось экспортировать архив.'),'<button class="btn btn-primary" data-modal-close>Закрыть</button>');}}
  async function importArchive(){const password=window.prompt('Пароль архива:');if(!password)return;try{const result=await window.omni.archiveImport(password);local.archive=[];await loadArchive(ctxRef);modal('Импорт завершён',`Импортировано: <strong>${result?.imported?.length||0}</strong><br>Пропущено: <strong>${result?.skipped?.length||0}</strong><br>Ошибок: <strong>${result?.failed?.length||0}</strong>`,'<button class="btn btn-primary" data-modal-close>Закрыть</button>');}catch(error){modal('Ошибка импорта',escapeHtml(error.message||'Не удалось импортировать архив.'),'<button class="btn btn-primary" data-modal-close>Закрыть</button>');}}

  function setRemoteStep(ctx, verified){
    ['rem-step-3','rem-step-4'].forEach(id=>el(id)?.classList.toggle('locked-step',!verified));
    const remote=el('radio-route-remote'); if(remote)remote.disabled=!verified;
    const confirm=el('deploy-confirm-check'); if(confirm)confirm.disabled=!verified;
    const deploy=el('btn-deploy-server'); if(deploy)deploy.disabled=!verified||!confirm?.checked;
    const route=el('rem-route-state-text'); if(route)route.textContent=ctx.state.backendMode==='remote'?'Удалённый маршрут активен':verified?'Удалённый сервер проверен':'Локальный маршрут готов (активен)';
  }
  function bindRemote(ctx){
    const cfg=ctx.state.remoteServerConfig||{}; if(el('ssh-host'))el('ssh-host').value=cfg.host||ctx.state.remoteServer?.host||''; if(el('ssh-port'))el('ssh-port').value=cfg.port||22; if(el('ssh-user'))el('ssh-user').value=cfg.user||''; if(el('ssh-fido-toggle')){el('ssh-fido-toggle').checked=!!cfg.use_fido;el('ssh-fido-status').textContent=cfg.use_fido?'Включено':'Выключено';}
    local.keyPath=cfg.key_path||''; if(el('route-remote-host-label'))el('route-remote-host-label').textContent=cfg.host||'сервер не настроен'; if(el('ssh-key-details'))el('ssh-key-details').textContent=local.keyPath?`Файл: ${local.keyPath}`:'Файл ключа не выбран';
    ['ssh-host','ssh-port','ssh-user'].forEach(id=>el(id)?.addEventListener('change',()=>send('remote_server_save',{config:routeConfig(ctx)})));
    el('ssh-fido-toggle')?.addEventListener('change',e=>{el('ssh-fido-status').textContent=e.target.checked?'Включено':'Выключено';send('remote_server_save',{config:routeConfig(ctx)});});
    el('btn-pick-ssh-key')?.addEventListener('click',async()=>{const path=await window.omni.pickKeyFile();if(path){local.keyPath=path;el('ssh-key-details').textContent=`Файл: ${path}`;await send('remote_server_save',{config:routeConfig(ctx)});}});
    el('btn-clear-ssh-key')?.addEventListener('click',async()=>{local.keyPath='';el('ssh-key-details').textContent='Файл ключа не выбран';await send('remote_server_save',{config:routeConfig(ctx)});});
    el('btn-test-ssh')?.addEventListener('click',async()=>{const badge=el('rem-verify-badge'),text=el('rem-verify-badge-text'),box=el('rem-verify-result-box');setBadge(badge,'pending','Проверка…');try{const result=await send('remote_server_test',{config:routeConfig(ctx)});if(!result?.connected)throw new Error(result?.error||'Сервер не ответил');setBadge(badge,'success','Подключение проверено');box.style.display='block';box.className='info-callout success';box.innerHTML=`<strong>Узел подтверждён:</strong> ${escapeHtml(result.os||'ОС не определена')} · пользователь ${escapeHtml(result.user||routeConfig(ctx).user)}.`;ctx.state.remoteBackendStatus={mode:'local',connected:true,gateway:result.gateway,model_count:result.model_count,latency_ms:result.latency_ms,checked_at:new Date().toISOString()};setRemoteStep(ctx,true);}catch(error){setBadge(badge,'error','Ошибка проверки');box.style.display='block';box.className='info-callout error';box.textContent=error.message||'Не удалось проверить SSH.';setRemoteStep(ctx,false);}});
    document.querySelectorAll('input[name="omni-route"]').forEach(radio=>radio.addEventListener('change',()=>{el('btn-apply-route').disabled=radio.value==='remote'&&!ctx.state.remoteBackendStatus?.connected;}));
    el('btn-apply-route')?.addEventListener('click',async()=>{const mode=document.querySelector('input[name="omni-route"]:checked')?.value||'local';const feedback=el('route-switch-feedback');if(feedback)feedback.textContent='Переключение…';try{const result=await send('remote_server_switch',{mode});if(!result?.connected)throw new Error(result?.error||'Маршрут не проверен');ctx.state.backendMode=mode;ctx.state.remoteBackendStatus=result;if(feedback)feedback.textContent=mode==='remote'?'Удалённый маршрут активен':'Локальный маршрут активен';statusSummary(ctx);}catch(error){if(feedback)feedback.textContent=error.message||'Не удалось переключить маршрут.';}});
    el('deploy-confirm-check')?.addEventListener('change',e=>{const b=el('btn-deploy-server');if(b)b.disabled=!e.target.checked||el('rem-step-4')?.classList.contains('locked-step');});
    el('btn-deploy-server')?.addEventListener('click',async()=>{if(!window.confirm('Перенести зашифрованные данные аккаунтов на проверенный сервер?'))return;const area=el('deploy-progress-area');if(area)area.style.display='flex';try{const result=await send('remote_server_deploy',{config:routeConfig(ctx)});setBadge(el('rem-deploy-badge'),'success','Данные перенесены');el('deploy-progress-step').textContent=result?.message||'Перенос завершён';el('deploy-progress-pct').textContent='100%';el('deploy-progress-bar').style.width='100%';}catch(error){setBadge(el('rem-deploy-badge'),'error','Ошибка переноса');el('deploy-progress-step').textContent=error.message||'Перенос не выполнен';}});
    setRemoteStep(ctx,!!ctx.state.remoteBackendStatus?.connected&&!!ctx.state.remoteServer?.host);
  }
  function bindNotifications(ctx){
    const tg=ctx.state.telegram||{};
    const tokenBadge=el('tg-token-badge');
    if(tokenBadge)setBadge(tokenBadge,tg.tokenSaved?'success':'neutral',tg.tokenSaved?'Токен сохранён локально':'Токен не сохранён');
    if(el('tg-token-saved-time'))el('tg-token-saved-time').textContent=tg.tokenSaved?'Последнее сохранение: ранее на этом устройстве':'Последнее сохранение: нет данных';
    if(el('tg-manual-chat-id'))el('tg-manual-chat-id').value=tg.chatId||'';
    if(el('tg-selected-chat-details'))el('tg-selected-chat-details').textContent=tg.chatId?`Выбранный получатель: чат с ID ${tg.chatId}. Права записи будут проверены при поиске.`:'Чат не выбран. Нажмите «Найти чаты» после сохранения токена.';
    if(el('tg-test-target-label'))el('tg-test-target-label').textContent=tg.chatId?`Чат с ID ${tg.chatId}`:'Чат не выбран';
    const enabled=el('tg-enable-toggle');if(enabled){enabled.checked=!!tg.enabled;const update=()=>{el('tg-enable-label').textContent=enabled.checked?'Оповещения включены':'Оповещения отключены';document.querySelectorAll('.tg-dependent-step').forEach(step=>step.classList.toggle('locked-step',!enabled.checked));};enabled.addEventListener('change',async()=>{update();await send('telegram_preferences',{enabled:enabled.checked,chatId:el('tg-manual-chat-id')?.value||tg.chatId||''});});update();}
    el('tg-token-input')?.addEventListener('input',()=>{const badge=el('tg-token-badge');if(badge)setBadge(badge,'neutral','Есть несохранённые изменения');});
    el('btn-tg-toggle-token')?.addEventListener('click',e=>{const input=el('tg-token-input');input.type=input.type==='password'?'text':'password';e.target.textContent=input.type==='password'?'Показать':'Скрыть';});
    el('btn-tg-clear-token')?.addEventListener('click',()=>{el('tg-token-input').value='';setBadge(el('tg-token-badge'),'neutral','Токен очищен из формы');});
    el('btn-tg-save-token')?.addEventListener('click',async()=>{const token=el('tg-token-input').value.trim();if(!token){setBadge(el('tg-token-badge'),'error','Введите токен бота');return;}try{await send('telegram_token',{token});setBadge(el('tg-token-badge'),'success','Токен сохранён локально');el('tg-token-saved-time').textContent='Последнее сохранение: только что';el('tg-token-input').value='';}catch(error){setBadge(el('tg-token-badge'),'error',error.message||'Не удалось сохранить токен');}});
    el('btn-tg-find-chats')?.addEventListener('click',async()=>{try{const chat=await send('telegram_find');if(el('tg-manual-chat-id'))el('tg-manual-chat-id').value=chat||'';setBadge(el('tg-test-result-badge'),'success','Чат найден');}catch(error){setBadge(el('tg-test-result-badge'),'error',error.message||'Чат не найден');}});
    el('tg-manual-chat-id')?.addEventListener('change',()=>{const chatId=el('tg-manual-chat-id').value.trim();if(el('tg-selected-chat-details'))el('tg-selected-chat-details').textContent=chatId?`Выбранный получатель: чат с ID ${chatId}. Права записи будут проверены при поиске.`:'Чат не выбран';if(el('tg-test-target-label'))el('tg-test-target-label').textContent=chatId?`Чат с ID ${chatId}`:'Чат не выбран';return send('telegram_preferences',{enabled:!!enabled?.checked,chatId});});
    el('btn-tg-send-test')?.addEventListener('click',async()=>{try{await send('telegram_test');setBadge(el('tg-test-result-badge'),'success','Тестовое сообщение отправлено');}catch(error){setBadge(el('tg-test-result-badge'),'error',error.message||'Ошибка доставки');}});
  }
  async function loadConnections(ctx){
    const body=el('connections-table-body');if(!body)return;body.innerHTML='<tr><td colspan="6" class="empty-state">Проверка подключений…</td></tr>';try{const rows=await send('connections');if(Array.isArray(rows))local.clients=rows;}catch{local.clients=[];}renderConnections();
  }
  function renderConnections(){const body=el('connections-table-body');if(!body)return;const rows=local.clients;const applied=rows.filter(r=>r.connected&&r.status==='configured'&&!r.restartRequired).length;const restart=rows.filter(r=>r.restartRequired).length;const errors=rows.filter(r=>!r.connected||r.status==='check_failed').length;const summary=el('conn-summary-strip');if(summary)summary.textContent=`${applied} применено · ${restart} требует перезапуска · ${errors} ошибок`;body.innerHTML=rows.length?rows.map(row=>{const state=row.checking?'Проверяется':row.restartRequired?'Нужен перезапуск':row.connected&&row.status==='configured'?'Применено':row.connected?'Требует внимания':'Не подключено';const kind=row.checking?'pending':row.restartRequired?'warn':row.connected&&row.status==='configured'?'success':row.connected?'warn':'error';const action=row.restartRequired?`<button class="btn btn-sm btn-primary" data-client-restart="${escapeHtml(row.id)}">Перезапустить</button>`:!row.connected||row.status!=='configured'?`<button class="btn btn-sm btn-primary" data-client-apply="${escapeHtml(row.id)}">Применить настройки</button>`:`<button class="btn btn-sm" data-client-recheck="${escapeHtml(row.id)}">Проверить снова</button>`;return `<tr><td><strong>${escapeHtml(row.name)}</strong><small>${row.detected?'Приложение найдено':'Приложение не найдено'}</small></td><td>${row.detected?'Да':'Нет'}</td><td><span class="badge badge-${kind}"><span>${kind==='success'?'✓':kind==='warn'?'!':kind==='error'?'×':'…'}</span><span>${state}</span></span></td><td>${row.gatewayModelCount??'—'}</td><td>${row.restartRequired?'Изменены на диске':'Применены'}</td><td class="table-actions"><button class="btn btn-sm btn-ghost" data-client-details="${escapeHtml(row.id)}">Подробности</button>${action}</td></tr>`;}).join(''):'<tr><td colspan="6" class="empty-state">Поддерживаемые приложения не найдены.</td></tr>';
    body.querySelectorAll('[data-client-apply]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await send('connect',{client:b.dataset.clientApply});await loadConnections(ctxRef);}finally{b.disabled=false;}});
    body.querySelectorAll('[data-client-recheck]').forEach(b=>b.onclick=async()=>{b.disabled=true;await loadConnections(ctxRef);b.disabled=false;});
    body.querySelectorAll('[data-client-restart]').forEach(b=>b.onclick=async()=>{const row=rows.find(x=>x.id===b.dataset.clientRestart);if(!row||!window.confirm(`Перезапустить ${row.name}? Текущие задачи могут прерваться.`))return;b.disabled=true;try{await send('restart_client',{client:row.id,confirmed:true});await loadConnections(ctxRef);}finally{b.disabled=false;}});
    body.querySelectorAll('[data-client-details]').forEach(b=>b.onclick=()=>{const row=rows.find(x=>x.id===b.dataset.clientDetails);if(!row)return;const files=(row.files||[]).map(f=>`<li><strong>${escapeHtml(f.role||'Файл')}</strong><br><code>${escapeHtml(f.path||'')}</code></li>`).join('')||'<li>Нет данных о файлах.</li>';modal(`Подробности: ${row.name}`,`<h3>Файлы Omni</h3><ul>${files}</ul><h3>Модели</h3><p>${escapeHtml((row.configuredModels||[]).join(', ')||'Используется выбор модели приложения.')}</p>`, '<button class="btn btn-primary" data-modal-close>Закрыть</button>');});
  }

  function bind(ctx){
    document.querySelectorAll('.nav-btn').forEach(button=>button.addEventListener('click',()=>showScreen(button.dataset.screen)));
    document.querySelectorAll('[data-theme-choice]').forEach(button=>button.addEventListener('click',async()=>{const value=button.dataset.themeChoice;if(value==='system')return;await send('theme',{value});ctx.state.theme=value;applyTheme(ctx);renderAppearance(ctx);}));
    document.querySelectorAll('[data-lang-choice]').forEach(button=>button.addEventListener('click',async()=>{await send('language',{value:button.dataset.langChoice});ctx.state.language=button.dataset.langChoice;renderAppearance(ctx);}));
    el('btn-sync-accounts')?.addEventListener('click',()=>send('refresh'));
    el('btn-check-updates')?.addEventListener('click',()=>window.omni.open('https://github.com/nikitaeight24family/Omni/releases/latest'));
    el('archive-search')?.addEventListener('input',renderArchive);['archive-filter-provider','archive-filter-status','archive-filter-tier','archive-sort','archive-group-toggle'].forEach(id=>el(id)?.addEventListener('change',renderArchive));
    el('archive-select-all')?.addEventListener('change',e=>{const query=(el('archive-search')?.value||'').toLowerCase();local.archive.filter(r=>`${r.email||''} ${r.id||''}`.toLowerCase().includes(query)).forEach(r=>e.target.checked?local.selected.add(r.id):local.selected.delete(r.id));renderArchive();});
    el('btn-toggle-all-emails')?.addEventListener('click',()=>{local.reveal=!local.reveal;el('btn-toggle-all-emails').textContent=local.reveal?'Скрыть адреса':'Показать адреса';renderArchive();});
    el('btn-open-export')?.addEventListener('click',exportArchive);el('btn-open-import')?.addEventListener('click',importArchive);
    el('btn-check-all-clients')?.addEventListener('click',()=>loadConnections(ctx));el('btn-modal-close')?.addEventListener('click',closeModal);el('modal-backdrop')?.addEventListener('click',e=>{if(e.target.id==='modal-backdrop')closeModal();});
    document.addEventListener('click',e=>{if(e.target.closest('[data-modal-close]'))closeModal();});
    bindRemote(ctx);bindNotifications(ctx);showScreen(local.screen);
  }
  function applyTheme(ctx){const view=el('settings-view');if(!view)return;view.classList.toggle('theme-light',ctx.state.theme==='light');view.dataset.theme=ctx.state.theme;document.documentElement.dataset.theme=ctx.state.theme;}
  function renderAppearance(ctx){const version=window.omni.version||'—';const versionNode=document.querySelector('#screen-appearance .setting-row .font-mono');if(versionNode)versionNode.textContent=version;const sideVersion=document.querySelector('#sidebar-arch-label')?.previousElementSibling;if(sideVersion)sideVersion.textContent=`Omni Desktop v${version}`;document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-checked',b.dataset.themeChoice===ctx.state.theme?'true':'false'));document.querySelectorAll('[data-lang-choice]').forEach(b=>b.setAttribute('aria-checked',b.dataset.langChoice===ctx.state.language?'true':'false'));}
  window.renderOmniSettingsPrototype=function(ctx){ctxRef=ctx;const view=el('settings-view');if(!view)return;view.classList.add('settings-prototype');applyTheme(ctx);if(!local.initialized){el('settings-content').innerHTML=window.omniSettingsTemplate||'';local.initialized=true;el('demo-preset-select')?.closest('div')?.remove();el('btn-sim-update-err')?.remove();el('btn-sim-ssh-fail')?.remove();el('btn-sim-deploy-error')?.remove();el('tg-sim-outcome')?.closest('div')?.remove();bind(ctx);}statusSummary(ctx);renderAppearance(ctx);renderProviders(ctx);if(local.screen==='accounts')loadArchive(ctx);if(local.screen==='connections')renderConnections();};
})();
