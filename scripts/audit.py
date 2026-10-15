#!/usr/bin/env python3
"""Local inventories and live drift. No installs, network queries, or config copies."""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.exit("Python 3.11+ is required. Use the Python installed through mise.")

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from copy import deepcopy

SCHEMA = 2
NAMES = ("brew_formulae", "brew_casks", "mise_installed", "mise_global", "npm", "vscode", "local_launchers", "manual")
CHECKS = ("git", "chezmoi", "missing_runtimes", "restore")
LABELS = {
    "brew_formulae": "Homebrew formulae", "brew_casks": "Homebrew casks",
    "mise_installed": "Installed mise runtimes", "mise_global": "Global mise requests",
    "npm": "npm globals by prefix", "vscode": "VS Code extensions (default profile)",
    "local_launchers": "Local launchers (names and metadata)",
    "manual": "Registered manual installations",
}


class AuditError(Exception):
    pass


def result(status="ok", data=None, reason="", scope="", coverage=None):
    return {"status": status, "data": {} if data is None else data,
            "reason": reason, "scope": scope, "coverage": [] if coverage is None else coverage}


def command(args, cwd):
    # Discard diagnostics from reports: tools may include local config or credentials.
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_ANALYTICS="1",
               npm_config_update_notifier="false", npm_config_logs_max="0",
               GIT_OPTIONAL_LOCKS="0", NO_COLOR="1")
    try:
        proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=45, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AuditError(f"{Path(args[0]).name} timed out") from exc
    except OSError as exc:
        raise AuditError(f"Cannot run {Path(args[0]).name} ({type(exc).__name__})") from exc
    if proc.returncode:
        raise AuditError(f"{Path(args[0]).name} exited {proc.returncode}; check it separately")
    return proc.stdout


def attempt(collector):
    try:
        return collector()
    except (OSError, ValueError, KeyError, TypeError, AuditError) as exc:
        # Never include exception messages from parsers/files that can contain values.
        reason = str(exc) if isinstance(exc, AuditError) else f"Cannot read inventory ({type(exc).__name__})"
        return result("error", reason=reason)


def read_json(path):
    return json.loads(path.read_text())


def short_path(path):
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text


def homebrew_root():
    brew = shutil.which("brew")
    prefix = os.environ.get("HOMEBREW_PREFIX")
    if not prefix and brew:
        prefix = str(Path(brew).absolute().parent.parent)
    return Path(prefix) if prefix else None


def brew_inventory(kind):
    prefix = homebrew_root()
    override = os.environ.get("HOMEBREW_CELLAR" if kind == "formulae" else "HOMEBREW_CASKROOM")
    if not prefix and not override:
        return result("unavailable", reason="Homebrew not found on PATH")
    root = Path(override) if override else prefix / ("Cellar" if kind == "formulae" else "Caskroom")
    if not root.is_dir():
        raise AuditError(f"Homebrew {kind} directory is unavailable")
    data, requested, unknown = {}, [], []
    for package in sorted(root.iterdir()):
        if package.name.startswith(".") or not package.is_dir():
            continue
        versions, request_flags = [], []
        for version in sorted(package.iterdir()):
            if version.name.startswith(".") or not version.is_dir():
                continue
            if kind == "formulae":
                receipt = version / "INSTALL_RECEIPT.json"
                if not receipt.is_file():
                    raise AuditError("Formula directory has no install receipt; inventory may be in transition")
                metadata = read_json(receipt)
                if not isinstance(metadata, dict):
                    raise AuditError("Invalid Homebrew install receipt")
                request_flags.append(metadata.get("installed_on_request"))
            versions.append(version.name)
        if versions:
            if kind == "casks":
                receipt = package / ".metadata/INSTALL_RECEIPT.json"
                metadata = read_json(receipt)
                if not isinstance(metadata, dict):
                    raise AuditError("Invalid Homebrew cask receipt")
                request_flags.append(metadata.get("installed_on_request"))
            data[package.name] = versions
            if any(flag is True for flag in request_flags):
                requested.append(package.name)
            elif any(not isinstance(flag, bool) for flag in request_flags):
                unknown.append(package.name)
    row = result(data=data, scope=short_path(root.resolve()))
    row.update(requested=requested, request_unknown=unknown)
    return row


