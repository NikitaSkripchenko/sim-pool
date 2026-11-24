# Sim Pool

Run local iOS XCTest jobs on a shared pool of disposable simulators. Jobs wait at the configured limit. The runner chooses a UDID, streams Xcode output, then erases and shuts down its device.

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

For longer builds, build first and give the runner the compiled test bundle. The slot is then occupied only while the simulator is in use. Pass the `-xctestrun` path without `-scheme`, `-project` or `-workspace`.

```sh
xcodebuild build-for-testing -scheme MyApp -destination 'generic/platform=iOS Simulator'
sim-pool test -xctestrun /absolute/path/to/MyApp.xctestrun
```

Use Ctrl-C to cancel a wait or active run. If cleanup fails or the runner is forcibly terminated, inspect `sim-pool status`. Once the recorded processes have exited, `sim-pool recover UDID` retries shutdown and erase for that slot. Recovery erases a pool slot. External interactive devices keep their data.

## Expand the pool

Create a dedicated iOS simulator in Xcode or with `xcrun simctl create`, then
register its UDID while it is shut down:

```sh
sim-pool add NEW_DEVICE_UDID
sim-pool status
```

Each addition raises the limit by one. Visible external devices, such as a
manually started Duo, still take one place in that limit. Registered devices
are erased after tests. Existing reservations continue to run during expansion.

## Guard agent tool calls

Run `./install-sim-pool --hooks` to append a global PreToolUse guard for Codex
and Claude Code. Preserve other hooks and open fresh sessions. If Codex asks
to trust the hook, review it via `/hooks`. The guard rejects direct XCTest and
known simulator-mutating tools. Use `sim-pool test` for XCTest. Read-only
inventory and standard builds remain available. Use Terminal for manual
administration of special devices.

For interactive work, start a lease and keep it running while you use the
simulator tools:

```sh
sim-pool hold
sim-pool hold EXISTING_DEVICE_UDID
```

Use one of these commands per session. The first chooses a free pool slot.
The second requests a specific existing device, for example a dedicated Duo.
Both count toward the visible Mac limit. Pass the printed UDID explicitly to
Claude simulator calls (`device`) or supported Xcode MCP calls (`simulatorId`).
The hook checks for a ready, live interactive lease at that UDID. It does not
authenticate the agent that holds the lease. Creation, cloning and direct
XCTest remain blocked through supported agent tool paths. Manage devices in
your own Terminal.

Ctrl-C releases the lease. Pool slots are erased. An existing device outside
the pool keeps its data and its starting boot state. Reinstall the hooks with
`./install-sim-pool --hooks` to remove any old static device exception.

The guard only sees tool calls surfaced by the client. It does not govern
manual Xcode or Simulator.app operations or indirect commands hidden in
scripts. To remove it, remove its PreToolUse entry pointing to
`sim-pool-hook` in each client configuration.

## Remove retired simulators

Preview both the default set and Xcode's testing set. Pass the same keep list
when applying the reviewed deletion list. Pool slots and recorded leases are
protected automatically.

```sh
sim-pool prune --keep SPECIAL_DEVICE_UDID
sim-pool prune --keep SPECIAL_DEVICE_UDID --delete RETIRED_UDID_1 RETIRED_UDID_2
```

Deletion is permanent. The command rejects the entire selection if any
requested device is active, protected or missing at validation. Stop active
devices separately after checking their owners. Runtime failures during deletion
can leave a partially applied batch. Each completed deletion is printed.

## How the limit works

Runner processes coordinate through a local file lock and a record of the current slots. Xcode runs outside the lock. A waiting command retries when capacity is available. Strict FIFO ordering is not guaranteed.

The runner counts devices in the default and Xcode parallel-testing sets. A visible external boot takes capacity. Direct calls to Xcode or Simulator can still bypass the shared limit, and custom device sets or other macOS users are outside this inventory.

By default, the state, per-project/per-device build caches and test results live in `~/Library/Application Support/sim-pool`. Use the same location across sessions. The CLI has no daemon and needs no SimSlim install. When no runs are active, old result bundles and build caches can be removed independently of the pool state.

## Develop

```sh
python3 -m unittest discover -s tests -v
```

Tests run the actual CLI in separate processes with isolated simulator and Xcode fixtures.
