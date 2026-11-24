# Sim Pool

Run local iOS XCTest jobs on two shared, disposable simulators. The third job waits. The runner chooses a UDID, streams Xcode output, then erases and shuts down its device.

## Set up once

Use macOS, Xcode and Python 3.9 or newer. Keep one pool per macOS user so Codex, Claude and terminal sessions share the same two slots.

Run `./install-sim-pool` from this checkout. On first install it creates two dedicated iPhone 17 simulators on iOS 27.0, adds a command symlink and appends user instructions for Codex and Claude Code. For a different installed device type or runtime, pass `--device` or `--runtime` with the corresponding CoreSimulator identifier. Subsequent installs reuse the configured devices. Open new agent sessions after installation.

To use two existing disposable devices, set up their UDIDs manually:

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/sim-pool" ~/.local/bin/sim-pool
xcrun simctl list devices available
sim-pool init FIRST_UDID SECOND_UDID
```

Run commands from the repository root. Add `~/.local/bin` to your `PATH` if needed. Pick two available, shut-down iOS devices from the default set that are safe to erase. Use freshly configured devices if your first job needs a clean simulator. Initialization only records the two UDIDs.

## Run tests

From an Xcode project directory:

```sh
sim-pool test -scheme MyApp
sim-pool status
```

Pass Xcode options such as `-project`, `-workspace` or `-only-testing` as usual. The runner selects the action and destination and disables parallel test workers. It prints the waiting, boot and cleanup times. Test output streams directly, and the result bundle stays on the Mac after cleanup. By default, failed tests skip verbose simulator diagnostics to avoid long collection delays. To collect them explicitly, pass `-collect-test-diagnostics on-failure`.

For longer builds, build first and give the runner the compiled test bundle. The slot is then occupied only while the simulator is in use.

```sh
xcodebuild build-for-testing -scheme MyApp -destination 'generic/platform=iOS Simulator'
sim-pool test -xctestrun /absolute/path/to/MyApp.xctestrun
```

Use Ctrl-C to cancel a wait or active run. If cleanup fails or the runner is forcibly terminated, inspect `sim-pool status`. Once the recorded processes have exited, `sim-pool recover UDID` retries shutdown and erase for that slot. Recovery erases the named simulator.

## How the limit works

Runner processes coordinate through a local file lock and a record of the current slots. Xcode runs outside the lock. A waiting command retries when capacity is available. Strict FIFO ordering is not guaranteed.

The runner counts devices in the default and Xcode parallel-testing sets. A visible external boot takes capacity. Direct calls to Xcode or Simulator can still bypass the shared limit, and custom device sets or other macOS users are outside this inventory.

By default, the state, per-project/per-device build caches and test results live in `~/Library/Application Support/sim-pool`. Use the same location across sessions. The CLI has no daemon and needs no SimSlim install. When no runs are active, old result bundles and build caches can be removed independently of the pool state.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

Tests run the actual CLI in separate processes with isolated simulator and Xcode fixtures.
