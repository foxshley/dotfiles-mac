"""Recording tests edit only temporary manifests and never install software."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import audit
import audit_record as record


class FakeQuestionary:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.defaults = []

    def Choice(self, title, **kwargs):
        return (title, kwargs)

    def Separator(self, label):
        return label

    def ask(self):
        answer = next(self.answers)
        return answer() if callable(answer) else answer

    def select(self, *args, **kwargs):
        return self

    checkbox = text = select

    def confirm(self, *args, **kwargs):
        self.defaults.append(kwargs["default"])
        return self


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        manifests = self.repo / "manifests"
        manifests.mkdir(parents=True)
        (self.repo / ".git").mkdir()
        (manifests / "Brewfile.core").write_text('# Keep this comment\nbrew "git"\n')
        (manifests / "Brewfile.apps").write_text('cask "visual-studio-code"\n')
        (manifests / "npm-tools.txt").write_text('# Optional tools\n@scope/existing\n')
        (manifests / "vscode-extensions.txt").write_text('vendor.existing\n')
        (manifests / "installations.toml").write_text('schema=1\n\n[excluded.npm]\nnpm="Provided by Node"\n')
        config = self.repo / "dot_config/mise"
        config.mkdir(parents=True)
        (config / "config.toml").write_text('[tools]\nnode="lts"\n')
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        (self.state / "baseline.json").write_text('"baseline sentinel"')
        (self.state / "latest.json").write_text('"latest sentinel"')
        self.originals = record.capture(self.repo)
        self.formula = record.Item("brew_formulae", "zeroclaw")
        self.cask = record.Item("brew_casks", "localsend")
        self.npm = record.Item("npm", "@scope/tool")
        self.extension = record.Item("vscode", "vendor.new")
        self.launcher = record.Item("local_launchers", "custom-launcher")
        candidates = [self.formula, self.cask, self.npm, self.extension, self.launcher]
        gaps = {}
        for item in candidates:
            gaps.setdefault(audit.LABELS[item.kind], []).append(item.name)
        self.snapshot = {"checks": {"restore": audit.result(data={"gaps": gaps})}, "inventories": {}}
        for item in [self.formula, self.cask]:
            location = self.root / item.kind
            self.snapshot["inventories"][item.kind] = audit.result(data={item.name: ["1.0"]}, scope=str(location))
            receipt = (location / item.name / ("1.0/INSTALL_RECEIPT.json" if item.kind == "brew_formulae" else ".metadata/INSTALL_RECEIPT.json"))
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"source": {"tap": "homebrew/core" if item.kind == "brew_formulae" else "homebrew/cask"}}))

    def run_prompt(self, answers):
        fake = FakeQuestionary(answers)
        output = io.StringIO()
        with redirect_stdout(output):
            result = record.prompt(self.repo, self.state, self.originals, self.snapshot, fake)
        return result, output.getvalue(), fake

    def assert_original(self):
        for relative, (data, _) in self.originals.items():
            self.assertEqual((self.repo / relative).read_bytes(), data)

    def assert_inventory_untouched(self):
        self.assertEqual((self.state / "baseline.json").read_text(), '"baseline sentinel"')
        self.assertEqual((self.state / "latest.json").read_text(), '"latest sentinel"')

    def test_cancel_and_empty_selection_write_nothing(self):
        for answers in [[None], ["cancel"], ["restore", []], ["restore", None]]:
            self.run_prompt(answers)
            self.assert_original()
        self.assertFalse((self.state / "record-backups").exists())
        self.assert_inventory_untouched()

    def test_preview_decline_preserves_everything(self):
        _, output, fake = self.run_prompt(["restore", [self.formula], False])
        self.assertIn('+brew "zeroclaw"', output)
        self.assertNotIn('+brew \\"zeroclaw', output)
        self.assertEqual(fake.defaults, [False])
        self.assert_original()
        self.assert_inventory_untouched()

    def test_selected_packages_go_to_correct_manifests(self):
        self.run_prompt(["restore", [self.formula, self.cask, self.npm, self.extension], True])
        self.assertIn('brew "zeroclaw"', (self.repo / "manifests/Brewfile.core").read_text())
        self.assertIn('# Keep this comment', (self.repo / "manifests/Brewfile.core").read_text())
        self.assertIn('cask "localsend"', (self.repo / "manifests/Brewfile.apps").read_text())
        self.assertIn('@scope/tool', (self.repo / "manifests/npm-tools.txt").read_text())
        self.assertIn('vendor.new', (self.repo / "manifests/vscode-extensions.txt").read_text())
        self.assert_inventory_untouched()
        self.assertEqual((self.repo / "manifests/Brewfile.core").stat().st_mode & 0o777, 0o644)
        backups = list((self.state / "record-backups").glob('*/*'))
        self.assertEqual(len(backups), 4)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in backups))

    def test_exclusions_preserve_tables_comments_and_unicode_reasons(self):
        reason = 'Project-only "test" \\ restore later 🙂'
        self.run_prompt(["exclude", [self.npm, self.launcher, self.formula], reason, True])
        policy = tomllib.loads((self.repo / "manifests/installations.toml").read_text())
        self.assertEqual(policy['excluded']['npm']['npm'], 'Provided by Node')
        self.assertEqual(policy['excluded']['npm']['@scope/tool'], reason)
        self.assertEqual(policy['excluded']['brew_formulae']['zeroclaw'], reason)
        self.assertEqual(policy['excluded']['local_launchers']['custom-launcher'], reason)
        self.assert_inventory_untouched()

    def test_blank_exclusion_is_rejected_even_without_ui_validation(self):
        with self.assertRaises(audit.AuditError):
            record.plan(self.repo, self.originals, [self.formula], "exclude", self.snapshot, " ")
        self.assert_original()

    def test_local_launcher_cannot_get_an_invented_installer(self):
        with self.assertRaises(audit.AuditError):
            record.plan(self.repo, self.originals, [self.launcher], "restore", self.snapshot)

    def test_third_party_tap_is_preserved(self):
        root = Path(self.snapshot['inventories']['brew_formulae']['scope'])
        receipt = root / 'zeroclaw/1.0/INSTALL_RECEIPT.json'
        receipt.write_text(json.dumps({'source': {'tap': 'vendor/tools'}}))
        changes = record.plan(self.repo, self.originals, [self.formula], "restore", self.snapshot)
        self.assertIn(b'tap "vendor/tools"', changes[0].after)
        self.assertIn(b'brew "vendor/tools/zeroclaw"', changes[0].after)

    def test_unknown_tap_does_not_guess_provenance(self):
        root = Path(self.snapshot['inventories']['brew_formulae']['scope'])
        (root / 'zeroclaw/1.0/INSTALL_RECEIPT.json').write_text('{}')
        with self.assertRaises(audit.AuditError):
            record.plan(self.repo, self.originals, [self.formula], "restore", self.snapshot)

    def test_changes_in_another_manifest_during_confirmation_abort(self):
        path = self.repo / "manifests/installations.toml"
        changed = path.read_bytes() + b'# A manual edit\n'
        def user_edit():
            path.write_bytes(changed)
            return True
        with self.assertRaises(audit.AuditError):
            self.run_prompt(["restore", [self.formula], user_edit])
        self.assertEqual(path.read_bytes(), changed)
        self.assertNotIn('zeroclaw', (self.repo / "manifests/Brewfile.core").read_text())

    def test_stale_target_aborts_before_any_write(self):
        changes = record.plan(self.repo, self.originals, [self.formula], "restore", self.snapshot)
        changes[0].path.write_text("manual edit\n")
        with self.assertRaises(audit.AuditError):
            record.apply_changes(changes, self.state)
        self.assertEqual(changes[0].path.read_text(), "manual edit\n")
        self.assertFalse((self.state / "record-backups").exists())

    def test_interrupted_multifile_write_rolls_back_completed_files(self):
        changes = record.plan(self.repo, self.originals, [self.formula, self.cask], "restore", self.snapshot)
        original_replace = record.replace_file
        target = self.repo / 'manifests/Brewfile.core'
        failed = False
        def fail_after_replace(path, data, mode):
            nonlocal failed
            original_replace(path, data, mode)
            if path == target and not failed:
                failed = True
                raise OSError("simulated failure after replacement")
        with patch.object(record, 'replace_file', side_effect=fail_after_replace):
            with self.assertRaises(audit.AuditError):
                record.apply_changes(changes, self.state)
        self.assert_original()
        self.assert_inventory_untouched()

    def test_repository_lock_blocks_other_recorders(self):
        with patch.object(audit, 'command', return_value=str(self.repo / '.git')):
            with record.repository_lock(self.repo):
                with self.assertRaises(audit.AuditError):
                    with record.repository_lock(self.repo):
                        self.fail('second lock acquired')
            with record.repository_lock(self.repo):
                pass

    def test_manifest_symlink_is_not_followed(self):
        path = self.repo / 'manifests/Brewfile.core'
        outside = self.root / 'outside'
        outside.write_text('private')
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(audit.AuditError):
            record.capture(self.repo)

    def test_control_sequences_are_escaped_without_escaping_quotes(self):
        self.assertEqual(record.visible_line('+brew "zeroclaw"'), '+brew "zeroclaw"')
        self.assertNotIn('\x1b', record.visible_line('\x1b[2Jclear'))

    def test_noninteractive_entry_does_not_start_dependency_setup(self):
        with patch.object(audit.sys.stdin, 'isatty', return_value=False), patch.object(audit.subprocess, 'run') as run:
            self.assertEqual(audit.main(['--repo', str(self.repo), '--state-dir', str(self.state), 'record']), 2)
            run.assert_not_called()
        self.assert_inventory_untouched()


if __name__ == '__main__':
    unittest.main()
