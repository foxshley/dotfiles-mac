#!/bin/bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
mkdir -p "$test_dir/home"

command -v chezmoi >/dev/null || { echo 'Install chezmoi before verification.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Install Python through mise before verification.' >&2; exit 1; }

bash -n "$repo_dir/scripts/bootstrap.sh" "$repo_dir/scripts/verify.sh"
if command -v ruby >/dev/null; then
  ruby -c "$repo_dir/manifests/Brewfile.core" >/dev/null
  ruby -c "$repo_dir/manifests/Brewfile.apps" >/dev/null
fi

python3 - "$repo_dir" <<'PY'
import json
from pathlib import Path
import sys
import tomllib

root = Path(sys.argv[1])
for path in root.rglob('*.toml'):
    if path.name != '.chezmoi.toml.tmpl':
        tomllib.loads(path.read_text())
for path in root.rglob('*.json'):
    json.loads(path.read_text())
PY

if command -v fish >/dev/null; then
  while IFS= read -r -d '' fish_file; do
    fish -n "$fish_file"
  done < <(find "$repo_dir/dot_config/fish" -name '*.fish' -print0)
fi

chezmoi --source="$repo_dir" --destination="$test_dir/home" --config="$test_dir/chezmoi.toml" init
chezmoi --source="$repo_dir" --destination="$test_dir/home" --config="$test_dir/chezmoi.toml" apply --error-on-conflict
if [[ -n $(chezmoi --source="$repo_dir" --destination="$test_dir/home" --config="$test_dir/chezmoi.toml" diff) ]]; then
  echo 'Second chezmoi pass differs from the first.' >&2
  exit 1
fi

if [[ -e "$test_dir/home/README.md" || -e "$test_dir/home/manifests" || -e "$test_dir/home/scripts" ]]; then
  echo 'Repository support files leaked into the home destination.' >&2
  exit 1
fi

if command -v rg >/dev/null && rg -l -F "$HOME" "$repo_dir" --glob '!README.md' --glob '!*.md' >/dev/null; then
  echo 'A source file contains the old absolute home path.' >&2
  exit 1
fi

echo 'Configuration parses and applies twice without drift to a temporary home.'