def mise_records(flag):
    data = json.loads(command(["mise", "ls", flag, "--json"], "/"))
    if not isinstance(data, dict) or any(not isinstance(rows, list) for rows in data.values()):
        raise AuditError("Unsupported mise inventory format")
    for rows in data.values():
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("version"), str)
                    or not isinstance(row.get("installed"), bool)):
                raise AuditError("Incomplete mise inventory")
    return data


def mise_inventory(records, global_requests=False):
    data = {}
    for name, rows in records.items():
        values = set()
        for row in rows:
            if global_requests:
                request = row.get("requested_version")
                if not isinstance(request, str):
                    raise AuditError("Mise global request is missing")
                values.add(request)
            elif row.get("installed") is True:
                values.add(row["version"])
        if values:
            data[name] = sorted(values)
    return result(data=data, scope="global requests" if global_requests else "all installed mise runtimes")


def npm_inventory(installed):
    prefixes = set()
    if installed is not None:
        for row in installed.get("node", []):
            if row.get("installed") is True:
                path = row.get("install_path")
                if not isinstance(path, str) or not Path(path).is_dir():
                    raise AuditError("An installed mise Node prefix is unavailable")
                prefixes.add(Path(path).resolve())
    if shutil.which("npm"):
        raw = command(["npm", "prefix", "-g"], "/").strip()
        if not raw or "\n" in raw or not Path(raw).is_absolute():
            raise AuditError("Cannot identify the active npm prefix")
        prefixes.add(Path(raw).resolve())
    if not prefixes:
        return result("unavailable", reason="No active npm or installed mise Node prefix found")
    data = {}
    for prefix in sorted(prefixes):
        modules = prefix / "lib/node_modules"
        if not prefix.is_dir():
            raise AuditError("An npm prefix is unavailable")
        if not modules.exists():
            continue
        packages = []
        for item in sorted(modules.iterdir()):
            if item.name.startswith("."):
                continue
            packages.extend(sorted(item.iterdir()) if item.name.startswith("@") else [item])
        for package in packages:
            if not package.is_dir() and not package.is_symlink():
                continue
            meta = read_json(package / "package.json")
            if (not isinstance(meta, dict) or not isinstance(meta.get("name"), str)
                    or not isinstance(meta.get("version"), str)):
                raise AuditError("An npm package has incomplete metadata")
            data[f"{short_path(prefix)} :: {meta['name']}"] = [meta["version"]]
    return result(data=data, scope="active npm prefix and all installed mise Node prefixes",
                  coverage=[short_path(p) for p in sorted(prefixes)])


def vscode_inventory():
    root = Path.home() / ".vscode/extensions"
    if not root.is_dir():
        return result("unavailable", reason="Default VS Code extensions directory not found")
    index = root / "extensions.json"
    if not index.exists():
        if any(p.is_dir() and not p.name.startswith(".") for p in root.iterdir()):
            raise AuditError("VS Code extension index is missing but extension folders exist")
        return result(data={}, scope=short_path(root))
    records = read_json(index)
    if not isinstance(records, list):
        raise AuditError("Unsupported VS Code extension index")
    data = {}
    for row in records:
        name, version = row["identifier"]["id"], row["version"]
        if not isinstance(name, str) or not isinstance(version, str):
            raise AuditError("Invalid VS Code extension metadata")
        data.setdefault(name.lower(), []).append(version)
    return result(data={k: sorted(set(v)) for k, v in data.items()}, scope=short_path(root))


def local_launchers():
    root = Path.home() / ".local/bin"
    data = {}
    try:
        entries = sorted(root.iterdir())
    except FileNotFoundError:
        entries = []
    for path in entries:
        if path.is_symlink():
            target = path.readlink()
            target = target if target.is_absolute() else root / target
            target = Path(os.path.normpath(target))
            info = f"symlink -> {short_path(target)}"
            try:
                meta = path.stat()
                info += f" (size={meta.st_size}, mtime_ns={meta.st_mtime_ns})"
            except FileNotFoundError:
                info += " (missing target)"
            data[path.name] = [info]
        elif path.is_file() and os.access(path, os.X_OK):
            meta = path.stat()
            data[path.name] = [f"executable file (size={meta.st_size}, mtime_ns={meta.st_mtime_ns})"]
    return result(data=data, scope=short_path(root))


