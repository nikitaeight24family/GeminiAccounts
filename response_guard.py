"""Validate Anthropic streams before exposing an empty completion to a client."""
import json

class StreamProbe:
    """Incremental SSE probe. Thinking alone is not a usable completion."""
    limit = 8 * 1024 * 1024

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
            if not line.startswith(b'data:'):
                continue
            try:
                value = json.loads(line[5:].strip())
            except (ValueError, UnicodeDecodeError):
                continue
            kind = value.get('type')
            if kind == 'error':
                self.error = True
            elif kind == 'message_stop':
                self.terminal = True
            elif kind == 'content_block_start':
                block = value.get('content_block', {})
                self.usable |= block.get('type') in ('tool_use', 'server_tool_use') or (
                    block.get('type') == 'text' and bool(block.get('text', '').strip()))
            elif kind == 'content_block_delta':
                delta = value.get('delta', {})
                self.usable |= delta.get('type') == 'text_delta' and bool(delta.get('text', '').strip())


def usable_message(value):
    return any(b.get('type') in ('tool_use', 'server_tool_use') or
               (b.get('type') == 'text' and bool(b.get('text', '').strip()))
               for b in value.get('content', []) if isinstance(b, dict))
