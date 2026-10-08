import unittest
from response_guard import StreamProbe, usable_message, add_role_guidance


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

    def test_system_cache_blocks_preserved_and_guard_idempotent(self):
        request = {'system':[{'type':'text','text':'Original','cache_control':{'type':'ephemeral'}}]}
        result = add_role_guidance(add_role_guidance(request))
        self.assertEqual(len(result['system']), 2)
        self.assertEqual(result['system'][0], request['system'][0])
        self.assertEqual(len(request['system']), 1)
