# Interactive shell preferences shared across machines.
if status is-interactive
    # Add common tool directories only when present; covers Apple Silicon and
    # Intel Homebrew without baking the current Mac's prefix into other paths.
    for directory in "$HOME/.local/bin" /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin /usr/local/sbin
        if test -d "$directory"
            fish_add_path --global --prepend "$directory"
        end
    end

    if type -q mise
        mise activate fish | source
    end

    if type -q zoxide
        zoxide init fish | source
    end

    alias ll='eza -lah'
    alias c='bat --paging=never'
    alias gs='git status'
    alias k='kubectl'
    alias d='docker'
    alias dc='docker compose'
end

# OrbStack is optional. Its installer recreates this integration on each Mac.
if test -f "$HOME/.orbstack/shell/init2.fish"
    source "$HOME/.orbstack/shell/init2.fish"
end
