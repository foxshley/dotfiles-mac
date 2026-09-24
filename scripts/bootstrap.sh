#!/bin/bash
set -euo pipefail
umask 077

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
mode=${1:-preview}

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap.sh [preview|apply]

preview  List proposed home-file changes without printing file contents.
apply    Install core Homebrew packages, back up managed home files, apply
         dotfiles, install mise runtimes, and restore Fish plugins.

Set DOTFILES_INCLUDE_APPS=1 to install the app Brewfile during apply.
Set DOTFILES_GIT_NAME, DOTFILES_GIT_EMAIL, and DOTFILES_GIT_SIGNINGKEY
before first apply to populate optional Git identity settings.
EOF
}

case "$mode" in
  preview|apply) ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [[ $(uname -s) != Darwin || $(uname -m) != arm64 ]]; then
  echo 'This bootstrap supports Apple Silicon macOS.' >&2
  exit 1
fi

if [[ $mode == apply ]]; then
  if ! xcode-select -p >/dev/null 2>&1; then
    echo 'Install Command Line Tools, then rerun this script.' >&2
    xcode-select --install || true
    exit 1
  fi

  if [[ ! -x /opt/homebrew/bin/brew ]]; then
    echo 'Installing Homebrew from its official installer.'
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  eval "$(/opt/homebrew/bin/brew shellenv)"

  brew bundle install --no-upgrade --file="$repo_dir/manifests/Brewfile.core"
  if [[ ${DOTFILES_INCLUDE_APPS:-0} == 1 ]]; then
    brew bundle install --no-upgrade --file="$repo_dir/manifests/Brewfile.apps"
  fi
fi

if ! command -v chezmoi >/dev/null 2>&1; then
  echo 'chezmoi is needed for preview. Run apply to install the core packages.' >&2
  exit 1
fi

if [[ $mode == preview ]]; then
  chezmoi --source="$repo_dir" status
  exit 0
fi

# Initialize only when there is no existing chezmoi configuration. Existing
# machine-specific data remains under the user's control.
if [[ ! -f "$HOME/.config/chezmoi/chezmoi.toml" ]]; then
  # Preserve identity from an existing Mac without committing it to this repo.
  export DOTFILES_GIT_NAME="${DOTFILES_GIT_NAME:-$(git config --global --get user.name || true)}"
  export DOTFILES_GIT_EMAIL="${DOTFILES_GIT_EMAIL:-$(git config --global --get user.email || true)}"
  export DOTFILES_GIT_SIGNINGKEY="${DOTFILES_GIT_SIGNINGKEY:-$(git config --global --get user.signingkey || true)}"
  chezmoi --source="$repo_dir" init
fi

backup_root="$HOME/.local/state/dotfiles-backups"
mkdir -p "$backup_root"
backup_dir=$(mktemp -d "$backup_root/$(date +%Y%m%d-%H%M%S).XXXXXX")
managed_list=$(mktemp)
trap 'rm -f "$managed_list"' EXIT
chezmoi --source="$repo_dir" managed --include=files,symlinks --path-style=absolute --nul-path-separator > "$managed_list"
while IFS= read -r -d '' managed_path; do
  case "$managed_path" in
    "$HOME"/*) ;;
    *) echo "Refusing unexpected managed path: $managed_path" >&2; exit 1 ;;
  esac
  if [[ -e "$managed_path" || -L "$managed_path" ]]; then
    relative_path=${managed_path#"$HOME"/}
    mkdir -p "$backup_dir/$(dirname "$relative_path")"
    cp -pR "$managed_path" "$backup_dir/$relative_path"
  fi
done < "$managed_list"
rm -f "$managed_list"
trap - EXIT
echo "Backed up existing managed files to $backup_dir"

chezmoi --source="$repo_dir" apply --error-on-conflict
mise install

if command -v fish >/dev/null 2>&1; then
  fish -c 'if functions -q fisher; fisher update; else; echo "Fisher is unavailable after Homebrew install" >&2; exit 1; end'
  if [[ -f "$HOME/.config/fish/setup-tide.fish" ]]; then
    fish "$HOME/.config/fish/setup-tide.fish"
  fi
fi

echo 'Core restore complete. Run scripts/verify.sh and finish account/key and project-specific setup from README.md.'
