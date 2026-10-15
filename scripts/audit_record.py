# /// script
# requires-python = ">=3.11"
# dependencies = ["questionary==2.1.1"]
# ///
"""Interactive recording of restore decisions. No package installs or baseline acceptance."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import difflib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import tomllib
import uuid

import audit

DESTINATIONS = {
    "brew_formulae": "manifests/Brewfile.core", "brew_casks": "manifests/Brewfile.apps",
    "npm": "manifests/npm-tools.txt", "vscode": "manifests/vscode-extensions.txt",
}
SELECTABLE = (*DESTINATIONS, "local_launchers")
FILES = (*DESTINATIONS.values(), "manifests/installations.toml")


@dataclass(frozen=True)
class Item:
    kind: str
    name: str


@dataclass
class Change:
    path: Path
    before: bytes
    after: bytes
    mode: int


def capture(repo):
    originals = {}
    for relative in FILES:
        path = repo / relative
        if path.is_symlink() or not path.resolve().is_relative_to(repo) or not stat.S_ISREG(path.stat().st_mode):
            raise audit.AuditError("Recording requires regular manifest files inside the repository")
        originals[relative] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    return originals


def items_from(snapshot):
    row = snapshot["checks"]["restore"]
    if row["status"] != "ok":
        raise audit.AuditError("Restore coverage is unverified. Fix that check before recording decisions.")
    return [Item(key, name) for key in SELECTABLE
            for name in row["data"]["gaps"].get(audit.LABELS[key], [])]


def valid_name(item):
    pattern = r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9][A-Za-z0-9_.+@-]*" if item.kind == "npm" else r"[A-Za-z0-9][A-Za-z0-9_.+@-]*"
    if item.kind not in SELECTABLE or not re.fullmatch(pattern, item.name):
        raise audit.AuditError("Unsupported package or launcher name. Record this recipe manually.")


def brew_tap(item, snapshot):
    row = snapshot["inventories"][item.kind]
    root = Path(row["scope"]).expanduser()
    if not root.is_absolute():
        raise audit.AuditError("Homebrew inventory location is invalid")
    if item.kind == "brew_casks":
        paths = [root / item.name / ".metadata/INSTALL_RECEIPT.json"]
    else:
        versions = row["data"].get(item.name, [])
        if any(Path(v).name != v or v in (".", "..") for v in versions):
            raise audit.AuditError("Homebrew version metadata is invalid")
        paths = [root / item.name / version / "INSTALL_RECEIPT.json" for version in versions]
    taps = set()
    for path in paths:
        metadata = audit.read_json(path)
        source = metadata.get("source") if isinstance(metadata, dict) else None
        tap = source.get("tap") if isinstance(source, dict) else None
        if not isinstance(tap, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", tap):
            raise audit.AuditError("Cannot establish the Homebrew tap from the local receipt")
        taps.add(tap)
    if len(taps) != 1:
        raise audit.AuditError("Homebrew tap ownership is ambiguous. Record this package manually.")
    return taps.pop()


def append_lines(text, lines):
    return text.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def add_exclusions(text, entries, reason):
    if not reason.strip():
        raise audit.AuditError("An exclusion needs a reason")
    for kind in SELECTABLE:
        names = sorted({item.name for item in entries if item.kind == kind})
        if not names:
            continue
        parsed = tomllib.loads(text)
        current = parsed.get("excluded", {}).get(kind, {})
        if any(name in current for name in names):
            raise audit.AuditError("An exclusion already exists. Run record again against current declarations.")
        additions = [f"{json.dumps(name, ensure_ascii=False)} = {json.dumps(reason.strip(), ensure_ascii=False)}" for name in names]
        lines = text.splitlines(keepends=True)
        header = re.compile(r"\s*\[excluded\." + re.escape(kind) + r"\]\s*(?:#.*)?$")
        start = next((i + 1 for i, line in enumerate(lines) if header.fullmatch(line.strip())), None)
        if start is None:
            text = append_lines(text, ["", f"[excluded.{kind}]", *additions])
        else:
            end = next((i for i in range(start, len(lines)) if re.match(r"\s*\[[A-Za-z0-9_.-]+\]\s*(?:#.*)?$", lines[i].strip())), len(lines))
            while end > start and not lines[end - 1].strip():
                end -= 1
            if end and not lines[end - 1].endswith("\n"):
                lines[end - 1] += "\n"
            lines[end:end] = [line + "\n" for line in additions]
            text = "".join(lines)
        if not all(tomllib.loads(text)["excluded"][kind][name] == reason.strip() for name in names):
            raise audit.AuditError("Could not preserve the registry format")
    return text


def plan(repo, originals, selected, action, snapshot, reason=""):
    available = set(items_from(snapshot))
    if any(item not in available for item in selected):
        raise audit.AuditError("Selection is not part of the current restore-gap list")
    for item in selected:
        valid_name(item)
    texts = {relative: data.decode("utf-8") for relative, (data, _) in originals.items()}
    if action == "exclude":
        relative = "manifests/installations.toml"
        texts[relative] = add_exclusions(texts[relative], selected, reason)
    elif action == "restore":
        for item in sorted(set(selected), key=lambda x: (x.kind, x.name)):
            if item.kind not in DESTINATIONS:
                raise audit.AuditError("A local launcher needs an explicit manual installer recipe")
            relative = DESTINATIONS[item.kind]
            name = item.name
            additions = []
            if item.kind in ("brew_formulae", "brew_casks"):
                tap = brew_tap(item, snapshot)
                if tap not in ("homebrew/core", "homebrew/cask"):
                    tap_pattern = re.compile(r'''^\s*tap\s+["']''' + re.escape(tap) + r'''["']\s*(?:#.*)?$''', re.M)
                    if not any(tap_pattern.search(texts[key]) for key in ("manifests/Brewfile.core", "manifests/Brewfile.apps")):
                        additions.append(f'tap "{tap}"')
                    name = f"{tap}/{name}"
                additions.append(f'{"brew" if item.kind == "brew_formulae" else "cask"} "{name}"')
            else:
                additions.append(name)
            texts[relative] = append_lines(texts[relative], additions)
    else:
        raise audit.AuditError("Unknown recording action")
    return [Change(repo / relative, originals[relative][0], text.encode("utf-8"), originals[relative][1])
            for relative, text in texts.items() if text.encode("utf-8") != originals[relative][0]]


def replace_file(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_changes(changes, state):
    if any(c.path.read_bytes() != c.before for c in changes):
        raise audit.AuditError("A manifest changed during review. Nothing was written. Run record again.")
    backup = state / "record-backups" / uuid.uuid4().hex
    backup.mkdir(parents=True, mode=0o700)
    for index, change in enumerate(changes):
        replace_file(backup / f"{index}-{change.path.name}", change.before, 0o600)
    written = []
    try:
        for change in changes:
            if change.path.read_bytes() != change.before:
                raise audit.AuditError("A manifest changed during recording")
            written.append(change)
            replace_file(change.path, change.after, change.mode)
    except BaseException as exc:
        conflicts = []
        for change in reversed(written):
            try:
                current = change.path.read_bytes()
                if current == change.before:
                    continue
                if current != change.after:
                    conflicts.append(change.path.name)
                    continue
                replace_file(change.path, change.before, change.mode)
            except OSError:
                conflicts.append(change.path.name)
        extra = f" Review backups at {audit.short_path(backup)}." if conflicts else " Completed manifest writes were rolled back."
        raise audit.AuditError("Recording stopped before completion." + extra) from exc
    return backup


def visible_line(line):
    # Preserve ordinary quotes in the diff, but never emit terminal control sequences.
    return "".join(char if char.isprintable() or char == "\t" else char.encode("unicode_escape").decode()
                   for char in line)


@contextmanager
def repository_lock(repo):
    directory = Path(audit.command(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"], "/").strip())
    if not directory.is_absolute() or not directory.is_dir():
        raise audit.AuditError("Cannot locate the repository metadata directory")
    with (directory / "dotfiles-record.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise audit.AuditError("Another checklist is already recording this repository") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def prompt(repo, state, originals, snapshot, questionary):
    candidates = items_from(snapshot)
    if not candidates:
        print("No selectable restore gaps found.")
        return 0
    action = questionary.select("What would you like to record?", choices=[
        questionary.Choice("Restore selected tools on another Mac", value="restore"),
        questionary.Choice("Exclude selected tools, with a reason", value="exclude"),
        questionary.Choice("Cancel", value="cancel"),
    ]).ask()
    if action not in ("restore", "exclude"):
        print("Cancelled. No manifest changes.")
        return 0
    choices = []
    for kind in SELECTABLE:
        rows = [item for item in candidates if item.kind == kind]
        if not rows:
            continue
        choices.append(questionary.Separator(audit.LABELS[kind]))
        for item in rows:
            target = DESTINATIONS.get(kind, "manual installer recipe") if action == "restore" else "exclusion registry"
            disabled = "Needs a manual installer recipe" if action == "restore" and kind not in DESTINATIONS else None
            choices.append(questionary.Choice(f"{audit.safe(item.name)} -> {target}", value=item, checked=False, disabled=disabled))
    selected = questionary.checkbox("Select tools", choices=choices,
                                    instruction="Arrows move, Space selects, Enter continues, Ctrl+C cancels").ask()
    if not selected:
        print("No tools selected. No manifest changes.")
        return 0
    reason = ""
    if action == "exclude":
        reason = questionary.text("Why should these tools stay outside the restore setup?",
                                   validate=lambda value: bool(value.strip()) or "Please give a reason").ask()
        if reason is None:
            print("Cancelled. No manifest changes.")
            return 0
    changes = plan(repo, originals, selected, action, snapshot, reason)
    print("\nProposed changes:")
    for change in changes:
        relative = str(change.path.relative_to(repo))
        preview = difflib.unified_diff(change.before.decode().splitlines(), change.after.decode().splitlines(),
                                       fromfile=relative, tofile=relative, lineterm="")
        print("\n".join(visible_line(line) for line in preview))
    if not questionary.confirm("Write these manifest changes?", default=False).ask():
        print("Cancelled. No manifest changes.")
        return 0
    if any((repo / path).read_bytes() != data for path, (data, _) in originals.items()):
        raise audit.AuditError("A manifest changed during review. Nothing was written. Run record again.")
    backup = apply_changes(changes, state)
    print(f"Recorded {len(selected)} decisions in {len(changes)} files. Review the Git diff and commit when ready.")
    print(f"Original manifests backed up at {audit.short_path(backup)}")
    print("No installed tools, live settings, or accepted inventory were changed. Run audit.sh to refresh the report.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Recording needs an interactive terminal.", file=sys.stderr)
        return 2
    repo, state = args.repo.resolve(), args.state_dir.expanduser().resolve()
    if state == repo or repo in state.parents:
        parser.error("State must be outside the repository")
    import questionary
    try:
        with repository_lock(repo):
            originals = capture(repo)
            with audit.locked(state):
                snapshot = audit.validate(audit.collect(repo))
            return prompt(repo, state, originals, snapshot, questionary)
    except KeyboardInterrupt:
        print("Cancelled. No further manifest changes.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, audit.AuditError) as exc:
        message = str(exc) if isinstance(exc, audit.AuditError) else f"Cannot record decisions ({type(exc).__name__})"
        print(audit.safe(message), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
