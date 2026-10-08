import unittest
from response_guard import StreamProbe, usable_message


class ResponseGuardTests(unittest.TestCase):
    def test_fragmented_sse_and_thinking_only(self):
        probe = StreamProbe()
        data = b'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Working"}}\r\n\r\ndata: {"type":"message_stop"}\r\n\r\n'
        for byte in data:
            probe.feed(bytes([byte]))
        self.assertFalse(probe.usable)
        self.assertTrue(probe.terminal)

    def test_whitespace_text_is_empty_but_tools_are_real_output(self):
        self.assertFalse(usable_message({'content':[{'type':'text','text':' \n'}]}))
        self.assertTrue(usable_message({'content':[{'type':'tool_use','name':'Read'}]}))
