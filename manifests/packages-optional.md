# Optional package groups

These were observed on the current Mac but are not part of the initial development baseline. Add only when wanted on the new Mac.

- **Containers/Kubernetes:** `helm`, `herdr`, `htop`, `k9s`, `kind`, `kubernetes-cli`, `kustomize`; `ollama` is present but neither it nor `herdr` was reported running. `orbstack` is in `Brewfile.apps`.
- **Go release work:** install Go through mise; optionally add `goreleaser` and `gopls` (see `go-tools.txt`).
- **Media/large tools:** `ffmpeg`, `yt-dlp`, `wrk`, `zig` (Zig is represented in mise config; do not install a duplicate Brew formula).
- **Personal utilities:** `btop`, `htop`, `mole`, `stats`, `tree`, `nano`, `glow`, `yt-dlp`; remove entries already in core before applying an optional Brewfile.
- **Applications:** `obs`, `obsidian`, `prismlauncher`, `raycast`, `rectangle`, `stats`, `supacode`, `wine-stable`. Disabled casks `gstreamer-runtime` and `wine-stable` are not installed by default.
- **ML/Conda:** Miniforge was installed, but the inventory found no named Conda environments or common ML packages in its base environment. Leave it out of the baseline; add Conda to a project-specific setup only if that project requires it.

The inventory reflects one machine and does not establish which optional tools are still used. Review this list before making an optional install manifest executable.
