"""Small Telegram Bot API client with locally encrypted bot-token storage."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from backend import AccountError, atomic_write, dpapi


class TelegramError(Exception):
    pass


class TelegramBot:
    def __init__(self, token_path):
        self.token_path = Path(token_path)

    def save_token(self, token):
        token = str(token or '').strip()
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise TelegramError('Enter a valid Telegram bot token.')
        atomic_write(self.token_path, dpapi(token.encode('utf-8')))

    def token_saved(self):
        return self.token_path.exists()

    def load_token(self):
        try:
            return dpapi(self.token_path.read_bytes(), decrypt=True).decode('utf-8')
        except FileNotFoundError:
            raise TelegramError('Save the bot token first.')
        except (AccountError, UnicodeError, OSError, ValueError) as error:
            raise TelegramError('Could not read the saved bot token.') from error

    def _request(self, method, payload=None):
        token = self.load_token()
        url = f'https://api.telegram.org/bot{token}/{method}'
        data = urllib.parse.urlencode(payload or {}).encode('utf-8') if payload is not None else None
        request = urllib.request.Request(url, data=data, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=8) as response:
                result = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            # Never forward the URL or exception text: Telegram embeds the secret in the URL path.
            raise TelegramError(f'Telegram request failed (HTTP {error.code}).') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise TelegramError('Could not reach Telegram. Check the internet connection.') from None
        except (UnicodeError, json.JSONDecodeError):
            raise TelegramError('Telegram returned an unreadable response.') from None
        if not isinstance(result, dict) or not result.get('ok'):
            description = result.get('description', '') if isinstance(result, dict) else ''
            if 'token' in str(description).lower() or 'unauthorized' in str(description).lower():
                raise TelegramError('Telegram rejected the bot token. Check it and save again.')
            raise TelegramError('Telegram could not complete the request.')
        return result.get('result')

    def discover_chat_id(self):
        updates = self._request('getUpdates') or []
        candidates = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            message = update.get('message') or update.get('edited_message') or update.get('channel_post') or {}
            chat = message.get('chat') if isinstance(message, dict) else None
            if isinstance(chat, dict) and chat.get('id') is not None:
                candidates.append((int(update.get('update_id') or 0), str(chat['id'])))
        if not candidates:
            raise TelegramError('Open the bot in Telegram and press Start, then try Find chat again.')
        return max(candidates)[1]

    def send_message(self, chat_id, text):
        chat_id = str(chat_id or '').strip()
        if not chat_id:
            raise TelegramError('Enter a chat ID or use Find chat.')
        self._request('sendMessage', {'chat_id': chat_id, 'text': str(text)[:4000]})
