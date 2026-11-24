import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = """#!/usr/bin/env python3
import json, os, sys, uuid
from pathlib import Path

path = Path(os.environ['FAKE_INVENTORY'])
entries = json.loads(path.read_text()) if path.exists() else []
command, *args = sys.argv[2:]
if command == 'create':
    udid = str(uuid.uuid4()).upper()
    entries.append(dict(udid=udid, name=args[0], state='Shutdown', isAvailable=True))
    path.write_text(json.dumps(entries))
    print(udid)
elif command == 'list':
    print(json.dumps({'devices': {'com.apple.CoreSimulator.SimRuntime.iOS-27-0': entries}}))
elif command == '--set' and args[0] == 'testing':
    print('{"devices": {}}')
else:
    sys.exit(2)
"""


class InstallTest(unittest.TestCase):
    def test_reinstall_reuses_devices_preserves_instructions_and_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            fake = home / "xcrun"
            fake.write_text(FAKE)
            fake.chmod(0o755)
            codex = home / ".codex"
            codex.mkdir()
            override = codex / "AGENTS.override.md"
            override.write_text("Existing preferences.\n")
            claude_home = home / ".claude"
            claude_home.mkdir()
            settings = claude_home / "settings.json"
            settings.write_text('{"hooks":{"PreToolUse":[{"matcher":"Edit","hooks":[]}]}}')
            env = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex),
                       CLAUDE_CONFIG_DIR=str(home / ".claude"),
                       FAKE_INVENTORY=str(home / "devices"),
                       PATH=f"{home}:{os.environ['PATH']}")
            env.pop("SIM_POOL_HOME", None)

            installer = ROOT / "install-sim-pool"
            self.assertTrue(installer.is_file(), "Repository installer is missing")
            for _ in range(2):
                result = subprocess.run([installer, "--hooks"], env=env, capture_output=True,
                                        text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Sim Pool A", result.stdout)
            inventory = (home / "devices").read_text()
            self.assertEqual(inventory.count('"udid"'), 2)
            self.assertTrue(override.read_text().startswith("Existing preferences.\n"))
            self.assertFalse((codex / "AGENTS.md").exists())
            self.assertEqual(override.read_text().count("## Local iOS simulator pool"), 1)
            claude = (home / ".claude/CLAUDE.md").read_text()
            self.assertEqual(claude.count("## Local iOS simulator pool"), 1)
            self.assertIn("current task holds its reservation", claude)
            self.assertEqual((home / ".local/bin/sim-pool").resolve(), ROOT / "sim-pool")
            codex_hooks = json.loads((codex / "hooks.json").read_text())["hooks"]["PreToolUse"]
            claude_hooks = json.loads(settings.read_text())["hooks"]["PreToolUse"]
            self.assertEqual(len(codex_hooks), 1)
            self.assertEqual(len(claude_hooks), 2)
            self.assertEqual(claude_hooks[0]["matcher"], "Edit")
            self.assertEqual(claude_hooks[1], codex_hooks[0])
