const crypto = require('crypto');

function parseCredentialLine(line) {
  if (typeof line !== 'string' || line.length > 2048) throw new Error('Enter email | password | authenticator secret.');
  const emailMatch = line.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  const email = emailMatch?.[0];
  const withoutEmail = email ? line.replace(email, ' ') : '';
  const secretCandidates = withoutEmail.match(/[A-Z2-7][A-Z2-7\s=-]{15,}/gi) || [];
  const secretCandidate = secretCandidates.sort((a,b)=>b.length-a.length)[0]?.replace(/[\s=-]/g, '').toUpperCase();
  if (!email || !secretCandidate) throw new Error('Enter email, password, and authenticator secret.');
  const password = withoutEmail.replace(secretCandidates.sort((a,b)=>b.length-a.length)[0] || '', ' ').replace(/(?:^|[|,:;\n\t])\s*(?:email|e-mail|почта|password|пароль|secret|секрет|authenticator|аутентификатор)\s*[:=]?/gi, ' ').replace(/[|,:;\n\t]+/g, ' ').trim();
  if (!password || password.length > 1024) {
    throw new Error('Enter email | password | authenticator secret.');
  }
  const secret = secretCandidate;
  decodeBase32(secret);
  return { email, password, secret };
}

function decodeBase32(value) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let buffer = 0, bits = 0;
  const bytes = [];
  for (const char of value) {
    const digit = alphabet.indexOf(char);
    if (digit < 0) throw new Error('Authenticator secret must be Base32.');
    buffer = (buffer << 5) | digit;
    bits += 5;
    if (bits >= 8) { bits -= 8; bytes.push((buffer >> bits) & 255); }
  }
  if (bytes.length < 10 || bits >= 5) throw new Error('Authenticator secret must be Base32.');
  return Buffer.from(bytes);
}

function totp(secret, now = Date.now()) {
  const counter = BigInt(Math.floor(now / 30000));
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(counter);
  const digest = crypto.createHmac('sha1', decodeBase32(secret)).update(message).digest();
  const offset = digest[digest.length - 1] & 15;
  const value = ((digest[offset] & 127) << 24) | (digest[offset + 1] << 16) |
    (digest[offset + 2] << 8) | digest[offset + 3];
  return String(value % 1000000).padStart(6, '0');
}

