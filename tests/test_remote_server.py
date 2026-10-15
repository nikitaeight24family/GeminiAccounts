import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from remote_server import (
    build_ssh_command,
    get_client_snippets,
    collect_accounts_payload,
    test_ssh_connection,
    deploy_to_server,
    probe_remote_gateway,
    validate_ssh_config
)


class RemoteServerTests(unittest.TestCase):
    def test_build_ssh_command_basic(self):
        config = {'host': '192.168.1.100', 'port': 2222, 'user': 'ubuntu'}
        cmd = build_ssh_command(config, 'whoami')
        self.assertIn('-p', cmd)
        self.assertIn('2222', cmd)
        self.assertIn('ubuntu@192.168.1.100', cmd)
        self.assertEqual(cmd[-1], 'whoami')

    def test_empty_ssh_config_is_rejected_before_network_call(self):
        with self.assertRaisesRegex(Exception, 'host or IP'):
            validate_ssh_config({})

    def test_build_ssh_command_with_fido(self):
        config = {'host': '10.0.0.1', 'port': 22, 'user': 'deploy', 'use_fido': True}
        cmd = build_ssh_command(config, 'uptime')
        self.assertIn('deploy@10.0.0.1', cmd)
        self.assertNotIn('-o BatchMode=yes', ' '.join(cmd))
        self.assertEqual(cmd[-1], 'uptime')

    def test_get_client_snippets_structure(self):
        snippets = get_client_snippets('1.2.3.4', 'secret-key-123')
        self.assertEqual(snippets['server_ip'], '1.2.3.4')
        self.assertEqual(snippets['client_key'], 'secret-key-123')
        self.assertEqual(snippets['gateway_url'], 'http://1.2.3.4:8317')

        # Check Claude Code CLI snippets
        self.assertIn('ANTHROPIC_BASE_URL', snippets['claude_code_ps'])
        self.assertIn('http://1.2.3.4:8317', snippets['claude_code_ps'])
        self.assertIn('secret-key-123', snippets['claude_code_ps'])
        self.assertIn('CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY', snippets['claude_code_bash'])
        self.assertIn('omni-backup', snippets['claude_code_bash'])
        self.assertIn('Claude Code route verification failed', snippets['claude_code_bash'])
        self.assertNotIn('>> ~/.claude/settings.json', snippets['claude_code_bash'])

        # Check Codex snippets
        self.assertIn('model_provider = "omni_server"', snippets['codex_ps'])
        self.assertIn('http://1.2.3.4:8317/v1', snippets['codex_ps'])
        self.assertIn('export OMNI_CODEX_URL=http://1.2.3.4:8317/v1 OMNI_CODEX_TOKEN=secret-key-123', snippets['codex_bash'])
        self.assertNotIn('>> ~/.codex/config.toml', snippets['codex_bash'])
        self.assertIn('${CODEX_HOME:-$HOME/.codex}/config.toml', snippets['codex_bash'])
        self.assertIn('codex doctor', snippets['codex_bash'])
        self.assertIn('previous Codex config was restored', snippets['codex_bash'])
        self.assertIn("'experimental_bearer_token = ' + json.dumps(token)", snippets['codex_bash'])
        self.assertIn('CODEX_HOME-aware profile', snippets['codex_cli_bash'])
        self.assertNotIn('CODEX_HOME', snippets['codex_desktop_bash'])
        self.assertIn('codex_desktop_ps', snippets)
        self.assertIn('codex_cli_ps', snippets)

        # Every server route has a matching stock restore command.  It keeps a
        # timestamped backup and removes only Omni-managed settings.
        self.assertIn('omni-backup', snippets['claude_restore_ps'])
        self.assertIn('ANTHROPIC_BASE_URL', snippets['claude_restore_bash'])
        self.assertIn('model_providers\\.omni_server', snippets['codex_restore_ps'])
        self.assertIn('model_providers\\.omni_server', snippets['codex_restore_bash'])

        # Check Claude Desktop
        self.assertIn('"inferenceGatewayBaseUrl": "http://1.2.3.4:8317"', snippets['claude_desktop_json'])
        self.assertIn('"inferenceGatewayApiKey": "secret-key-123"', snippets['claude_desktop_json'])

    def test_collect_accounts_payload(self):
        controller = Mock()
        controller.proxy_dir = Path(__file__).resolve().parent / 'fixtures' / 'non_existent'
        payload = collect_accounts_payload(controller)
        self.assertEqual(payload, {})

    @patch('remote_server.run_ssh_command')
    def test_test_ssh_connection(self, mock_run):
        mock_run.return_value = "Linux\nroot\nUbuntu 24.04.1 LTS"
        res = test_ssh_connection({'host': '1.2.3.4', 'user': 'root'})
        self.assertTrue(res['connected'])
        self.assertEqual(res['kernel'], 'Linux')
        self.assertEqual(res['user'], 'root')
        self.assertEqual(res['os'], 'Ubuntu 24.04.1 LTS')

    @patch('remote_server.urllib.request.build_opener')
    def test_remote_gateway_probe_reports_catalog_and_latency(self, mock_opener):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"data":[{"id":"gemini-3-flash"}]}'
        mock_opener.return_value.open.return_value = Response()
        result = probe_remote_gateway({'host': '1.2.3.4', 'client_key': 'secret'})
        self.assertTrue(result['connected'])
        self.assertEqual(result['model_count'], 1)
        self.assertIn('latency_ms', result)

    def test_remote_gateway_probe_does_not_claim_unconfigured_server(self):
        result = probe_remote_gateway({})
        self.assertFalse(result['connected'])
        self.assertIn('Deploy', result['error'])

    @patch('remote_server.run_ssh_command')
    def test_deploy_to_server(self, mock_run):
        mock_run.side_effect = [
            "Linux\nroot\nUbuntu 24.04.1 LTS",
            "Imported 2 accounts\nOMNI_DEPLOY_OK:key_abc_123"
        ]
        controller = Mock()
        controller.proxy_dir = Path(__file__).resolve().parent / 'fixtures' / 'non_existent'
        controller.preferences = {}
        progress = []
        res = deploy_to_server({'host': '1.2.3.4', 'user': 'root'}, controller, progress_callback=progress.append)
        self.assertTrue(res['success'])
        self.assertEqual(res['client_key'], 'key_abc_123')
        self.assertEqual(controller.preferences['remote-server']['client_key'], 'key_abc_123')
        self.assertTrue(any('Connected' in p for p in progress))


if __name__ == '__main__':
    unittest.main()
