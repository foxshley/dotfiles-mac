# Rust runtime

The global default is `rust = "latest"` in `dot_config/mise/config.toml`. The normal dotfiles bootstrap installs Rust with the other mise runtimes. Mise uses rustup underneath; no separate Homebrew Rust formula or installer is needed.

On an existing Mac, run `chezmoi --source="$HOME/dotfiles" apply` after editing the source, then `mise install rust`. Verify outside the dotfiles repository with `mise exec -- rustc --version` and `mise exec -- cargo --version`. Run `mise upgrade rust` when you want to advance the global toolchain. Commit changes to the managed config to sync them to another Mac.

Project-specific Rust versions belong in each project's `rust-toolchain.toml`. The managed mise config enables discovery of that file through `idiomatic_version_file_enable_tools`; check the selected version with `mise exec -- rustup show active-toolchain`. Mise sets `RUSTUP_TOOLCHAIN`, which takes precedence over rustup's direct file discovery.

Avoid running `mise use rust` while inside `~/dotfiles`: it creates a repository-local `mise.toml`, rather than changing the managed global config. The repository ignores that filename for chezmoi as an extra safeguard.

`~/.rustup` and `~/.cargo` are generated toolchain, package, and cache data; do not copy them into dotfiles. Record project dependencies in each project's `Cargo.toml` and lockfile.

References: [mise Rust](https://mise.jdx.dev/lang/rust.html) and [rustup toolchain overrides](https://rust-lang.github.io/rustup/overrides.html).
