"""Extend the pinned CLIProxyAPI 8.0.16 catalog with exposed Antigravity levels."""
import copy
import json
import sys
from pathlib import Path


def main(source, output):
    catalog = json.loads(Path(source).read_text(encoding='utf-8'))
    models = catalog['antigravity']
    ids = {model['id'] for model in models}
    for version in ('3.6', '3.7', '3.8'):
        original = next(model for model in models if model['id'] == f'gemini-{version}-flash-high')
        for level in ('medium', 'low'):
            name = f'gemini-{version}-flash-{level}'
            if name in ids:
                continue
            model = copy.deepcopy(original)
            model['id'] = model['name'] = name
            model['description'] = model['display_name'] = f'Gemini {version} Flash ({level.title()})'
            models.append(model)
    base = next(model for model in models if model['id'] == 'gemini-3.6-flash-high')
    for name, label in (
        ('gemini-3-flash-agent', 'Gemini 3.5 Flash (High)'),
        ('gemini-3.5-flash-low', 'Gemini 3.5 Flash (Medium)'),
        ('gemini-3.5-flash-extra-low', 'Gemini 3.5 Flash (Low)'),
    ):
        if name not in ids:
            model = copy.deepcopy(base)
            model['id'] = model['name'] = name
            model['description'] = model['display_name'] = label
            models.append(model)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main(*sys.argv[1:])
