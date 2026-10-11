"""Empirical capacity from observed token counts and quota percentage changes."""
import json
import math
from backend import atomic_write


class TokenCapacity:
    def __init__(self, path):
        self.path = path
        try:
            self.state = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            self.state = {'baselines': {}, 'estimates': {}}

    def observe(self, name, provider, plan, groups, model_tokens):
        """Reject resets, mixed models and missing data instead of assigning false precision."""
        changed = False
        for group in groups:
            for bucket in group.get('buckets', []):
                window = bucket.get('window')
                remaining = bucket.get('remaining')
                if window not in ('5h', 'weekly') or not isinstance(remaining, (int, float)) or isinstance(remaining, bool) or not math.isfinite(remaining) or not 0 <= remaining <= 1:
                    continue
                identity = json.dumps([name, provider, plan, group['kind'], window])
                current = {'remaining': remaining, 'reset': bucket.get('reset'), 'tokens': dict(model_tokens)}
                old = self.state['baselines'].get(identity)
                reset_changed = old and old['reset'] != current['reset']
                if reset_changed:
                    try:
                        from routing import reset_date
                        reset_changed = abs((reset_date(old['reset']) - reset_date(current['reset'])).total_seconds()) > 5
                    except (TypeError, AttributeError):
                        pass
                if not old or reset_changed or remaining > old['remaining'] + 1e-7:
                    self.state['baselines'][identity] = current
                    changed = True
                    continue
                delta = {model: value - old['tokens'].get(model, 0) for model, value in model_tokens.items()}
                if any(value < 0 for value in delta.values()):
                    self.state['baselines'][identity] = current
                    changed = True
                    continue
                used = old['remaining'] - remaining
                if used < .009999:
                    continue
                positive = {model: value for model, value in delta.items() if value > 0}
                if len(positive) == 1:
                    model, tokens = next(iter(positive.items()))
                    key = json.dumps([provider, plan or 'unknown', group['kind'], model, window])
                    estimate = self.state['estimates'].setdefault(key, {'tokens': 0, 'used': 0, 'samples': 0, 'min': None, 'max': None})
                    capacity = tokens / used
                    estimate['tokens'] += tokens
                    estimate['used'] += used
                    estimate['samples'] += 1
                    estimate['min'] = min(estimate['min'] or capacity, capacity)
                    estimate['max'] = max(estimate['max'] or capacity, capacity)
                # A mixed-model interval cannot identify each model's quota cost.
                self.state['baselines'][identity] = current
                changed = True
        if changed:
            atomic_write(self.path, json.dumps(self.state).encode('utf-8'))

    def rows(self):
        rows = []
        for key, value in self.state['estimates'].items():
            provider, plan, family, model, window = json.loads(key)
            rows.append({'provider': provider, 'plan': plan, 'family': family, 'model': model,
                         'window': window, **value, 'capacity': round(value['tokens'] / value['used']),
                         'ready': value['samples'] >= 3 and value['used'] >= .02})
        return sorted(rows, key=lambda row: (row['provider'], row['plan'], row['model'], row['window']))
