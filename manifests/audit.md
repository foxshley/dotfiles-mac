# Environment audit

Run the audit after installing tools or before updating dotfiles:

```bash
bash "$HOME/dotfiles/scripts/audit.sh"
```

The first run lists the current inventory. Later runs compare it with the last inventory you accepted. Additions, removals, and version changes stay visible until you accept a new baseline. The audit reads local metadata and writes its own state. It does not install tools, fetch updates, apply configuration, or copy live settings into dotfiles.

To review the last saved snapshot without collecting again:

```bash
bash "$HOME/dotfiles/scripts/audit.sh" report
```

To accept that snapshot as the new software baseline:

```bash
bash "$HOME/dotfiles/scripts/audit.sh" accept
```

Check the snapshot date before accepting. If your setup has changed since the scan, run another audit first. Acceptance acknowledges the software inventory. It does not add anything to a Brewfile, capture settings, or commit changes. Git and chezmoi differences are shown on every audit, including after acceptance.

## Coverage

| Check | What it records |
| --- | --- |
| Homebrew | Formula and cask names and installed versions, including dependencies. Reads local install receipts without invoking Homebrew or refreshing its API. |
| mise | Installed runtimes and global version requests. No check for newer upstream releases. |
| npm | Top-level package names and versions from the active global prefix and every installed mise Node prefix. Prefixes are identified separately and deduplicated. |
| VS Code | Extension IDs and versions from the default `~/.vscode/extensions/extensions.json` index. No CLI invocation or log creation. |
| Git | Current local commit and changed source paths. No file contents, remote URLs, fetch, or push. |
| chezmoi | Status of managed destination paths using this repository as the explicit source. No config contents or full diffs. |

The audit requires Python 3.11 or newer and a Unix system with file locking. It uses whichever tools are available on PATH, so run it from your normal development shell. Snapshot state is bound to the repository path.

This is a scoped inventory, not a record of every app or file on the Mac. It does not inspect shell history, credentials, app state, project dependencies, uv tools, or Cargo packages. VS Code profiles, Insiders, remote extensions, and custom extension directories are outside this first version. Inactive npm prefixes managed outside mise are outside coverage unless they are the active npm prefix when scanned. Package timestamps are not used as installation dates.

## Failed checks and changing coverage

A failed collector is reported as **unverified**. It is never treated as an empty package list, and its removals are not inferred. A snapshot containing a failed check cannot become the baseline. An unavailable tool is allowed in the first baseline, with its coverage explicitly unverified. If a previously successful collector becomes unavailable, acceptance is blocked.

Changing a collector's location or observed npm prefix set makes that section incomparable with the old scope. The report lists the current entries rather than inventing removals. Adding a new Node prefix is allowed. Losing a known npm prefix blocks ordinary acceptance because the audit cannot tell whether it was removed or simply stopped being discovered.

Restore the previous PATH or mise discovery and scan again if that loss was accidental. If you intentionally removed a Node installation or changed its prefix, review the new snapshot and explicitly acknowledge the reduced coverage:

```bash
bash "$HOME/dotfiles/scripts/audit.sh" accept --allow-prefix-loss
```

That flag only permits reduced npm prefix coverage. It does not bypass failed collectors or a missing previously available tool. A removal reported within an observed npm prefix is not proof of a machine-wide uninstall.

Exit status is `0` for a successful audit, even when changes are found. It is `2` for a failed check, lost previously available coverage, invalid state, or an operation already holding the lock. Initially unavailable tools remain clearly marked even when the audit exits successfully.

## Local state

Snapshots live under `${XDG_STATE_HOME:-~/.local/state}/dotfiles-audit/`. They contain package metadata and changed path names, so keep them local. The state directory is private with mode `700`, and snapshot and pointer files use mode `600`. The command rejects a state directory inside the repository.

Each scan writes a new snapshot. `latest.json` points to the last completed scan, including one with collector failures. `baseline.json` changes only on explicit acceptance. Atomic file replacement protects these pointers, and a process lock prevents overlapping scans or acceptance. The operating system releases the lock if the process exits. Keep the lock file in place.

To use a separate state directory, for example when testing:

```bash
bash "$HOME/dotfiles/scripts/audit.sh" --state-dir /tmp/dotfiles-audit-test
```

The directory must be private. Use the same option for `report` and `accept`. Snapshots are retained until you remove them, so this initial version has no automatic history cleanup.

## Verification

Fixture tests cover package deltas, collector failures, prefix coverage loss, explicit acceptance, repeated scans, invalid state, privacy, lock contention, and failed atomic writes. They use temporary directories and do not touch your real baseline:

```bash
python3 -B "$HOME/dotfiles/scripts/test_audit.py"
```

The repository verifier also runs these tests.
