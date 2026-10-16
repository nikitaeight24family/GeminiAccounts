# Settings inventory and Google AI Studio design prompt

## Current settings inventory

### Global shell

- The settings view opens from the gear button in the main Omni window.
- The left navigation contains Appearance, Accounts, Remote server, Connections, and Notifications.
- A system summary shows the current routing state: local route ready or remote route active.
- The same summary shows provider account counts.
- Preferences are saved immediately when a control changes.
- The interface supports English and Russian and dark and light themes.

### Appearance

- Theme: Dark or Light. The theme is applied immediately.
- Language: English or Russian. The language is applied immediately.
- Current version: displays the installed Omni version.
- Sync accounts: refreshes the account data shown by Omni.
- Check for updates: currently opens the latest Omni release page. The design should make the result and last check time explicit.

### Accounts and providers

The provider list controls visibility in the main account view; hiding a provider does not disconnect its accounts.

- Antigravity: visibility switch and connected-account count.
- OpenAI: visibility switch and connected-account count.
- Claude: visibility switch and connected-account count.
- Grok: visibility switch and connected-account count.
- TokenHarbor: visibility switch and connected-account count.
- Each provider can show Visible, Hidden, or no connected accounts.
- A provider row should make it clear that the switch changes display visibility, not authentication or model access.

### Account archive

- The archive contains account files and automatic sign-in data and must be treated as sensitive.
- Accounts are grouped by provider or archive area.
- Search filters the archive list.
- Select all selects the currently visible search results.
- A selected-account counter shows how many records are selected.
- Email addresses are displayed in masked form in the list.
- Export archive exports the selected records after a password confirmation.
- Import archive asks for the archive password and reports imported and skipped records.
- Empty states include no portable accounts and no accounts found.
- The design should explain whether import merges, replaces, or skips existing records before the user confirms.

### Remote server

The remote flow is a four-step sequence: Connect, Verify, Choose route, Deploy.

#### Connect

- Host / IP address.
- SSH port, default 22.
- SSH username.
- SSH password, optional when a key is used.
- SSH private key file, optional.
- Browse button opens a native key-file picker.
- Supported key hint: RSA and Ed25519.
- FIDO / Security Key switch, off by default. It uses Windows Hello or a hardware FIDO key and may require a touch.
- Host validation rejects an empty host and spaces.
- Port validation accepts only an integer from 1 to 65535.
- Username validation rejects an empty value.
- SSH values are saved as they change.

#### Verify

- Test connection is the primary action.
- The check must happen before routing can be changed.
- Success should show the remote operating system and authenticated user.
- Failure should appear beside the relevant field or as a clear connection error.
- A successful gateway catalog check can show gateway address, model count, latency, and last checked time.

#### Choose route

- Local backend (127.0.0.1).
- Remote server route.
- The remote option is disabled until the server and gateway have been verified.
- Switching a route is an explicit operation with a visible loading state and result.
- The UI must distinguish local route ready, remote route verified, remote route active, and remote route not verified.

#### Deploy

- Copy Omni backend and account data to the verified server.
- The operation requires confirmation because it transfers sensitive account data.
- The confirmation should state what is copied, where it is stored, whether it is encrypted in transit, what files are changed, whether a backup exists, and how failure is handled.
- Deployment has progress, success, and error states.
- Deployment does not change the active route until the user chooses a route.

#### Client connection instructions

- An expandable instruction area appears after a remote server is configured.
- Claude Code CLI has PowerShell and Bash commands plus restore commands.
- Codex Desktop has PowerShell and Bash commands plus restore commands.
- Codex CLI has PowerShell and Bash commands plus restore commands.
- Claude Desktop has a JSON configuration snippet.
- Copy buttons must confirm that the command or JSON was copied.
- The design should explain what each snippet changes and avoid forcing users to read a large nested terminal panel.

#### Remote help

- A help dialog explains why to use a remote backend: continuous uptime, fewer local disconnects, multi-device access, and lower local resource use.
- It also explains automated SSH deployment, daemon installation, account migration, firewall isolation, and route switching.

### Connections and diagnostics

Supported clients are Codex, Claude Desktop, and Claude Code CLI.

- Summary counts: ready and needs attention.
- Check all reruns diagnostics for every supported client.
- Each row shows application name, whether it was found, connection status, model count, and actions.
- Statuses are Checking, Applied, Restart needed, Needs attention, and Not connected.
- Diagnostic details can show files managed by Omni, file existence, settings written, and models selected in the application.
- Actions are Apply settings, Restart, Check again, and Details.
- Restart requires confirmation and warns that running tasks may be interrupted while saved sessions remain preserved.
- A model availability warning lists configured models that are not available.
- The design must distinguish configuration verified, settings changed, settings applied, and application restart required.