def declared_packages(repo):
    """Parse the supported literal manifest formats. Never evaluate a Brewfile."""
    declarations = {key: set() for key in ("brew_formulae", "brew_casks", "npm", "vscode")}
    paths = [repo / "manifests" / name for name in ("Brewfile.core", "Brewfile.apps")]
    for path in paths:
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not re.match(r"^(brew|cask)\b", stripped):
                continue
            match = re.fullmatch(r'''(brew|cask)\s+["']([^"']+)["'](?:\s*,.*)?(?:\s*#.*)?''', stripped)
            if not match:
                raise AuditError("Unsupported Brewfile declaration; restore coverage is unverified")
            key = "brew_formulae" if match[1] == "brew" else "brew_casks"
            declarations[key].add(match[2].rsplit("/", 1)[-1])
    for key, filename in (("npm", "npm-tools.txt"), ("vscode", "vscode-extensions.txt")):
        for line in (repo / "manifests" / filename).read_text().splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                if any(c.isspace() for c in entry):
                    raise AuditError("Unsupported tool-list entry in restore manifests")
                name = entry.rsplit("@", 1)[0] if "@" in entry[1:] else entry
                declarations[key].add(name.lower() if key == "vscode" else name)
    tools = tomllib.loads((repo / "dot_config/mise/config.toml").read_text()).get("tools")
    if not isinstance(tools, dict):
        raise AuditError("Managed mise tools table is missing")
    requests = {}
    for key, value in tools.items():
        values = value if isinstance(value, list) else [value]
        versions = [v.get("version") if isinstance(v, dict) else v for v in values]
        if not versions or any(not isinstance(v, str) for v in versions):
            raise AuditError("Unsupported managed mise version request")
        requests[key] = sorted(set(versions))
    declarations["mise_global"] = requests
    registry = tomllib.loads((repo / "manifests/installations.toml").read_text())
    if registry.get("schema") != 1:
        raise AuditError("Unsupported manual installation registry")
    manual, excluded = registry.get("manual", {}), registry.get("excluded", {})
    if not isinstance(manual, dict) or not isinstance(excluded, dict):
        raise AuditError("Invalid installation registry")
    for entry in manual.values():
        if not isinstance(entry, dict):
            raise AuditError("Invalid manual installation entry")
        names = entry.get("executables")
        if (not isinstance(names, list) or not names or
                any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+", n) for n in names)):
            raise AuditError("Invalid manual launcher names")
        for field in ("source", "install", "update", "verify"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise AuditError("Manual recipe needs source, install, update, and verify instructions")
        marker = entry.get("marker")
        if (not isinstance(marker, str) or not marker or Path(marker).is_absolute()
                or ".." in Path(marker).parts):
            raise AuditError("Manual recipe needs a marker path relative to the home directory")
        checkout = entry.get("checkout")
        if checkout is not None and (not isinstance(checkout, str) or not checkout
                                     or Path(checkout).is_absolute() or ".." in Path(checkout).parts):
            raise AuditError("Manual source checkout must be relative to the home directory")
    owners = [name for entry in manual.values() for name in entry["executables"]]
    if len(owners) != len(set(owners)):
        raise AuditError("A manual launcher has more than one declared owner")
    for key, entries in excluded.items():
        if (key not in declarations and key != "local_launchers") or not isinstance(entries, dict):
            raise AuditError("Invalid exclusion category")
        if any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in entries.items()):
            raise AuditError("Exclusions need an explicit reason")
    return declarations, manual, excluded


def manual_inventory(repo):
    _, manual, _ = declared_packages(repo)
    data = {}
    for name, entry in manual.items():
        if not (Path.home() / entry["marker"]).is_file():
            continue
        version = "present (installation marker only)"
        if entry.get("checkout"):
            root = Path.home() / entry["checkout"]
            if (root / ".git").exists():
                revision = command(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], "/").strip()
                if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
                    raise AuditError("Cannot read a registered manual tool's source revision")
                version = f"source commit {revision}"
        data[name] = [version]
    return result(data=data, scope="manual recipes in manifests/installations.toml")


