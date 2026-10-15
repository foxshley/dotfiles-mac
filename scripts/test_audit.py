"""Tests use fake inventories and temporary state, never the real audit baseline."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit


def snapshot(repo):
    return {"schema": audit.SCHEMA, "created_at": "2026-10-15T00:00:00+00:00",
            "repo": str(repo),
            "inventories": {name: audit.result(data={"example": ["1"]}, scope=name) for name in audit.NAMES},
            "checks": {"git": audit.result(data={"head": "abc123", "changes": []}),
                       "chezmoi": audit.result(data={"changes": ["MM .config/fish/config.fish"]}),
                       "missing_runtimes": audit.result(data={"tools": []}),
                       "restore": audit.result(data={"gaps": {}, "excluded": {}, "registered_manual": [], "unverified": []})}}


class ComparisonTests(unittest.TestCase):
    def test_add_remove_upgrade(self):
        old = audit.result(data={"retired": ["1"], "updated": ["1"]})
        new = audit.result(data={"new": ["1"], "updated": ["2"]})
        self.assertEqual(audit.differences(old, new),
                         {"added": ["new"], "removed": ["retired"], "changed": ["updated"]})

    def test_failed_missing_or_different_scope_is_not_removal(self):
        old = audit.result(data={"keep": ["1"]}, scope="old")
        for new in (audit.result("error"), audit.result("unavailable"), audit.result(scope="new")):
            self.assertIsNone(audit.differences(old, new))
        self.assertIsNone(audit.differences(audit.result("unavailable"), audit.result()))

    def test_lost_npm_prefix_is_not_a_package_removal(self):
        base = snapshot(Path("/example"))
        base["inventories"]["npm"] = audit.result(data={"A :: tool": ["1"], "B :: npm": ["2"]}, coverage=["A", "B"])
        new = deepcopy(base)
        new["inventories"]["npm"] = audit.result(data={"B :: npm": ["2"]}, coverage=["B"])
        self.assertIsNone(audit.differences(base["inventories"]["npm"], new["inventories"]["npm"]))
        self.assertTrue(audit.acceptance_errors(new, base))
        self.assertEqual(audit.acceptance_errors(new, base, allow_prefix_loss=True), [])
        self.assertIn("UNVERIFIED former prefixes: A", audit.render(new, base))

    def test_unavailable_initially_allowed_but_lost_coverage_blocked(self):
        base = snapshot(Path("/example"))
        new = deepcopy(base)
        new["inventories"]["npm"] = audit.result("unavailable")
        self.assertEqual(audit.acceptance_errors(new, None), [])
        self.assertTrue(audit.acceptance_errors(new, base))
        new["inventories"]["npm"] = audit.result("error")
        self.assertTrue(audit.acceptance_errors(new, None))

    def test_live_drift_remains_visible_after_acceptance(self):
        current = snapshot(Path("/example"))
        report = audit.render(current, current)
        self.assertIn("MM .config/fish/config.fish", report)
        self.assertIn("No changes since the accepted inventory", report)

    def test_initial_inventory_is_reviewable_before_accepting(self):
        current = snapshot(Path("/example"))
        current["inventories"]["npm"]["data"] = {"node-prefix :: example-tool": ["2.1"]}
        self.assertIn("= node-prefix :: example-tool: 2.1", audit.render(current, None))

    def test_malformed_snapshot_cannot_be_accepted(self):
        current = snapshot(Path("/example"))
        del current["checks"]["chezmoi"]["data"]["changes"]
        with self.assertRaises(audit.AuditError):
            audit.validate(current)

    def test_schema_one_baseline_upgrades_in_memory_only(self):
        current = snapshot(Path("/example"))
        current["schema"] = 1
        del current["inventories"]["local_launchers"]
        del current["inventories"]["manual"]
        del current["checks"]["restore"]
        before = deepcopy(current)
        upgraded = audit.validate(current)
        self.assertEqual(current, before)
        self.assertEqual(upgraded["schema"], 2)
        self.assertEqual(upgraded["inventories"]["local_launchers"]["status"], "unavailable")

    def test_restore_gaps_survive_identical_accepted_inventory(self):
        current = snapshot(Path("/example"))
        current["checks"]["restore"]["data"]["gaps"] = {"Homebrew formulae": ["zeroclaw"]}
        report = audit.render(current, current)
        self.assertIn("No changes since the accepted inventory", report)
        self.assertIn("! zeroclaw", report)
        self.assertEqual(audit.acceptance_errors(current, current), [])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "repo"
        self.repo.mkdir()
        self.state = Path(self.temp.name) / "state"

    def run_cli(self, action, data=None):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch.object(audit, "collect", return_value=data) as collector:
                status = audit.main(["--repo", str(self.repo), "--state-dir", str(self.state), action])
        return status, collector.call_count

    def test_scans_never_advance_baseline_and_accept_does_not_recollect(self):
        current = snapshot(self.repo)
        self.assertEqual(self.run_cli("scan", current)[0], 0)
        self.assertFalse((self.state / "baseline.json").exists())
        latest = audit.read_json(self.state / "latest.json")
        self.assertEqual(self.run_cli("accept"), (0, 0))
        self.assertEqual(audit.read_json(self.state / "baseline.json"), latest)
        current["inventories"]["npm"]["data"]["new"] = ["2"]
        self.run_cli("scan", current)
        self.run_cli("scan", current)
        self.assertEqual(audit.read_json(self.state / "baseline.json"), latest)
        _, new = audit.load_pointer(self.state, "latest", self.repo)
        _, old = audit.load_pointer(self.state, "baseline", self.repo)
        self.assertEqual(audit.differences(old["inventories"]["npm"], new["inventories"]["npm"])["added"], ["new"])

    def test_failed_latest_blocks_accept_and_preserves_previous(self):
        current = snapshot(self.repo)
        self.run_cli("scan", current)
        self.run_cli("accept")
        before = (self.state / "baseline.json").read_bytes()
        current["inventories"]["brew_formulae"] = audit.result("error", reason="unreadable")
        self.assertEqual(self.run_cli("scan", current)[0], 2)
        self.assertEqual(self.run_cli("accept")[0], 2)
        self.assertEqual((self.state / "baseline.json").read_bytes(), before)

    def test_lock_excludes_other_run_and_releases_on_failure(self):
        with self.assertRaises(RuntimeError):
            with audit.locked(self.state):
                with self.assertRaises(audit.AuditError):
                    with audit.locked(self.state):
                        self.fail("second lock acquired")
                raise RuntimeError("simulate aborted operation")
        with audit.locked(self.state):
            pass

    def test_failed_atomic_replace_preserves_old_pointer(self):
        self.state.mkdir(mode=0o700)
        pointer = self.state / "baseline.json"
        audit.atomic_json(pointer, {"old": True})
        with patch.object(audit.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                audit.atomic_json(pointer, {"new": True})
        self.assertEqual(audit.read_json(pointer), {"old": True})
        self.assertEqual(list(self.state.glob(".audit-*")), [])

    def test_invalid_pointer_or_wrong_repo_is_rejected(self):
        self.run_cli("scan", snapshot(self.repo))
        with self.assertRaises(audit.AuditError):
            audit.load_pointer(self.state, "latest", self.repo / "other")
        audit.atomic_json(self.state / "latest.json", {"snapshot": "../../outside.json"})
        self.assertEqual(self.run_cli("accept")[0], 2)

    def test_private_state_permissions(self):
        self.run_cli("scan", snapshot(self.repo))
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state / "latest.json").stat().st_mode & 0o777, 0o600)


class CollectorTests(unittest.TestCase):
    def test_local_homebrew_records_require_no_command_and_missing_receipt_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cellar = root / "Cellar"
            version = cellar / "example/1.2_1"
            version.mkdir(parents=True)
            (version / "INSTALL_RECEIPT.json").write_text("{}")
            cask = root / "Caskroom/app"
            (cask / "2.0").mkdir(parents=True)
            (cask / ".metadata").mkdir()
            (cask / ".metadata/INSTALL_RECEIPT.json").write_text("{}")
            with patch.object(audit, "homebrew_root", return_value=root), patch.dict(audit.os.environ, {}, clear=True):
                self.assertEqual(audit.brew_inventory("formulae")["data"], {"example": ["1.2_1"]})
                self.assertEqual(audit.brew_inventory("casks")["data"], {"app": ["2.0"]})
                (version / "INSTALL_RECEIPT.json").unlink()
                self.assertEqual(audit.attempt(lambda: audit.brew_inventory("formulae"))["status"], "error")

    def test_npm_collects_inactive_prefix_and_ignores_manifest_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "node/22"
            package = prefix / "lib/node_modules/@example/tool"
            package.mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"name": "@example/tool", "version": "1.2", "privateToken": "DO_NOT_COPY"}))
            records = {"node": [{"installed": True, "install_path": str(prefix)}]}
            with patch.object(audit.shutil, "which", return_value=None):
                data = audit.npm_inventory(records)
            self.assertEqual(list(data["data"].values()), [["1.2"]])
            self.assertNotIn("DO_NOT_COPY", json.dumps(data))

    def test_command_errors_do_not_save_raw_diagnostics(self):
        failed = audit.subprocess.CompletedProcess([], 1, stdout="", stderr="private-token=DO_NOT_COPY")
        with patch.object(audit.subprocess, "run", return_value=failed):
            row = audit.attempt(lambda: audit.command(["example"], "/"))
        self.assertEqual(row["status"], "error")
        self.assertNotIn("DO_NOT_COPY", str(row))

    def test_malformed_npm_manifest_is_a_collector_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)
            package = prefix / "lib/node_modules/tool"
            package.mkdir(parents=True)
            (package / "package.json").write_text("[]")
            records = {"node": [{"installed": True, "install_path": str(prefix)}]}
            with patch.object(audit.shutil, "which", return_value=None):
                self.assertEqual(audit.attempt(lambda: audit.npm_inventory(records))["status"], "error")

    def test_launcher_inventory_records_metadata_without_reading_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            binaries = home / ".local/bin"
            binaries.mkdir(parents=True)
            wrapper = binaries / "custom-tool"
            wrapper.write_text("#!/bin/sh\nTOKEN=DO_NOT_COPY\n")
            wrapper.chmod(0o755)
            (binaries / "link-tool").symlink_to(wrapper)
            (binaries / "missing-tool").symlink_to(home / "absent")
            (binaries / "notes.txt").write_text("not executable")
            with patch.object(audit.Path, "home", return_value=home):
                row = audit.local_launchers()
            self.assertEqual(set(row["data"]), {"custom-tool", "link-tool", "missing-tool"})
            self.assertNotIn("DO_NOT_COPY", json.dumps(row))
            self.assertIn("missing target", row["data"]["missing-tool"][0])


class RestoreCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        manifests = self.repo / "manifests"
        manifests.mkdir(parents=True)
        (manifests / "Brewfile.core").write_text('brew "tracked"\nbrew "vendor/tap/tapped", trusted: true\n')
        (manifests / "Brewfile.apps").write_text('cask "tracked-app"\n')
        (manifests / "npm-tools.txt").write_text('@scope/tracked@1.2\n')
        (manifests / "vscode-extensions.txt").write_text('vendor.extension\n')
        config = self.repo / "dot_config/mise"
        config.mkdir(parents=True)
        (config / "config.toml").write_text('[tools]\nnode="lts"\n')
        self.registry = manifests / "installations.toml"
        self.registry.write_text('''schema=1
[manual.hermes]
executables=["hermes"]
marker=".hermes/hermes-agent/pyproject.toml"
source="https://example.org/install"
install="official installer"
update="hermes update"
verify="hermes doctor"
[excluded.brew_formulae]
legacy="Explicitly excluded by policy"
[excluded.npm]
npm="Provided by Node"
''')
        marker = self.root / ".hermes/hermes-agent/pyproject.toml"
        marker.parent.mkdir(parents=True)
        marker.write_text("")
        self.marker = marker
        self.inventories = {key: audit.result() for key in audit.NAMES}
        row = self.inventories["brew_formulae"]
        row["data"] = {name: ["1"] for name in ["tracked", "tapped", "dependency", "zeroclaw", "smartmontools", "legacy"]}
        row.update(requested=["tracked", "tapped", "zeroclaw", "smartmontools", "legacy"], request_unknown=[])
        row = self.inventories["brew_casks"]
        row.update(data={"localsend": ["1"]}, requested=["localsend"], request_unknown=[])
        self.inventories["npm"]["data"] = {"prefix :: @scope/tracked": ["1.2"], "prefix :: openclaw": ["2"], "prefix :: npm": ["3"]}
        self.inventories["vscode"]["data"] = {"vendor.extension": ["1"]}
        self.inventories["mise_global"]["data"] = {"node": ["lts"]}
        self.inventories["local_launchers"]["data"] = {"hermes": ["file"], "unregistered": ["file"]}

    def coverage(self):
        with patch.object(audit.Path, "home", return_value=self.root):
            return audit.restore_coverage(self.repo, self.inventories)

    def test_direct_packages_and_launchers_remain_gaps_until_declared(self):
        row = self.coverage()
        gaps = row["data"]["gaps"]
        self.assertEqual(gaps["Homebrew formulae"], ["smartmontools", "zeroclaw"])
        self.assertEqual(gaps["Homebrew casks"], ["localsend"])
        self.assertEqual(gaps["npm globals by prefix"], ["openclaw"])
        self.assertEqual(gaps["Local launchers (names and metadata)"], ["unregistered"])
        self.assertEqual(row["data"]["registered_manual"], ["hermes: manual recipe 'hermes'"])

    def test_declaring_a_recipe_clears_gap_without_changing_software(self):
        with (self.repo / "manifests/Brewfile.core").open("a") as f:
            f.write('brew "zeroclaw"\n')
        self.assertNotIn("zeroclaw", self.coverage()["data"]["gaps"]["Homebrew formulae"])

    def test_unused_brewfile_cannot_hide_a_restore_gap(self):
        (self.repo / "manifests/Brewfile.backup").write_text('brew "zeroclaw"\n')
        self.assertIn("zeroclaw", self.coverage()["data"]["gaps"]["Homebrew formulae"])

    def test_missing_marker_keeps_manual_tool_unverified(self):
        self.marker.unlink()
        row = self.coverage()
        self.assertEqual(row["data"]["registered_manual"], [])
        self.assertIn("hermes", row["data"]["gaps"]["Local launchers (names and metadata)"])

    def test_changed_global_request_is_a_restore_gap(self):
        self.inventories["mise_global"]["data"]["node"] = ["22"]
        self.assertIn("Global mise requests", self.coverage()["data"]["gaps"])

    def test_missing_collector_is_unverified_not_an_empty_install(self):
        self.inventories["npm"] = audit.result("error", reason="failed")
        row = self.coverage()
        self.assertNotIn("npm globals by prefix", row["data"]["gaps"])
        self.assertIn("npm globals by prefix", row["data"]["unverified"])

    def test_unknown_homebrew_request_flags_are_not_guessed(self):
        self.inventories["brew_formulae"]["request_unknown"] = ["mystery"]
        self.assertTrue(any("mystery" in item for item in self.coverage()["data"]["unverified"]))

    def test_unsupported_brewfile_is_not_executed(self):
        (self.repo / "manifests/Brewfile.core").write_text('brew(variable)\n')
        with self.assertRaises(audit.AuditError):
            self.coverage()

    def test_exclusion_needs_a_reason(self):
        self.registry.write_text('schema=1\n[excluded.npm]\nopenclaw=""\n')
        with self.assertRaises(audit.AuditError):
            self.coverage()

    def test_registered_manual_tool_is_observed_without_running_it(self):
        with patch.object(audit.Path, "home", return_value=self.root):
            row = audit.manual_inventory(self.repo)
        self.assertEqual(row["data"], {"hermes": ["present (installation marker only)"]})

    def test_duplicate_manual_ownership_is_rejected(self):
        with self.registry.open("a") as f:
            f.write('''\n[manual.duplicate]
executables=["hermes"]
marker="marker"
source="source"
install="install"
update="update"
verify="verify"
''')
        with self.assertRaises(audit.AuditError):
            self.coverage()


if __name__ == "__main__":
    unittest.main()
