# Mac development dotfiles

This repository exports the portable parts of an Apple Silicon Mac development environment. It uses Homebrew Bundle for software, chezmoi for configuration, mise for runtime versions, and uv for Python project environments. The global Node request follows the latest LTS line; the global Python request is 3.14. Project version files and lockfiles remain with their repositories. Miniforge and old project-specific Node installations are outside the baseline.

## Restore on a fresh Mac

1. Install the macOS Command Line Tools (`xcode-select --install`), then clone this repository. Keep project repositories and protected backups separate.
2. Inspect `manifests/Brewfile.core`, `manifests/Brewfile.apps`, and the configuration source. Set `DOTFILES_GIT_NAME` and `DOTFILES_GIT_EMAIL` if this machine should have a Git identity at first apply. Set `DOTFILES_GIT_SIGNINGKEY` only after importing the matching private key. These values populate the initial chezmoi config and are not committed.
3. Run `bash scripts/bootstrap.sh apply`. To include the listed GUI apps, use `DOTFILES_INCLUDE_APPS=1 bash scripts/bootstrap.sh apply`. The script installs core packages, copies existing managed files to `~/.local/state/dotfiles-backups/`, applies the source, installs mise runtimes, and restores Fisher plugins and Tide preferences. It stops if Command Line Tools are missing.
4. Run `bash scripts/verify.sh`. After restoring a signing key, update `~/.config/chezmoi/chezmoi.toml` with the Git data, apply again, and verify a signed commit in a disposable repository.
5. Complete account sign-ins, SSH/GPG key recovery, VS Code extension selection, Neovim Mason tools, Android/Unity SDKs and licenses, OrbStack initialization, and app-specific integrations. See `manifests/README.md` and `manifests/manual-installers.md`. None of those credentials or large SDK/data directories are stored here.

On an existing Mac, run `bash scripts/bootstrap.sh preview` first. It lists changed paths without printing current file contents; this matters because the old OpenCode file contains a credential. Review the repository source and inspect any specific live-file differences locally before applying. Apply mode makes a private, timestamped copy of existing managed files before overwriting them. The setup should be rerunnable; the verifier tests a second apply in an isolated temporary home. To make Fish the login shell, register its installed path in `/etc/shells` and use `chsh` after confirming it starts correctly.

## Updating

Edit the source files in this repository, review `chezmoi --source="$(pwd)" status`, then apply. A full `chezmoi diff` can print old credentials from the target Mac, so handle its output locally. Update the global Node LTS deliberately with `mise upgrade node`; a project-specific version file overrides the global request. For Python projects, use mise to select the interpreter and `uv sync` / `uv run` to manage the project's `.venv` and dependencies. The uv configuration disables automatic Python downloads so an absent mise Python is an error rather than a silent second installation.

The package lists are curated, not a copy of every installed formula or application. `manifests/packages-optional.md` records candidates that need project-by-project review. A particular ML project may add Conda when its own manifest or dependencies require it; there is no Conda initialization in these shell files.

## Boundaries

This source must never contain SSH/GPG private keys, tokens, authentication databases, project `.env` files, shell history, container volumes, IDE caches, package caches, or downloaded SDKs. The original OpenCode configuration held a Context7 API key; this repository contains no copy of it. Restore any needed integration by supplying a new credential through its supported local configuration or environment mechanism after review. Review `git status` and the staged diff before committing or publishing this repository.

Restore SSH keys and host trust from a protected backup, then test required hosts. Restore the GPG signing key before setting `git_signingkey`; GnuPG, pinentry, and the portable agent settings are in the core restore. Codex credentials, sessions, trusted projects, and app-specific integrations must be re-established inside Codex. The OpenCode source omits Context7 and CodeGraph integrations: the former had an embedded credential, and the latter pointed to a separately installed executable.

The first restore has not been tested on a clean Mac. `scripts/verify.sh` validates configuration syntax and a repeatable chezmoi apply in a temporary home; a real fresh-account test is still required for package availability, app licensing, external installations, and user authentication.
