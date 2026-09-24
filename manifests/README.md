# Software manifests

These are curated restore inputs for a fresh Apple Silicon Mac, not a dump of every installed or transitive package. `Brewfile.core` is the CLI baseline; `Brewfile.apps` holds larger GUI applications. Runtime versions belong to mise, Python projects to uv, and project-only requirements stay with their repositories. No secrets or credentials belong here.

These manifests were curated from the 2026-09-24 assessment inventory, which is kept separately from this portable repository. Package versions in that inventory are observations, not pins. Review optional and broad editor lists before installing. `Brewfile.core` deliberately omits fnm, Homebrew Go/Python/Zig/Bun runtime entries moved to mise, and Miniforge. Bun is requested through the mise configuration in this repository.

Rust is a global mise runtime; see [rust.md](rust.md) for setup and project version behavior.

`Brewfile.apps` is intentionally limited to core development apps; entertainment, recording, window management, and disabled casks are listed as optional. `vscode-extensions.txt` records installed default-profile IDs but includes many languages and remote workflows that may be project-specific. VS Code extension state can vary by profile. Mason names are references for Neovim/Mason, not portable standalone packages. Android IDs require Android Studio/SDK setup and license acceptance.

Before applying a manifest, ensure taps/formula names remain available on the target date and review the diff. Homebrew manifests do not reproduce package versions or service state.
