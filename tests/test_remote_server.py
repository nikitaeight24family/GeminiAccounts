import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from remote_server import (
    build_ssh_command,
    get_client_snippets,
    collect_accounts_payload,
    test_ssh_connection,
    deploy_to_server
)


class RemoteServerTests(unittest.TestCase):
    def test_build_ssh_command_basic(self):
        config = {'host': '192.168.1.100', 'port': 2222, 'user': 'ubuntu'}
        cmd = build_ssh_command(config, 'whoami')
        self.assertIn('-p', cmd)
        self.assertIn('2222', cmd)
        self.assertIn('ubuntu@192.168.1.100', cmd)
        self.assertEqual(cmd[-1], 'whoami')

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

        # Check Codex snippets
        self.assertIn('model_provider = "omni_server"', snippets['codex_ps'])
        self.assertIn('http://1.2.3.4:8317/v1', snippets['codex_ps'])
        self.assertIn('experimental_bearer_token = "secret-key-123"', snippets['codex_bash'])

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
