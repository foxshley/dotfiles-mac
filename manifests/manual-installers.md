# Manual and vendor-managed installations

These are not ordinary Homebrew packages. Confirm current use, download source, license, and project compatibility before reinstalling.

- **Unity Editor 6000.5.4f1:** Unity Hub is in `Brewfile.apps`; install the editor and required modules through Hub. Licenses and project data are separate.
- **Godot:** app observed in `~/Applications`; version was not established. Choose an official distribution if needed.
- **Meteor 3.4.1:** installed under `~/.meteor`; no current project requirement was established. Restore only for Meteor projects.
- **Claude Code:** native/user-local installation observed under `~/.local/share/claude` with a `~/.local/bin` symlink. Use the vendor installer; sign in separately.
- **CodeGraph 1.5.0:** both standalone and npm global installation observed; avoid duplicate installs. Decide on one current supported installation method if still used.
- **Java:** selected runtime was JetBrains Runtime 11 via Android Studio; Android Studio also bundled JBR 21. Do not export that transient selection as a general Java runtime. Select a JDK per Android/project need.
- **Android SDK:** package IDs are recorded separately; SDK binaries, emulator images, licenses, debug keystore, and emulator state are not dotfiles.
- **Miniforge:** excluded from baseline. Existing install may support a particular ML project, but no such dependency was established from the inspected base.
- **AI apps/services:** Claude and ChatGPT desktop applications were present. Installation does not restore account access or local session data.
