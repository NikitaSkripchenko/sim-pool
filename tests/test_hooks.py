import json
from pathlib import Path
import subprocess
import unittest

HOOK = Path(__file__).resolve().parents[1] / "sim-pool-hook"


class HookTest(unittest.TestCase):
    def call(self, tool, *, approved=(), **arguments):
        return subprocess.run(
            [HOOK, *[f"--interactive-device={udid}" for udid in approved]], input=json.dumps({"tool_name": tool, "tool_input": arguments}),
            capture_output=True, text=True, timeout=5,
        )

    def test_blocks_direct_simulator_commands(self):
        for command in (
            "cd project && xcodebuild -scheme Demo test",
            "xcrun simctl --set testing boot UDID",
            "xcrun simctl --set=testing boot UDID",
            "/usr/bin/xcrun simctl bootstatus UDID -b",
            "xcrun simctl delete UDID",
            "xcrun simctl create Name Type Runtime",
            "sim-pool add UDID",
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


    def test_legacy_allowlist_does_not_grant_access_without_lease(self):
        server = "mcp__Claude_Code_iOS_Simulator__control"
        duo = "58039C64-5C2E-4D1D-848A-417DFBC183A3"
        for action in ("attach", "tap", "screenshot", "open_url"):
            with self.subTest(action=action):
                self.assertEqual(self.call(server, approved=[duo], device=duo,
                                           action=action).returncode, 2)
