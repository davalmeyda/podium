import unittest

from podium.targets import _memory_mcp_entry


class MemoryMcpEntryTests(unittest.TestCase):
    def test_minimal_entry(self):
        entry = _memory_mcp_entry({"url": "http://m.example/mcp", "headers": {}, "mcp_options": {}})
        self.assertEqual(entry, {"type": "remote", "url": "http://m.example/mcp", "enabled": True})

    def test_headers_and_options(self):
        entry = _memory_mcp_entry({
            "url": "http://m.example/mcp",
            "headers": {"Host": "localhost:8000"},
            "mcp_options": {"timeout": 180000, "oauth": False, "enabled": False},
        })
        self.assertEqual(entry["headers"], {"Host": "localhost:8000"})
        self.assertEqual(entry["timeout"], 180000)
        self.assertIs(entry["oauth"], False)
        self.assertIs(entry["enabled"], True)  # options never override the core keys


if __name__ == "__main__":
    unittest.main()
