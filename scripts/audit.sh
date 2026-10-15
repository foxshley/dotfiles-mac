#!/bin/bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
command -v python3 >/dev/null || { echo 'Python 3.11+ is required. Install Python through mise first.' >&2; exit 2; }
exec python3 "$repo_dir/scripts/audit.py" --repo "$repo_dir" "$@"
