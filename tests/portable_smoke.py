"""Real service startup smoke test in an empty, isolated CI installation."""
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Controller
from runtime import initialize, install_native, start_services, stop_owned

with tempfile.TemporaryDirectory() as directory:
    os.environ['GEMINI_ACCOUNTS_HOME'] = directory
    controller = Controller()
    initialize(controller)
    install_native(controller)
    owned = start_services(controller)
    try:
        assert controller.request('/auth-files').get('files') == [], 'A fresh installation must have no accounts'
        snapshot = controller.quota_wait_status()
        assert snapshot.get('jobs') == [] and snapshot.get('poll_seconds') == 3, 'Quota queue must respond'
        if len(sys.argv) > 1:
            # Verify the bundled executable's internal queue worker on the real OS.
            stop_owned(owned)
            executable = str(Path(sys.argv[1]).resolve())
            process = subprocess.Popen([executable, 'serve'], env=os.environ.copy(),
                creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
            try:
                for _ in range(100):
                    try:
                        assert controller.request('/auth-files').get('files') == []
                        snapshot = controller.quota_wait_status()
                        assert snapshot.get('jobs') == [] and snapshot.get('poll_seconds') == 3
                        # The queue status fallback also returns empty on failure.
                        controller.base = 'http://127.0.0.1:8317'
                        assert controller.request('/quota-wait').get('jobs') == []
                        controller.base = 'http://127.0.0.1:8318'
                        break
                    except Exception:
                        controller.base = 'http://127.0.0.1:8318'
                        time.sleep(.2)
                else:
                    raise RuntimeError('Standalone services did not start')
                result = subprocess.run([executable, 'status'], capture_output=True, text=True, timeout=90, env=os.environ.copy())
                assert result.returncode == 0, result.stderr
                assert 'No accounts yet' in result.stdout, result.stdout
                print('Standalone executable and bundled queue: OK')
            finally:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
                process.wait(timeout=30)
        print('Fresh native service and quota queue: OK')
    finally:
        stop_owned(owned)
