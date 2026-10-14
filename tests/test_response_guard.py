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

    def test_codex_responses_stream_probe(self):
        probe = StreamProbe()
        probe.feed(b'event: response.failed\ndata: {"type":"response.failed","response":{"status":"failed"}}\n\n')
        self.assertTrue(probe.error)
        self.assertFalse(probe.usable)

        probe2 = StreamProbe()
        probe2.feed(b'event: response.output_item.added\ndata: {"type":"response.output_item.added"}\n\n')
        self.assertTrue(probe2.usable)
        self.assertFalse(probe2.error)

    def test_usable_message_for_responses(self):
        self.assertFalse(usable_message({'status':'failed','error':{'message':'overloaded'}}))
        self.assertTrue(usable_message({'status':'completed','output':[{'type':'message'}]}))
