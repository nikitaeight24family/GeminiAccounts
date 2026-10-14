"""Validate Anthropic and OpenAI Responses streams before exposing an empty completion or error to a client."""
import json

class StreamProbe:
    """Incremental SSE probe for Anthropic and OpenAI Responses protocols."""
    limit = 16 * 1024 * 1024

    def __init__(self):
        self.pending = b''
        self.buffer = bytearray()
        self.usable = False
        self.terminal = False
        self.error = False

    def feed(self, data):
        self.buffer.extend(data)
        if len(self.buffer) > self.limit:
            raise ValueError('Response validation buffer exceeded')
        self.pending += data
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            line = line.strip()
            if not line.startswith(b'data:'):
                continue
            payload = line[5:].strip()
            if not payload or payload == b'[DONE]':
                continue
            try:
                value = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                continue
            kind = value.get('type')
            if kind in ('error', 'response.failed'):
                self.error = True
            elif kind in ('message_stop', 'response.completed', 'response.done'):
                self.terminal = True
                if kind in ('response.completed', 'response.done'):
                    resp_status = (value.get('response') or {}).get('status') or value.get('status')
                    if resp_status == 'completed':
                        self.usable = True
            elif kind == 'content_block_start':
                block = value.get('content_block', {})
                self.usable |= block.get('type') in ('tool_use', 'server_tool_use') or (
                    block.get('type') == 'text' and bool(block.get('text', '').strip()))
            elif kind == 'content_block_delta':
                delta = value.get('delta', {})
                self.usable |= delta.get('type') == 'text_delta' and bool(delta.get('text', '').strip())
            elif kind in ('response.text.delta', 'response.output_text.delta'):
                delta = value.get('delta') or value.get('text') or ''
                if str(delta).strip():
                    self.usable = True
            elif kind in ('response.function_call_arguments.delta', 'response.output_item.added'):
                self.usable = True


def usable_message(value):
    if not isinstance(value, dict):
        return False
    if value.get('error') or value.get('status') == 'failed':
        return False
    if value.get('status') == 'completed':
        return True
    if any(b.get('type') in ('tool_use', 'server_tool_use') or
           (b.get('type') == 'text' and bool(b.get('text', '').strip()))
           for b in value.get('content', []) if isinstance(b, dict)):
        return True
    output = value.get('output')
    if isinstance(output, list) and len(output) > 0:
        return True
    return False
