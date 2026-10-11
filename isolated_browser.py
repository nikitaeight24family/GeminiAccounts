"""Open OAuth in a fresh browser profile, separate from the user's daily browser."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend import AccountError


def forced_profile_policy(kind):
    """A managed UserDataDir policy overrides --user-data-dir and breaks isolation."""
    if os.name != 'nt':
        return False
    import winreg
    vendor = 'Microsoft\\Edge' if kind == 'edge' else 'Google\\Chrome'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, 'SOFTWARE\\Policies\\' + vendor) as key:
                value, _ = winreg.QueryValueEx(key, 'UserDataDir')
                if value:
                    return True
        except OSError:
            pass
    return False


def find_browser():
    roots = [os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'),
             os.environ.get('LOCALAPPDATA')]
    for root in filter(None, roots):
        for relative, kind in [
            ('Microsoft/Edge/Application/msedge.exe', 'edge'),
            ('Google/Chrome/Application/chrome.exe', 'chrome'),
        ]:
            candidate = Path(root) / relative
            if candidate.is_file() and not forced_profile_policy(kind):
                return candidate, kind
    raise AccountError('A separate ChatGPT sign-in needs Edge or Chrome without a managed browser profile policy.')


def open_isolated(url):
    """Use a unique temporary profile for every sign-in, including concurrent ones."""
    browser, kind = find_browser()
    # Do not remove the profile when the launcher process exits: Chromium may
    # hand the window to a child process that is still completing OAuth.
    profile = Path(tempfile.mkdtemp(prefix='gemini-chatgpt-signin-'))
    args = [str(browser), '--user-data-dir=' + str(profile), '--no-first-run',
            '--no-default-browser-check', '--new-window',
            '--inprivate' if kind == 'edge' else '--incognito', url]
    try:
        process = subprocess.Popen(args, close_fds=True)
    except OSError as error:
        shutil.rmtree(profile, ignore_errors=True)
        raise AccountError('Could not open the separate ChatGPT sign-in browser.') from error

    return process