function pageAutomationScript(credentials, code, mfaSubmitted = false, targetArea = '', targetAccountId = '') {
  return String.raw`(() => {
    const host = location.hostname.toLowerCase();
    if (!['auth.openai.com','login.openai.com','login.microsoftonline.com','login.live.com','chatgpt.com','www.chatgpt.com'].includes(host)) return { status: 'waiting' };
    const visible = node => !!node && !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    const first = selectors => selectors.map(selector => document.querySelector(selector)).find(visible);
    const setValue = (node, value) => {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), 'value')?.set;
      if (setter) setter.call(node, value); else node.value = value;
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const submit = node => {
      window.__omniAuthSubmitted ||= new WeakSet();
      if (window.__omniAuthSubmitted.has(node)) return false;
      const form = node.closest('form');
      const label = item => (item.innerText || item.textContent || item.value || item.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
      const blocked = item => /passkey|security key|use (another|a different) device|ключ безоп|ключ доступа|устройство iphone|ipad|android|webAuthn|webauthn/i.test(label(item));
      const submitLabels = /^(continue|next|sign in|log in|submit|продолжить|далее|войти|отправить|weiter|fortfahren|continuer|suivant|続行|次へ|继续|下一步|계속)$/i;
      const formButtons = form ? [...form.querySelectorAll('button,input[type="submit"],#idSIButton9')].filter(item => visible(item) && !blocked(item)) : [];
      const button = formButtons.find(item => submitLabels.test(label(item))) ||
        [...document.querySelectorAll('button,input[type="submit"]')].find(item => visible(item) && !blocked(item) && /continue|next|sign in|log in|продолж|далее|войти/i.test(label(item)));
      if (button && !button.disabled) { window.__omniAuthSubmitted.add(node); button.click(); return true; }
      if (form?.requestSubmit && ![...form.querySelectorAll('button,input[type="submit"]')].some(blocked)) { window.__omniAuthSubmitted.add(node); form.requestSubmit(); return true; }
      return false;
    };
    const submitted = node => !!window.__omniAuthSubmitted?.has(node);
    const email = first(['input[type="email"]','input[autocomplete="username"]','input[name="email"]','input[name="username"]','#i0116']);
    if (email && !submitted(email)) { if (email.value !== ${JSON.stringify(credentials.email)}) setValue(email, ${JSON.stringify(credentials.email)}); return { status: submit(email) ? 'submitted-email' : 'filled-email' }; }
    const password = first(['input[type="password"]','input[autocomplete="current-password"]','input[name="password"]','#i0118']);
    if (password && !submitted(password)) { if (password.value !== ${JSON.stringify(credentials.password)}) setValue(password, ${JSON.stringify(credentials.password)}); return { status: submit(password) ? 'submitted-password' : 'filled-password' }; }
    const otp = first(['input[autocomplete="one-time-code"]','input[name="code"]','input[inputmode="numeric"]','input[name*="totp" i]','#idTxtBx_SAOTCC_OTC']);
    if (otp && !submitted(otp)) { if (otp.value !== ${JSON.stringify(code)}) setValue(otp, ${JSON.stringify(code)}); const sent = submit(otp); if (sent) window.__omniMfaSubmitted = true; return { status: sent ? 'submitted-code' : 'filled-code' }; }
    const pageText = document.body?.innerText || document.body?.textContent || '';
    const alert = [...document.querySelectorAll('[role="alert"],.error,[class*="error" i]')].find(node => visible(node) && (node.innerText || node.textContent || '').trim());
    if (alert) return { status: 'rejected' };
    const hasWorkspaceControls = !!document.querySelector('input[name="workspace_id"],input[data-login-web-auth-control][type="radio"]');
    const workspaceChooser = hasWorkspaceControls || (/workspace|organization|team|рабоч(?:ая|ие)\s+област|организац|команд/i.test(pageText) && /choose|select|pick|continue|выберите|выбор|продолж|далее/i.test(pageText));
    const actionLabel = node => (node.innerText || node.textContent || node.value || '').trim().replace(/\s+/g, ' ');
    const isNextAction = node => /^(continue|next|confirm|done|allow|authorize|accept|proceed|submit|продолжить|далее|подтвердить|готово|разрешить|принять|отправить|weiter|fortfahren|continuer|suivant|confirmer|aceptar|siguiente|продовжити|далі|підтвердити|続行|次へ|確認|继续|下一步|확인|계속)$/i.test(actionLabel(node));
    const nextAction = controls => {
      const enabled = controls.filter(node => visible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true');
      const submits = enabled.filter(node => node.matches('button[type="submit"],input[type="submit"],button:not([type])') && node.closest('form'));
      if (submits.length === 1) return submits[0];
      return enabled.find(isNextAction) || (enabled.length === 1 ? enabled[0] : null);
    };
    if (workspaceChooser) {
      const controls = [...document.querySelectorAll('button,[role="button"],label')].filter(visible);
      const targetArea = ${JSON.stringify(targetArea || '')};
      const targetAccountId = ${JSON.stringify(targetAccountId || '')};
      if (targetArea && !window.__omniTargetWorkspaceChosen) {
        const choices = [...document.querySelectorAll('input[type="radio"],input[type="checkbox"],[role="option"],label,button,[data-workspace],[data-organization]')].filter(visible);
        const area = targetArea.toLowerCase().replace(/[_-]/g, ' ');
        const matchesArea = text => {
          if (area === 'free' || /free|personal|личн|персональ|бесплат/i.test(area)) return /personal|free|личн|персональ|бесплат/i.test(text);
          if (area === 'k12' || area === 'edu' || /education|school|student|учеб|образован/i.test(area)) return /edu|education|school|student|учеб|образован|школ/i.test(text);
          return text.toLowerCase().includes(area);
        };
        const targetInput = choices.find(node => targetAccountId && node.matches('input[type="radio"],input[type="checkbox"]') && String(node.value||'')===String(targetAccountId));
        const target = targetInput || choices.filter(node => !node.matches('button,[role="button"]')).find(node => {
          let parent=node, text=node.closest?.('label')?.textContent||'';
          for(let i=0;i<2&&parent&&!node.closest?.('label');i++,parent=parent.parentElement) text+=' '+(parent.innerText||parent.textContent||'');
          text+=' '+(node.value||'');
          return matchesArea(text.trim());
        });
        if (!target) return {status:'target-workspace-unavailable'};
        target.click();window.__omniTargetWorkspaceChosen=true;
        return {status:'selected-target-workspace'};
      }
      if (targetArea && window.__omniTargetWorkspaceChosen) {
        const next=nextAction(controls);
        if(next&&!window.__omniWorkspaceContinue){window.__omniWorkspaceContinue=true;next.click();}
        return {status:'selected-target-workspace'};
      }
      const allChoice = controls.find(node => /all (workspaces|organizations|teams)|every workspace|все рабочие области|все организации|tous les espaces|alle arbeitsbereiche|todas las áreas/i.test(actionLabel(node)));
      if (allChoice) {
        if (!window.__omniAllWorkspacesChosen) { window.__omniAllWorkspacesChosen = true; allChoice.click(); return { status: 'selected-all-workspaces' }; }
        const next = nextAction(controls);
        if (next && !window.__omniWorkspaceContinue) { window.__omniWorkspaceContinue = true; next.click(); }
        return { status: 'selected-all-workspaces' };
      }
      const boxes = [...document.querySelectorAll('input[type="checkbox"],[role="checkbox"]')].filter(visible);
      if (boxes.length > 0) {
        for (const box of boxes) {
          const checked = box.checked === true || box.getAttribute('aria-checked') === 'true';
          if (!checked) box.click();
        }
        const next = nextAction(controls);
        if (next && !window.__omniWorkspaceContinue) { window.__omniWorkspaceContinue = true; next.click(); }
        return { status: 'selected-all-workspaces' };
      }
      const options = [...document.querySelectorAll('[role="option"],[data-workspace],[data-organization],[data-team]')].filter(visible);
      if (options.length > 0) {
        for (const option of options) {
          if (option.getAttribute('aria-selected') !== 'true' && !option.classList.contains('selected')) option.click();
        }
        const next = nextAction(controls);
        if (next && !next.disabled && !window.__omniWorkspaceContinue) { window.__omniWorkspaceContinue = true; next.click(); }
        return { status: 'selected-all-workspaces' };
      }
      const radios = [...document.querySelectorAll('input[type="radio"],[role="radio"]')].filter(visible);
      if (radios.length > 1) return { status: 'single-workspace-picker' };
      if (radios.length === 1) {
        if (!radios[0].checked && radios[0].getAttribute('aria-checked') !== 'true') radios[0].click();
        const next = nextAction(controls);
        if (next && !next.disabled && !window.__omniWorkspaceContinue) { window.__omniWorkspaceContinue = true; next.click(); }
        return { status: 'selected-all-workspaces' };
      }
    }
    // OAuth may require a final confirmation after MFA; it has no credential input.
    // Restrict this to the Codex consent screen for the login Omni started.
    const codexConsent = /codex/i.test(pageText) && /consent|sign in (?:with|to)|continue to|authorize|allow access/i.test(pageText);
    const postMfaConfirmation = (${JSON.stringify(Boolean(mfaSubmitted))} || window.__omniMfaSubmitted) && ![email,password,otp].some(visible);
    if ((codexConsent || postMfaConfirmation) && ![email,password,otp].some(visible)) {
      const candidates = [...document.querySelectorAll('button,input[type="submit"],[role="button"]')].filter(node => visible(node) && !node.disabled);
      const next = nextAction(candidates);
      if (next) {
        window.__omniAuthSubmitted ||= new WeakSet();
        if (!window.__omniAuthSubmitted.has(next)) { window.__omniAuthSubmitted.add(next); next.click(); return { status: 'submitted-consent' }; }
        return { status: 'waiting-consent' };
      }
    }
    if (document.querySelector('iframe[src*="captcha" i],[data-sitekey],input[name*="captcha" i]') || /captcha|verify you are human|security challenge/i.test(document.body?.innerText || '')) return { status: 'verification' };
    // Only categorical diagnostics leave the page. Never return page text or field values.
    return { status: 'waiting', diagnostics: {
      email: !!email, password: !!password, otp: !!otp,
      workspace: workspaceChooser, consent: codexConsent, postMfa: !!postMfaConfirmation,
      buttons: [...document.querySelectorAll('button,input[type="submit"]')].filter(visible).length,
      buttonLabels: [...document.querySelectorAll('button,input[type="submit"]')].filter(visible).map(node => (node.innerText || node.textContent || node.value || '').trim().replace(/\s+/g, ' ').slice(0, 40)).filter(Boolean).slice(0, 6)
    } };
  })()`;
}

module.exports = { parseCredentialLine, decodeBase32, totp, pageAutomationScript };