### Notifications

Telegram notifications use a four-step flow.

- Enable account alerts switch.
- Event description currently covers quota exhaustion, sign-outs, and connection failures.
- Bot token password field.
- Save bot token action.
- Token status: saved or not saved. The token is stored locally.
- Chat ID field.
- Find chat action, which should explain how chats are discovered and what bot permissions are required.
- Send test notification action.
- Test result should appear beside the action and identify success or the exact failure: invalid token, bot not found, no chat access, or delivery failure.
- The design should add show/hide token, clear token, selected-chat details, event selection, and quiet-hours controls if they fit the product scope.
- Disabling alerts should visibly disable dependent Telegram steps while preserving their values.

## Prompt for Google AI Studio

```text
You are a senior product designer and frontend engineer. Design a production-ready settings experience for a desktop Electron application called Omni. Omni manages AI provider accounts, routing, a local or remote backend, Telegram alerts, and connections to Codex and Claude clients.

The current interface is a dark admin panel made of large cards. Redesign the information architecture and interaction model so a user can scan the system state in seconds, understand consequences before acting, and complete the next action without reading a technical log.

Deliver a polished, self-contained desktop settings prototype in one HTML file with embedded CSS and JavaScript. Do not use external assets or network requests. The prototype must be usable at 100%, 125%, 150%, and 200% zoom, and it must remain usable at a 760px-wide window. Use semantic HTML, keyboard navigation, visible focus rings, accessible labels, and status text in addition to color. If you use icons, use simple inline SVG with consistent stroke weight.

Product context:

- Product name: Omni.
- Target platform: Windows desktop Electron application.
- Default locale: Russian. Include an English locale toggle, but write the visible sample content in Russian first.
- Support dark and light themes.
- The settings window must feel compact, calm, and trustworthy. Avoid oversized cards, decorative gradients, excessive borders, and empty space.
- Use a five-level type scale: page title, section title, body, supporting text, and status/meta text.
- Use a clear semantic state system: success, warning, error, pending, disabled, requires action, and not checked. Every state needs text or an icon; never rely on color alone.
- Use one primary action per screen. Secondary actions must be visually subordinate. Destructive or sensitive actions require a preview and confirmation.

Global shell:

- Use a compact sticky left navigation with grouped sections: Appearance; Accounts and providers; Remote server; Notifications; Connections and diagnostics.
- The active section must have strong contrast and a clear icon/label treatment.
- Keep the page title compact. Do not repeat “Settings” as a page title, eyebrow, and navigation heading.
- Add a single global status strip below the header. It should state a useful summary such as: “Система: локальный маршрут активен · 3 провайдера · 2 подключения применены · 1 требует перезапуска”. Make each count unambiguous.
- Show “Изменения сохраняются автоматически” once in the header or footer, not as its own navigation group.
- Keep the content column readable, with a maximum width around 960px and responsive full-width behavior on smaller windows.

Screen 1 — Appearance:

- Present Theme and Language as compact setting rows with a clear value and supporting text.
- Theme values: Тёмная, Светлая, Системная. State that the choice applies immediately.
- Language values: Русский, English. State that the choice applies immediately.
- Add an Application section containing the installed version, update channel, last update check time, and the result of the last check.
- Use the action label “Проверить обновления”, never “Последняя версия”. Show loading, success, and error results beside the action.
- Keep “Синхронизировать аккаунты” separate from update checking and make it secondary.

Screen 2 — Accounts and providers:

- Explain at the top that provider switches control visibility in the main account view; they do not disconnect accounts.
- Show a compact table/list with provider, account count, visibility state, connection state, and a clear visibility switch label.
- Providers: Antigravity, OpenAI, Claude, Grok, TokenHarbor.
- Include states for visible, hidden, connected but hidden, no accounts, expired session, unavailable provider, and provider error.
- Make provider rows clickable to open that provider’s accounts.
- Add an Account archive subsection with search, provider/status/subscription filters, sorting, grouping, multi-select, selected count, and a sticky bulk-action bar.
- Mask email addresses by default and provide an explicit reveal action.
- Use Russian labels: “Экспортировать выбранные”, “Импортировать архив”, “Выбрать все результаты”, “Выбрано: N”.
- Before export, explain format and that the archive contains sensitive sign-in data.
- Before import, show a preview and clearly state whether existing records are merged, replaced, or skipped. Report imported, skipped, and failed records after the operation.

Screen 3 — Remote server:

- Build a real progressive wizard with four steps: 1 Подключение, 2 Проверка, 3 Маршрут, 4 Перенос.
- Only the active step should be visually prominent. Future steps should be visibly locked until their prerequisite succeeds.
- Step 1 fields: host/IP, SSH port, SSH username, SSH password, private key file, native “Выбрать файл” action, and an optional FIDO/security-key method that is off by default.
- Do not prefill a real IP or root. Use neutral placeholders such as “server.example.com” and “Имя пользователя”.
- Explain authentication precedence: key, password, and FIDO. Show selected key filename, key type, fingerprint, and validation state when available.
- Validate each field inline. Show errors beside the exact field.
- Make “Проверить подключение” the primary action. Show checking, success, and failure states with server name, OS, user, latency, and last checked time.
- Step 3 must use a clearly labeled radio group, not tab-like controls: “Локальный маршрут” and “Удалённый сервер”. Disable the remote option until verification succeeds. Explain what changes immediately and what does not.
- Step 4 must use an action label such as “Перенести данные на проверенный сервер”. Add a preflight preview listing data, destination, estimated size, changed files, backup behavior, duration estimate, and rollback behavior. Require explicit confirmation. Include progress, cancel/failed, and completed states.
- Put client connection instructions in a separate expandable “Инструкция подключения” area. Let the user choose one client and one operating system before showing a command. Provide copy and download actions, and show a small explanation of the files changed by the command. Never show four giant shell blocks at once.
- Put technical deployment benefits in a secondary help dialog, not in the main flow.

Screen 4 — Notifications:

- Design this as a dependency-aware Telegram setup wizard.
- Step 1: enable alerts. When disabled, dependent fields are visibly disabled and the reason is stated.
- Step 2: bot token. Use a password field with show/hide, clear, save, local-storage explanation, last saved time, and token validation state.
- Step 3: chat selection. Explain that the bot must have permission to write. Provide “Найти чаты”, a list of discovered chats, selected chat details, and a manual chat ID fallback.
- Step 4: event selection. Include quota exhaustion, sign-outs, connection failures, and an expandable list for additional event types.
- Step 5: test message. Show the selected chat next to the button and report sent, invalid token, bot not found, no access, and delivery failed states in place.
- Use explicit Russian copy such as “Токен проверен”, “Бот не имеет доступа к чату”, and “Тестовое сообщение отправлено”.

Screen 5 — Connections and diagnostics:

- Start with a compact summary: “2 применено · 1 требует перезапуска · 0 ошибок”.
- Provide “Проверить все” as the primary diagnostic action and show the last checked time.
- Use a responsive table with columns: Приложение, Обнаружено, Подключение, Модели, Применение, Действия.
- Rows: Codex, Claude Desktop, Claude Code CLI.
- Separate these states in text: не проверено, проверяется, приложение не найдено, не подключено, проверено, настройки изменены, применено, требуется перезапуск, ошибка.
- Keep the actions in a fixed-width right column or an overflow menu so nothing is clipped. Actions: “Применить настройки”, “Перезапустить”, “Проверить снова”, “Подробности”.
- Details should open in a side panel, not expand a large nested card. Show managed files, settings written, selected models, last check time, and the reason a restart is needed.
- Restart confirmation must state which application restarts, that running tasks may be interrupted, and that saved sessions remain preserved.

Interaction and content rules:

- Do not use English fragments in Russian copy except product names, model IDs, file paths, and shell syntax.
- Do not use “бекенд”, “сток”, or vague labels such as “Последняя версия”, “Проверить всё”, or “Нужен перезапуск” without a reason.
- Prefer result-oriented labels: “Проверить обновления”, “Синхронизировать аккаунты”, “Проверить подключение”, “Применить настройки”, “Восстановить настройки по умолчанию”.
- Never show real IP addresses, root usernames, full emails, tokens, or private keys in sample data.
- Include realistic loading, empty, success, warning, and error examples for every screen.
- Make clear which actions are automatic, which are saved, which are verified, and which are applied only after a restart.
- The final result should look like a coherent product, not a set of independent cards.

Return:

1. The self-contained HTML/CSS/JS prototype.
2. A short design rationale explaining the hierarchy, state system, responsive behavior, and the main user flow.
3. A component/state inventory mapping each screen element to its loading, empty, success, warning, error, and disabled states.
4. Do not implement fake backend calls; use local mock state and clearly marked callbacks so the design can later be integrated into an existing Electron renderer.
```
