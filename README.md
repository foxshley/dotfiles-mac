# Dotfiles

My development setup for an Apple Silicon Mac. Homebrew installs software, chezmoi manages configuration, mise selects language runtimes, and uv manages Python project environments.

## Set up a Mac

Install the macOS Command Line Tools with `xcode-select --install`, then copy or clone this repo to `~/dotfiles`. Keep a backup of the repo or put it on a Git remote before relying on it for recovery.

Review the [core packages](manifests/Brewfile.core), [optional GUI apps](manifests/Brewfile.apps), and managed configuration before applying. On an existing Mac, run `bash "$HOME/dotfiles/scripts/bootstrap.sh" preview` first. It lists paths that would change without printing their contents.

Before the first apply, you can set `DOTFILES_GIT_NAME` and `DOTFILES_GIT_EMAIL`. Set `DOTFILES_GIT_SIGNINGKEY` only after restoring its private key. These values stay in the local chezmoi config. The bootstrap leaves an existing chezmoi config alone.

To install the core setup:

```bash
bash "$HOME/dotfiles/scripts/bootstrap.sh" apply
```

To include the GUI apps:

```bash
DOTFILES_INCLUDE_APPS=1 bash "$HOME/dotfiles/scripts/bootstrap.sh" apply
```

The bootstrap installs missing packages without upgrading existing ones. It backs up managed files to `~/.local/state/dotfiles-backups/`, applies the configuration, installs the mise runtimes, and restores Fish plugins and Tide settings.

To check the result:

```bash
bash "$HOME/dotfiles/scripts/verify.sh"
```

If you use signed commits, check the Git settings in `~/.config/chezmoi/chezmoi.toml` and test a signed commit in a temporary repo.

Finish the parts that need your accounts or project choices, including SSH host trust, app sign-ins, editor extensions, Android and Unity SDKs, and OrbStack. See the [software notes](manifests/README.md) and [manual installers](manifests/manual-installers.md). To use Fish as your login shell, confirm that it starts correctly, add its path to `/etc/shells`, then run `chsh`.

[Other packages](manifests/packages-optional.md) need a project-by-project decision. Conda belongs in an ML project's setup if that project needs it.

## Keeping it up to date

### Dotfiles

To edit and apply a managed file, use its path in your home directory. For example:

```bash
chezmoi --source="$HOME/dotfiles" edit --apply "$HOME/.config/fish/config.fish"
```

To see which managed files differ from the repo:

```bash
chezmoi --source="$HOME/dotfiles" status
```

To apply changes made directly in `~/dotfiles`:

```bash
chezmoi --source="$HOME/dotfiles" apply
```

A full `chezmoi diff` may print credentials from an old live file, so review it privately.

### Runtimes

The [mise config](dot_config/mise/config.toml) tracks the latest Node LTS and stable Rust, plus Python 3.14, Ruby 3.4, Bun, Go, and Zig. Mise reads project version files for Node, Python, and Rust, so those projects can override the global defaults. Old project-specific Node versions and Miniforge are outside this setup.

To add a global runtime from any directory, replace `TOOL@VERSION` with your choice:

```bash
mise use -g TOOL@VERSION
```

The `-g` matters. Without it, mise may write a project config in the current directory. Git and chezmoi ignore a `mise.toml` accidentally created at the root of this repo.

To copy the updated global config back into dotfiles:

```bash
chezmoi --source="$HOME/dotfiles" add "$HOME/.config/mise/config.toml"
```

Review the change in Git before committing it. If you edit the managed mise config directly instead, apply it with chezmoi and install the requested runtimes:

```bash
mise install
```

To update the global Node LTS when you choose to:

```bash
mise upgrade node
```

### Python projects

Mise selects Python. uv manages each project's `.venv` and dependencies. uv will not download a separate Python automatically, so a missing mise interpreter shows up as an error.

From a Python project directory, install its dependencies:

```bash
uv sync
```

To run a command in that project's environment:

```bash
uv run COMMAND
```

## What stays out

Do not commit private keys, tokens, authentication data, project `.env` files, shell history, caches, container volumes, or downloaded SDKs. Check the staged diff before committing or publishing. Restore SSH keys and host trust from a protected backup. GnuPG and pinentry are included, but the signing key is not.

Sign back into Codex and set up its trusted projects and integrations again. This repo does not restore sessions. OpenCode's current config contains a local credential, so it is deliberately unmanaged. Set up that integration separately if you still need it. CodeGraph also needs its own executable.

The verifier checks configuration syntax and confirms that a second chezmoi apply would make no changes in a temporary home. A full restore has not yet been tested on a clean Mac, so package availability, app licensing, external installers, and authentication still need a real-world check.
