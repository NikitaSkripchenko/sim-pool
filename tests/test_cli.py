import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDS = ["00000000-0000-4000-8000-00000000000" + str(i) for i in range(1, 4)]

FAKE = """#!/usr/bin/env python3
import fcntl, json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
path = Path(os.environ['FAKE_DEVICES'])
with path.open('r+') as file:
    fcntl.flock(file, fcntl.LOCK_EX)
    devices = json.load(file)
    def save():
        file.seek(0)
        json.dump(devices, file)
        file.truncate()
    if Path(sys.argv[0]).name == 'xcrun':
        args = args[1:]
        if args[:2] == ['--set', 'testing']:
            print('{"devices":{}}')
        elif args[0] == 'list':
            print(json.dumps({'devices': {'com.apple.CoreSimulator.SimRuntime.iOS-27-0': [
                {'udid': id, 'name': id[-1], 'state': state, 'isAvailable': True}
                for id, state in devices.items()
            ]}}))
        else:
            command, id = args[:2]
            if command == 'erase' and os.environ.get('FAIL_ERASE'):
                sys.exit(17)
            devices[id] = 'Booted' if command == 'bootstatus' else 'Shutdown'
            save()
        sys.exit()
    id = args[args.index('-destination') + 1].split('id=')[1]
    assert devices[id] == 'Booted'
    assert args[args.index('-parallel-testing-enabled') + 1] == 'NO'
    with open(os.environ['FAKE_EVENTS'], 'a') as log:
        log.write(json.dumps({'id': id, 'args': args, 'pid': os.getpid()}) + '\\n')
release = os.environ.get('FAKE_RELEASE')
deadline = time.monotonic() + 30
while release and not Path(release).exists() and time.monotonic() < deadline:
    time.sleep(0.05)
time.sleep(float(os.environ.get('TEST_DURATION', '0')))
sys.exit(int(os.environ.get('TEST_EXIT', '0')))
"""


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.devices = self.path / "devices"
        self.events = self.path / "events"
        self.devices.write_text(json.dumps(dict.fromkeys(IDS, "Shutdown")))
        self.events.touch()
        for name in ("xcrun", "xcodebuild"):
            fixture = self.path / name
            fixture.write_text(FAKE)
            fixture.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.path}:{os.environ['PATH']}",
                        SIM_POOL_HOME=str(self.path / "state"),
                        FAKE_DEVICES=str(self.devices), FAKE_EVENTS=str(self.events))
        self.processes = []
        self.addCleanup(self.stop_processes)
        result = self.cli("init", *IDS[:2])
        self.assertEqual(result.returncode, 0, result.stderr)

    def cli(self, *args, **env):
        if not (ROOT / "sim-pool").exists():
            return subprocess.CompletedProcess(args, 127, "", "sim-pool executable is missing")
        return subprocess.run([ROOT / "sim-pool", *args], env=self.env | env,
                              capture_output=True, text=True, timeout=30)

    def start(self, *args, **env):
        process = subprocess.Popen([ROOT / "sim-pool", *args], env=self.env | env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        return process

    def stop_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

    def rows(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()]

    def wait_for_events(self, count):
        end = time.monotonic() + 20
        while time.monotonic() < end:
            if len(self.rows()) >= count:
                return
            time.sleep(0.05)
        self.fail(f"Expected {count} runs, saw {self.rows()}")

    def test_passes_xcode_arguments_and_returns_test_exit_code(self):
        result = self.cli("test", "-scheme", "test", TEST_EXIT="65")
        self.assertEqual(result.returncode, 65, result.stderr)
        row, = self.rows()
        self.assertEqual(row["args"][-1], "test")
        self.assertEqual(json.loads(self.devices.read_text())[row["id"]], "Shutdown")
        self.assertIn("available", self.cli("status").stdout)

    def test_queues_third_run_and_preserves_two_distinct_devices(self):
        command = ("test", "-scheme", "Demo")
        release = self.path / "release"
        runs = [self.start(*command, FAKE_RELEASE=str(release)) for _ in range(2)]
        self.wait_for_events(2)
        queued = self.start(*command)
        time.sleep(0.35)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(len({event["id"] for event in self.rows()}), 2)
        release.touch()
        for run in [*runs, queued]:
            _, stderr = run.communicate(timeout=25)
            self.assertEqual(run.returncode, 0, stderr)
        self.assertEqual(len(self.rows()), 3)

    def test_counts_manual_boot_and_cancels_running_test(self):
        self.devices.write_text(json.dumps({**dict.fromkeys(IDS[:2], "Shutdown"), IDS[2]: "Booted"}))
        first = self.start("test", "-scheme", "Demo", TEST_DURATION="30")
        self.wait_for_events(1)
        queued = self.start("test", "-scheme", "Demo")
        time.sleep(0.35)
        self.assertEqual(len(self.rows()), 1)
        first.send_signal(signal.SIGINT)
        _, stderr = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 130, stderr)
        _, stderr = queued.communicate(timeout=10)
        self.assertEqual(queued.returncode, 0, stderr)
        self.assertEqual(json.loads(self.devices.read_text())[IDS[2]], "Booted")

    def test_failed_erase_keeps_slot_blocked_until_recovery(self):
        result = self.cli("test", "-scheme", "Demo", FAIL_ERASE="1")
        self.assertNotEqual(result.returncode, 0)
        id = self.rows()[0]["id"]
        self.assertIn("blocked", self.cli("status").stdout)
        result = self.cli("test", "-scheme", "Demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.rows()[1]["id"], id)
        result = self.cli("recover", id)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("blocked", self.cli("status").stdout)

    def test_runner_death_does_not_erase_a_live_worker(self):
        release = self.path / "release"
        run = self.start("test", "-scheme", "Demo", FAKE_RELEASE=str(release))
        self.wait_for_events(1)
        row, = self.rows()
        run.kill()
        run.wait(timeout=5)
        result = self.cli("recover", row["id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still running", result.stderr)
        self.assertEqual(json.loads(self.devices.read_text())[row["id"]], "Booted")
        release.touch()
        run.communicate(timeout=15)
        result = self.cli("recover", row["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.devices.read_text())[row["id"]], "Shutdown")

    def test_queued_cancel_never_runs_or_erases_an_external_device(self):
        self.devices.write_text(json.dumps(dict.fromkeys(IDS, "Booted")))
        run = self.start("test", "-scheme", "Demo")
        with selectors.DefaultSelector() as selector:
            selector.register(run.stderr, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=15), "No admission decision")
            self.assertIn("Waiting for a slot", run.stderr.readline())
        run.send_signal(signal.SIGINT)
        run.communicate(timeout=5)
        self.assertEqual(run.returncode, 130)
        self.assertEqual(self.rows(), [])
        self.assertEqual(set(json.loads(self.devices.read_text()).values()), {"Booted"})

    def test_defaults_to_lightweight_failure_diagnostics(self):
        result = self.cli("test", "-scheme", "Demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.rows()[0]["args"]
        self.assertIn("-collect-test-diagnostics", args)
        self.assertEqual(args[args.index("-collect-test-diagnostics") + 1], "never")

    def test_rejects_destination_overrides(self):
        result = self.cli("test", "-scheme", "Demo", "-destination", "platform=iOS Simulator")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-destination", result.stderr)
        self.assertEqual(self.rows(), [])

    def test_uses_prebuilt_test_action(self):
        result = self.cli("test", "-xctestrun", "Demo.xctestrun")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[0]["args"][-1], "test-without-building")