def restore_coverage(repo, inventories):
    declarations, manual, exclusions = declared_packages(repo)
    gaps, excluded, unverified = {}, {}, []
    registered = []
    if inventories["manual"]["status"] != "ok":
        unverified.append(LABELS["manual"])
    launcher_owners = {name: owner for owner, entry in manual.items()
                       if (Path.home() / entry["marker"]).is_file() for name in entry["executables"]}
    for key in ("brew_formulae", "brew_casks", "mise_global", "npm", "vscode", "local_launchers"):
        row = inventories[key]
        if row["status"] != "ok":
            unverified.append(LABELS[key])
            continue
        names = set(row["data"])
        if key in ("brew_formulae", "brew_casks"):
            if "requested" not in row or "request_unknown" not in row:
                unverified.append(LABELS[key] + " (direct-install metadata unavailable)")
                continue
            names = set(row["requested"])
            unverified.extend(f"{LABELS[key]}: direct/dependency status unknown for {n}" for n in row["request_unknown"])
        for name in sorted(names):
            package = name.rsplit(" :: ", 1)[-1] if key == "npm" else name
            reason = exclusions.get(key, {}).get(package)
            if reason:
                excluded.setdefault(LABELS[key], []).append(f"{package}: {reason}")
            elif key == "local_launchers":
                if package in launcher_owners:
                    registered.append(f"{package}: manual recipe '{launcher_owners[package]}'")
                else:
                    gaps.setdefault(LABELS[key], []).append(package)
            elif key == "mise_global":
                if declarations[key].get(package) != row["data"][name]:
                    gaps.setdefault(LABELS[key], []).append(package + " (global request differs from managed source)")
            elif package not in declarations[key]:
                gaps.setdefault(LABELS[key], []).append(package)
    return result(data={"gaps": gaps, "excluded": excluded,
                        "registered_manual": sorted(registered), "unverified": unverified})


def live_checks(repo, global_records):
    git = attempt(lambda: result(data={
        "head": command(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], "/").strip(),
        "changes": command(["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=normal"], "/").splitlines(),
    }))
    chezmoi = (attempt(lambda: result(data={"changes": command([
        "chezmoi", f"--source={repo}", "--refresh-externals=never", "--no-tty", "--no-pager", "status"
    ], "/").splitlines()})) if shutil.which("chezmoi") else result("unavailable", reason="chezmoi not found on PATH"))
    missing = (result(data={"tools": sorted(f"{name}@{row['version']}" for name, rows in global_records.items()
                                           for row in rows if row.get("installed") is not True)})
               if global_records is not None else result("unavailable", reason="Mise requests could not be checked"))
    return {"git": git, "chezmoi": chezmoi, "missing_runtimes": missing}


def collect(repo):
    inventories = {"brew_formulae": attempt(lambda: brew_inventory("formulae")),
                   "brew_casks": attempt(lambda: brew_inventory("casks")),
                   "vscode": attempt(vscode_inventory),
                   "local_launchers": attempt(local_launchers),
                   "manual": attempt(lambda: manual_inventory(repo))}
    installed = global_records = None
    if shutil.which("mise"):
        try:
            installed = mise_records("--installed")
            inventories["mise_installed"] = mise_inventory(installed)
        except (OSError, ValueError, KeyError, TypeError, AuditError):
            inventories["mise_installed"] = result("error", reason="Cannot read installed mise runtimes")
        try:
            global_records = mise_records("--global")
            inventories["mise_global"] = mise_inventory(global_records, True)
        except (OSError, ValueError, KeyError, TypeError, AuditError):
            inventories["mise_global"] = result("error", reason="Cannot read global mise requests")
    else:
        for key in ("mise_installed", "mise_global"):
            inventories[key] = result("unavailable", reason="mise not found on PATH")
    inventories["npm"] = (result("error", reason="Cannot enumerate npm prefixes because mise inventory failed")
                          if inventories["mise_installed"]["status"] == "error"
                          else attempt(lambda: npm_inventory(installed)))
    checks = live_checks(repo, global_records)
    checks["restore"] = attempt(lambda: restore_coverage(repo, inventories))
    return {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "repo": str(repo), "inventories": inventories,
            "checks": checks}


