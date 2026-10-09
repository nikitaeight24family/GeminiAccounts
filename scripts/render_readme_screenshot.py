"""Capture the actual compact UI with synthetic data for the public README."""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import customtkinter as ctk
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from backend import Controller


def bucket(window, remaining, hours):
    return {
        'window': window,
        'remaining': remaining,
        'reset': (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        with patch('app.Controller', lambda: Controller(proxy_dir=temporary / 'proxy', data_dir=temporary / 'data')), \
                patch.object(App, 'refresh'), patch.object(App, 'fetch_quota'), \
                patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'), \
                patch.object(App, 'poll_gateway_jobs'), patch.object(App, 'check_for_updates'):
            ctk.set_appearance_mode('dark')
            app = App()
            try:
                app.controller.preferences['details-collapsed'] = False
                accounts = [
                    {'name': f'demo-{index}', 'email': f'Demo account {index}', 'disabled': False,
                     'unavailable': False, 'access_issue': 'verification' if index == 0 else None}
                    for index in range(6)
                ]
                examples = [
                    ((None, None), (None, None)),
                    ((.92, .005), (.83, .34)),
                    ((.53, .64), (.71, .77)),
                    ((.31, .42), (.98, .008)),
                    ((.86, .92), (.67, .55)),
                    ((.17, .23), (.58, .38)),
                ]
                for index, account in enumerate(accounts):
                    gemini, claude = examples[index]
                    app.quota_cache[account['name']] = {'data': {'groups': [
                        {'kind': 'gemini', 'buckets': [bucket('5h', gemini[0], 1.5 + index * .3),
                                                       bucket('weekly', gemini[1], 80 + index * 10)]},
                        {'kind': 'claude', 'buckets': [bucket('5h', claude[0], 2 + index * .2),
                                                       bucket('weekly', claude[1], 94 + index * 6)]},
                    ]}}
                app.loaded(accounts)
                app.activity_state['stats']['demo-2'] = {
                    'last_model': 'gemini-3-flash', 'last': datetime.now(timezone.utc).isoformat()}
                app.activity_state['stats']['demo-4'] = {
                    'last_model': 'claude-opus-4-6-thinking', 'last': datetime.now(timezone.utc).isoformat()}
                app.toggle_details()
                app.maxsize(2400, 2400)
                app.geometry('280x1060+40+40')
                app.attributes('-topmost', True)
                app.update()
                app.after(300, app.update)
                app.update()
                app.animate_active_borders()
                app.update_idletasks()
                hwnd = app.winfo_id()
                shot = ImageGrab.grab(window=hwnd)
                destination = root / 'docs' / 'compact-panel.png'
                shot.save(destination, optimize=True)
                print(f'{destination} {shot.size[0]}x{shot.size[1]}')
            finally:
                app.closed = True
                app.destroy()


if __name__ == '__main__':
    main()
