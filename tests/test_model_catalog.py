import json
import unittest
from pathlib import Path


class ModelCatalogTests(unittest.TestCase):
    def test_flash_levels_are_distinct_upstream_models(self):
        path = Path(__file__).resolve().parents[1] / 'assets' / 'cliproxy-models.json'
        models = json.loads(path.read_text(encoding='utf-8'))['antigravity']
        ids = [entry['id'] for entry in models]
        self.assertEqual(len(ids), len(set(ids)))
        for version in ('3.6', '3.7', '3.8'):
            for level in ('high', 'medium', 'low'):
                self.assertIn(f'gemini-{version}-flash-{level}', ids)
        for model in ('gemini-3-flash-agent', 'gemini-3.5-flash-low', 'gemini-3.5-flash-extra-low'):
            self.assertIn(model, ids)


if __name__ == '__main__':
    unittest.main()