def validate(snapshot):
    if isinstance(snapshot, dict) and snapshot.get("schema") == 1:
        # Upgrade only in memory. Keep the original baseline and history intact.
        snapshot = deepcopy(snapshot)
        snapshot["schema"] = SCHEMA
        snapshot["inventories"]["local_launchers"] = result("unavailable", reason="Not collected by the older auditor")
        snapshot["inventories"]["manual"] = result("unavailable", reason="Not collected by the older auditor")
        snapshot["checks"]["restore"] = result("unavailable", reason="Not checked by the older auditor")
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        raise AuditError("Unsupported snapshot schema")
    if not isinstance(snapshot.get("repo"), str) or not isinstance(snapshot.get("created_at"), str):
        raise AuditError("Invalid snapshot identity")
    for section, names in (("inventories", NAMES), ("checks", CHECKS)):
        group = snapshot.get(section)
        if not isinstance(group, dict) or set(group) != set(names):
            raise AuditError("Incomplete snapshot")
        for row in group.values():
            if not isinstance(row, dict) or row.get("status") not in ("ok", "error", "unavailable"):
                raise AuditError("Invalid collector status")
            if not isinstance(row.get("data"), dict) or not isinstance(row.get("reason"), str) or not isinstance(row.get("scope"), str):
                raise AuditError("Invalid collector data")
            coverage = row.get("coverage")
            if not isinstance(coverage, list) or any(not isinstance(x, str) for x in coverage):
                raise AuditError("Invalid collector coverage")
    for row in snapshot["inventories"].values():
        if any(not isinstance(k, str) or not isinstance(v, list) or not v or
               any(not isinstance(x, str) for x in v) for k, v in row["data"].items()):
            raise AuditError("Invalid package inventory")
    for key in ("git", "chezmoi"):
        row = snapshot["checks"][key]
        if row["status"] == "ok":
            entries = row["data"].get("changes")
            if not isinstance(entries, list) or any(not isinstance(x, str) for x in entries):
                raise AuditError("Invalid live-check data")
    git = snapshot["checks"]["git"]
    if git["status"] == "ok" and not isinstance(git["data"].get("head"), str):
        raise AuditError("Invalid Git identity")
    missing = snapshot["checks"]["missing_runtimes"]
    if missing["status"] == "ok":
        entries = missing["data"].get("tools")
        if not isinstance(entries, list) or any(not isinstance(x, str) for x in entries):
            raise AuditError("Invalid missing-runtime data")
    restore = snapshot["checks"]["restore"]
    if restore["status"] == "ok":
        data = restore["data"]
        for key in ("gaps", "excluded"):
            if (not isinstance(data.get(key), dict) or
                    any(not isinstance(k, str) or not isinstance(v, list) or
                        any(not isinstance(x, str) for x in v) for k, v in data[key].items())):
                raise AuditError("Invalid restore coverage")
        for key in ("registered_manual", "unverified"):
            if not isinstance(data.get(key), list) or any(not isinstance(x, str) for x in data[key]):
                raise AuditError("Invalid restore coverage")
    return snapshot


