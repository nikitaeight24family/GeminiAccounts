<p align="center"><img src="assets/omni-icon.png" width="76" alt="Omni"></p>
<h1 align="center">Omni</h1>
<p align="center">Аккаунты AI, квоты, модели и подключения в одном приложении.</p>
<p align="center">
  <a href="https://github.com/nikitaeight24family/Omni/releases/tag/v1.6.1"><img src="https://img.shields.io/github/v/release/nikitaeight24family/Omni?label=release&color=739aff" alt="Release 1.6.1"></a>
  <a href="https://github.com/nikitaeight24family/Omni/actions/workflows/build.yml"><img src="https://github.com/nikitaeight24family/Omni/actions/workflows/build.yml/badge.svg" alt="Build and tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-66d7b0" alt="MIT license"></a>
</p>
<p align="center">
  <a href="https://github.com/nikitaeight24family/Omni/releases/download/v1.6.1/Omni-Setup.exe"><b>Скачать Omni 1.6.1 для Windows</b></a> ·
  <a href="https://github.com/nikitaeight24family/Omni/releases/tag/v1.6.1">Все файлы релиза</a> ·
  <a href="CLI.md">CLI</a>
</p>

Omni подключает Google Antigravity/Gemini, ChatGPT, Claude, Grok и TokenHarbor, показывает квоты и автоматически распределяет запросы через локальный gateway. Внешние клиенты — Codex, Claude Code, Claude Desktop и CLI — получают актуальный каталог доступных моделей.

Версия **1.6.1** — Electron-сборка для Windows. Python-приложение и CLI остаются в репозитории для macOS, Linux, Windows CLI и совместимости старых установок.

## Окна Omni

Главное окно с аккаунтами, квотами, моделями, активностью и автоматической маршрутизацией:

<p align="center"><img src="docs/omni-dashboard.png" width="1000" alt="Главное окно Omni"></p>

Настройки интерфейса, языков, сервисов, уведомлений и подключений:

<p align="center"><img src="docs/omni-settings.png" width="1000" alt="Настройки Omni"></p>

Отдельное окно автоматического входа: одна строка аккаунта, а области показаны отдельными карточками-ачивками. Данные входа можно показать, изменить карандашом или удалить крестиком; поддерживается вставка нескольких записей и пачки TXT-файлов.

<p align="center"><img src="docs/omni-auto-sign-in.png" width="1000" alt="Окно автоматического входа Omni"></p>

Скриншоты используют демонстрационные данные. Настоящие пароли, секреты 2FA, токены и история запросов в репозиторий не входят.

## Что нового в 1.6.1

- отдельное Electron-окно автоматического входа ChatGPT;
- таблица только аккаунтов, для которых сохранены данные автоматического входа;
- одна строка на аккаунт и отдельные области Free/EDU/K12 в виде статусов-ачивок;
- просмотр, редактирование и удаление зашифрованных данных входа;
- bulk-вставка и drag-and-drop нескольких `.txt` файлов;
- проблемные аккаунты исключаются из общего количества аккаунтов;
- сохранение выбранных областей и проверка квоты после входа;
- актуальная модель отображается на свернутой карточке;
- плавный Electron-скролл без поэлементной перерисовки;
- автоматическая синхронизация каталога моделей для Codex, Claude и CLI;
- обновлённые настройки и подключение приложений.

## Установка Windows

1. Скачайте [Omni-Setup.exe](https://github.com/nikitaeight24family/Omni/releases/download/v1.6.1/Omni-Setup.exe) из релиза **v1.6.1**.
2. Запустите установщик. Python и права администратора не нужны.
3. Откройте Omni и добавьте аккаунты через `+` у нужного провайдера.

Установщик сохраняет аккаунты и настройки при обновлении. Портативная сборка `Omni.exe` находится среди файлов релиза.

## Аккаунты и автоматический вход

Omni поддерживает:

- Google Antigravity/Gemini;
- ChatGPT/Codex с областями Free, EDU/K12 и другими доступными workspace;
- нативные Claude и Grok;
- TokenHarbor и API-ключи.

Для ChatGPT можно использовать обычный вход, отдельный браузер или **Sign in automatically**. Автоматический вход принимает строки с любыми распространёнными разделителями, несколько строк и `.txt` файлы. Данные хранятся зашифрованно через Windows `safeStorage`.

После входа Omni проверяет все области аккаунта, выбирает нужную область, сохраняет её идентификатор и проверяет реальную доступность квоты. Callback сам по себе не считается успешным входом.

## Квоты и маршрутизация

- 5h отображается выше 1w;
- квоты и сбросы обновляются в фоне;
- недоступные и проблемные аккаунты не учитываются в общем количестве;
- аккаунты одного провайдера распределяются между параллельными запросами;
- перегруженный маршрут получает повторную попытку через другой доступный аккаунт или модель;
- ручные приоритеты и минимальные границы квоты сохраняются;
- активный аккаунт показывает текущую модель и цветную подсветку.

## Подключение приложений

В разделе **Connect applications** Omni проверяет и обновляет конфигурации:

| Приложение | Что обновляется |
| --- | --- |
| Codex Desktop / CLI | локальный gateway, Responses API и каталог моделей |
| Claude Code CLI | gateway URL, ключ, модели и настройки CLI |
| Claude Desktop | Code-провайдер и доступные модели |

Каталог моделей регулярно сверяется с доступными аккаунтами. Устаревшие модели удаляются, новые добавляются автоматически. Исходные конфигурации сохраняются в резервную копию.

## CLI и другие ОС

CLI доступен для Windows, macOS и Linux. Скачать архивы можно на странице [релиза v1.6.1](https://github.com/nikitaeight24family/Omni/releases/tag/v1.6.1). Исходный запуск:

```sh
python console.py
python console.py status
python console.py models
python console.py configure --clients claude_cli codex
python console.py serve
```

Подробности: [CLI.md](CLI.md).

## Хранение и безопасность

Gateway и native service работают только локально (`127.0.0.1`). Публичные сборки не содержат аккаунтов, паролей, токенов, ключей и истории запросов. Windows использует DPAPI/safeStorage; macOS и Linux используют локальное шифрование и права пользователя.

Не публикуйте папки `auth`, `config.yaml`, `preferences.json`, `client-key.txt` и диагностические архивы с личными данными.

## Разработка

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests
cd electron
npm install
npm test
npm run pack -- --config.directories.output=dist-local
```

Electron-исходники находятся в `electron/`, Python backend — в корне, CLI — в `console.py`. Для новой публикации сначала выполните полный локальный набор тестов и соберите затронутую платформу.

## История

Проект ранее назывался **Gemini Accounts**. Старые имена исполняемых файлов и папки данных сохранены для совместимости существующих установок.

