# Mac development dotfiles

This repo holds the parts of my Apple Silicon Mac development setup that I can carry to another machine. Homebrew installs software, chezmoi manages configuration files, mise manages language runtimes, and uv manages Python project environments.

The global mise config uses the latest Node LTS, Python 3.14, Ruby 3.4, and the latest stable Rust. It also lists Bun, Go, and Zig. Projects keep their own version files and lockfiles. Old project-specific Node versions and Miniforge are not part of this setup.

## Restore on a fresh Mac

1. Install the macOS Command Line Tools with `xcode-select --install`. Copy or clone this repo to `~/dotfiles`. Make sure the repo is backed up or available through a Git remote before you depend on it for recovery.
2. Review `manifests/Brewfile.core`, `manifests/Brewfile.apps`, and the managed configuration. Before the first apply, you can set `DOTFILES_GIT_NAME` and `DOTFILES_GIT_EMAIL` for your Git identity. Set `DOTFILES_GIT_SIGNINGKEY` only after restoring the matching private key. These values go into the local chezmoi config, not the repo. An existing chezmoi config is left alone.
3. Run `bash scripts/bootstrap.sh apply`. To install the listed GUI apps too, run `DOTFILES_INCLUDE_APPS=1 bash scripts/bootstrap.sh apply`. The script installs missing core packages without upgrading existing ones, backs up existing managed files to `~/.local/state/dotfiles-backups/`, applies the configuration, installs the mise runtimes, and restores Fish plugins and Tide settings.
4. Run `bash scripts/verify.sh`. If you use signed commits, restore your GPG key, check the Git settings in `~/.config/chezmoi/chezmoi.toml`, apply again, and test a signed commit in a temporary repo.
5. Finish the parts that need your accounts or project choices: SSH host trust, app sign-ins, VS Code extensions, Neovim Mason tools, Android and Unity SDKs, OrbStack, and other integrations. See `manifests/README.md` and `manifests/manual-installers.md`.

On an existing Mac, start with `bash scripts/bootstrap.sh preview`. It shows which paths would change without printing their contents. Review differences in the live files locally before applying. Apply mode makes a private, timestamped backup of existing managed files. If you want Fish as your login shell, confirm that it starts correctly, register its path in `/etc/shells`, then use `chsh`.

The core package list covers tools I use across Macs. GUI apps are optional, and `manifests/packages-optional.md` holds other tools to review for each project. Conda belongs in an ML project's setup if that project needs it.

## Keeping it up to date

To edit a managed file and apply it, use its path in your home directory. For example:

```bash
chezmoi --source="$HOME/dotfiles" edit --apply "$HOME/.config/mise/config.toml"
```

To install a runtime you added to that config:

```bash
mise install
```

To see which managed files would change:

```bash
chezmoi --source="$HOME/dotfiles" status
```

To apply changes you made directly in `~/dotfiles`:

```bash
chezmoi --source="$HOME/dotfiles" apply
```

A full `chezmoi diff` may print credentials from an old live file, so review it privately.

To add a global runtime from any directory, replace `TOOL@VERSION` with the tool and version you want:

```bash
mise use -g TOOL@VERSION
```

The `-g` matters. Without it, mise may create a project config in your current directory. If it creates `~/dotfiles/mise.toml` by mistake, Git and chezmoi will ignore that file.

To copy the updated global mise config back into dotfiles:

```bash
chezmoi --source="$HOME/dotfiles" add "$HOME/.config/mise/config.toml"
```

To review that change before committing it:

```bash
git -C "$HOME/dotfiles" diff -- dot_config/mise/config.toml
```

To update the global Node LTS when you choose to:

```bash
mise upgrade node
```

Mise reads project version files for Node, Python, and Rust, so a project can use a different version.

To install a Python project's dependencies, run this from the project directory:

```bash
uv sync
```

To run a command in that project's environment:

```bash
uv run COMMAND
```

Mise selects the Python interpreter. uv manages the project's `.venv` and does not download another Python automatically, so a missing mise Python shows up as an error.

## What stays out

Do not commit private keys, tokens, authentication data, project `.env` files, shell history, caches, container volumes, or downloaded SDKs. Check `git status` and the staged diff for sensitive data before committing or publishing.

Restore SSH keys and host trust from a protected backup. GnuPG, pinentry, and their portable settings are included, but the signing key itself is not. Sign back into Codex and set up its trusted projects and integrations again. This repo does not restore sessions. OpenCode's current config contains a Context7 API key, so it is deliberately unmanaged. Set up that credential separately if you still need it. CodeGraph also needs its own executable.

The verifier checks configuration syntax, applies chezmoi in a temporary home, and confirms that another apply would make no changes. This repo has not yet been tested on a clean Mac. A real fresh-account restore is still needed to confirm package availability, app licensing, external installers, and authentication.
