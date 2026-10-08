import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from backend import AccountError
from updater import check_update, download_update, version


class UpdaterTests(unittest.TestCase):
    def test_numeric_version_and_release_validation(self):
        self.assertGreater(version('v1.10.0'), version('1.9.0'))
        with self.assertRaises(ValueError):
            version('../evil')
        release = {'tag_name':'v9.0.0','assets':[{'name':'GeminiAccounts-Setup.exe',
            'digest':'sha256:'+'a'*64, 'browser_download_url':'https://evil.example/installer.exe'}]}
        with patch('updater.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaises(AccountError):
                check_update()

    def test_download_rejects_tampered_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = SimpleNamespace(data_dir=Path(directory))
            release = {'version':'v9.0.0','url':'https://example','sha256':hashlib.sha256(b'good').hexdigest()}
            with patch('updater.urllib.request.urlopen', return_value=io.BytesIO(b'bad')):
                with self.assertRaises(AccountError):
                    download_update(controller, release)
            self.assertEqual(list((Path(directory)/'updates').iterdir()), [])
            with patch('updater.urllib.request.urlopen', return_value=io.BytesIO(b'good')):
                self.assertEqual(download_update(controller, release).read_bytes(), b'good')
