# Optional Rust setup

Rust is prepared as an opt-in runtime. It is absent from the global mise config, so the normal dotfiles bootstrap does not install it on this Mac or a fresh Mac.

When you decide to use Rust, add this line under `[tools]` in `dot_config/mise/config.toml`:

```toml
rust = "latest"
```

Then run `chezmoi --source="$HOME/dotfiles" apply`, `mise install rust`, and verify with `mise exec -- rustc --version` and `mise exec -- cargo --version`. Commit the mise config change to sync that choice to your dotfiles. Mise uses rustup to manage the Rust toolchain; there is no need to add a separate Rust Homebrew formula or installer to the core manifest.

For a Rust project that has `rust-toolchain.toml`, keep its toolchain choice with that project. Before relying on that file through mise, add `rust` to `idiomatic_version_file_enable_tools` in the mise config. Mise sets `RUSTUP_TOOLCHAIN`, which has precedence over rustup's project file, so check the active version with `mise exec -- rustup show active-toolchain`.

`~/.rustup` and `~/.cargo` are generated toolchain, package, and cache data; do not copy them into dotfiles. Record project dependencies in each project's `Cargo.toml` and lockfile.

References: [mise Rust](https://mise.jdx.dev/lang/rust.html) and [rustup toolchain overrides](https://rust-lang.github.io/rustup/overrides.html).