def differences(old, new):
    if new["status"] != "ok" or old is None or old["status"] != "ok":
        return None
    if old["scope"] != new["scope"] or old["coverage"] != new["coverage"]:
        return None
    a, b = old["data"], new["data"]
    return {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
            "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}


def acceptance_errors(snapshot, baseline, allow_prefix_loss=False):
    issues = []
    for section in ("inventories", "checks"):
        for key, row in snapshot[section].items():
            if row["status"] == "error":
                issues.append(f"{key}: failed check")
            if baseline and baseline[section][key]["status"] == "ok" and row["status"] != "ok":
                issues.append(f"{key}: previously available coverage is now missing")
    if baseline:
        old, new = baseline["inventories"]["npm"], snapshot["inventories"]["npm"]
        if old["status"] == new["status"] == "ok" and not allow_prefix_loss:
            if set(old["coverage"]) - set(new["coverage"]):
                issues.append("npm: prefix coverage decreased; restore the prefix discovery or deliberately use accept --allow-prefix-loss")
    return sorted(set(issues))


def safe(value):
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def render(snapshot, baseline):
    lines = [f"Audit: {safe(snapshot['created_at'])}", f"Repository: {safe(short_path(Path(snapshot['repo'])))}"]
    lines.append(f"Accepted baseline: {safe(baseline['created_at'])}" if baseline else "No accepted baseline. Review this inventory, then run audit.sh accept.")
    lines.append("\nChanges since the accepted inventory:")
    for name in NAMES:
        row = snapshot["inventories"][name]
        lines.append(f"\n{LABELS[name]}:")
        if row["status"] != "ok":
            lines.append(f"  UNVERIFIED ({row['status']}): {safe(row['reason'])}. No removals inferred.")
            continue
        previous = baseline["inventories"][name] if baseline else None
        delta = differences(previous, row)
        lines.append(f"  {len(row['data'])} entries")
        if delta is None:
            lines.append("  No comparable baseline for this coverage. Review the current inventory:")
            if previous and previous["status"] == "ok":
                lost = sorted(set(previous["coverage"]) - set(row["coverage"]))
                if lost:
                    lines.append("  UNVERIFIED former prefixes: " + safe(", ".join(lost)) + ". No removals inferred.")
                elif previous["scope"] != row["scope"] or previous["coverage"] != row["coverage"]:
                    lines.append("  Observed scope changed. No removals inferred across scopes.")
            lines.extend(f"  = {safe(key)}: {safe(', '.join(row['data'][key]))}" for key in sorted(row["data"]))
        elif not any(delta.values()):
            lines.append("  No changes since the accepted inventory.")
        else:
            for key in delta["added"]:
                lines.append(f"  + {safe(key)}: {safe(', '.join(row['data'][key]))}")
            for key in delta["removed"]:
                lines.append(f"  - {safe(key)}: {safe(', '.join(previous['data'][key]))}")
            for key in delta["changed"]:
                lines.append(f"  ~ {safe(key)}: {safe(', '.join(previous['data'][key]))} -> {safe(', '.join(row['data'][key]))}")
    lines.append("\nRestore coverage (accepting an inventory does not clear these gaps):")
    restore = snapshot["checks"]["restore"]
    if restore["status"] != "ok":
        lines.append(f"  UNVERIFIED ({safe(restore['reason'])})")
    else:
        data = restore["data"]
        if not data["gaps"]:
            lines.append("  No undeclared tools found within verified coverage.")
        for label, names in data["gaps"].items():
            lines.append(f"  Missing restore declaration - {safe(label)}:")
            lines.extend(f"    ! {safe(name)}" for name in names)
        if data["registered_manual"]:
            lines.append("  Registered manual recipes (still manual restore steps):")
            lines.extend(f"    = {safe(name)}" for name in data["registered_manual"])
        if data["excluded"]:
            lines.append("  Deliberately excluded by policy:")
            for label, names in data["excluded"].items():
                lines.extend(f"    {safe(label)}: {safe(name)}" for name in names)
        lines.extend(f"  UNVERIFIED: {safe(item)}" for item in data["unverified"])
    lines.append("\nLive settings/source changes (always shown):")
    for key, title in (("git", "Git source"), ("chezmoi", "Managed home files")):
        row = snapshot["checks"][key]
        if row["status"] != "ok":
            lines.append(f"  {title}: UNVERIFIED ({safe(row['reason'])})")
        elif row["data"]["changes"]:
            lines.append(f"  {title}:")
            lines.extend(f"    {safe(v)}" for v in row["data"]["changes"])
        else:
            lines.append(f"  {title}: clean")
    missing = snapshot["checks"]["missing_runtimes"]
    if missing["status"] == "ok" and missing["data"]["tools"]:
        lines.append("  Missing requested runtimes: " + safe(", ".join(missing["data"]["tools"])))
    lines.append("\nScope: local Homebrew records, mise, active/all mise Node prefixes, default VS Code profile, ~/.local/bin metadata.")
    lines.append("npm removals refer to a prefix, not proof of a machine-wide uninstall. No remote/update checks.")
    return "\n".join(lines) + "\n"


def atomic_json(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".audit-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def locked(state):
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    if state.stat().st_mode & 0o077:
        raise AuditError("Audit state directory must be private (mode 700)")
    with (state / ".lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AuditError("Another audit or accept is running. Try again after it finishes.") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def load_pointer(state, kind, repo):
    path = state / f"{kind}.json"
    if not path.exists():
        return None
    pointer = read_json(path)
    name = pointer.get("snapshot") if isinstance(pointer, dict) else None
    if not isinstance(name, str) or not re.fullmatch(r"[0-9TZ-]+-[0-9a-f]{12}\.json", name):
        raise AuditError(f"Invalid {kind} pointer")
    snapshot = validate(read_json(state / "snapshots" / name))
    if snapshot["repo"] != str(repo):
        raise AuditError("Audit state belongs to a different repository. Use a separate --state-dir.")
    return name, snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("scan", "report", "accept", "record"), default="scan")
    parser.add_argument("--allow-prefix-loss", action="store_true",
                        help="With accept only, acknowledge intentionally removed npm prefix coverage")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "dotfiles-audit")
    args = parser.parse_args(argv)
    if args.allow_prefix_loss and args.action != "accept":
        parser.error("--allow-prefix-loss is only valid with accept")
    repo, state = args.repo.expanduser().resolve(), args.state_dir.expanduser().resolve()
    if state == repo or repo in state.parents:
        parser.error("State must be outside the Git repository")
    if not repo.is_dir():
        parser.error("Repository directory does not exist")
    if args.action == "record":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("Recording needs an interactive terminal. Run audit.sh record in your terminal.", file=sys.stderr)
            return 2
        uv = shutil.which("uv")
        if uv is None:
            print("uv is required for the Questionary checklist. Install it from the core Brewfile.", file=sys.stderr)
            return 2
        try:
            status = subprocess.run([
                uv, "run", "--no-config", "--no-env-file", "--no-python-downloads",
                "--python", sys.executable, "--script", "--locked",
                str(repo / "scripts/audit_record.py"), "--repo", str(repo), "--state-dir", str(state),
            ], check=False).returncode
            return 0 if status == 0 else 2
        except (OSError, KeyboardInterrupt):
            print("Recording cancelled or could not start.", file=sys.stderr)
            return 2
    try:
        with locked(state):
            base = load_pointer(state, "baseline", repo)
            baseline = base[1] if base else None
            if args.action == "scan":
                snapshot = validate(collect(repo))
                folder = state / "snapshots"
                folder.mkdir(mode=0o700, exist_ok=True)
                name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12] + ".json"
                atomic_json(folder / name, snapshot)
                atomic_json(state / "latest.json", {"snapshot": name})
                print(render(snapshot, baseline), end="")
                print(f"\nSaved snapshot: {short_path(folder / name)}")
                return 2 if acceptance_errors(snapshot, baseline) else 0
            latest = load_pointer(state, "latest", repo)
            if latest is None:
                raise AuditError("No completed snapshot. Run audit.sh first.")
            name, snapshot = latest
            if args.action == "report":
                print(render(snapshot, baseline), end="")
                return 2 if acceptance_errors(snapshot, baseline) else 0
            errors = acceptance_errors(snapshot, baseline, args.allow_prefix_loss)
            if errors:
                raise AuditError("Cannot accept incomplete coverage: " + ", ".join(errors) + ". Run a successful audit first.")
            atomic_json(state / "baseline.json", {"snapshot": name})
            print(f"Accepted inventory from {snapshot['created_at']}. No settings were captured or applied.")
            print("Unavailable collectors remain unverified. Live drift will still appear on every audit.")
            return 0
    except (OSError, ValueError, KeyError, TypeError, AuditError) as exc:
        message = str(exc) if isinstance(exc, AuditError) else f"Cannot read/write audit state ({type(exc).__name__})"
        print(f"Audit error: {safe(message)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
