# Node policy

- Global runtime: mise `node = "lts"`; update deliberately with `mise upgrade node`.
- Do not restore fnm or older global Node versions. The previous Node 22 versions were project-specific; project manifests and lockfiles own their pins.
- Node 24's globally installed packages in the inventory were `@openai/codex` and `@colbymchenry/codegraph`; Codex had different versions across historical Node installs. Treat these as optional user CLIs, install current versions with the vendor-recommended method, and keep authentication outside dotfiles.
- Do not globally install `corepack` or `npm`; Node provides npm, and package managers should be selected per project.
