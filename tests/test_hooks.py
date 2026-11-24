import json
from pathlib import Path
import subprocess
import unittest

HOOK = Path(__file__).resolve().parents[1] / "sim-pool-hook"


class HookTest(unittest.TestCase):
    def call(self, tool, **arguments):
        return subprocess.run(
            [HOOK], input=json.dumps({"tool_name": tool, "tool_input": arguments}),
            capture_output=True, text=True, timeout=5,
        )

    def test_blocks_direct_simulator_commands(self):
        for command in (
            "cd project && xcodebuild -scheme Demo test",
            "xcrun simctl --set testing boot UDID",
            "xcrun simctl --set=testing boot UDID",
            "/usr/bin/xcrun simctl bootstatus UDID -b",
            "xcrun simctl delete UDID",
        ):
            with self.subTest(command=command):
                result = self.call("Bash", command=command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("sim-pool", result.stderr)

    def test_allows_builds_inventory_and_pool(self):
        for command in ("xcodebuild build-for-testing -scheme Demo",
                        "xcodebuild -scheme test build-for-testing",
                        "xcrun simctl list devices booted --json",
                        "sim-pool test -scheme Demo",
                        "git log --grep='xcodebuild test'"):
            with self.subTest(command=command):
                self.assertEqual(self.call("Bash", command=command).returncode, 0)

    def test_blocks_mcp_launch_and_allows_read_only(self):
        for name, arguments, expected in (
            ("mcp__xcodebuildmcp__test_sim", {}, 2),
            ("mcp__mobilebuildmcp__build_run_sim", {}, 2),
            ("mcp__xcodebuildmcp__batch", {}, 2),
            ("mcp__xcodebuildmcp__list_sims", {}, 0),
            ("mcp__Claude_Code_iOS_Simulator__control", {"action": "attach"}, 2),
            ("mcp__Claude_Code_iOS_Simulator__control", {"action": "list"}, 0),
        ):
            with self.subTest(name=name, arguments=arguments):
                self.assertEqual(self.call(name, **arguments).returncode, expected)
