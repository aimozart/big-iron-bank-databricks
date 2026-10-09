#!/usr/bin/env bash
# Export a Databricks workspace folder into ./notebooks and commit it locally.
# You run this yourself. It never touches credentials: the databricks CLI uses your own login.
# Usage: ./export.sh "/Workspace/Users/<you>/<folder>" [profile]
set -euo pipefail

SRC="${1:-}"
PROFILE="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/notebooks"

if [ -z "$SRC" ]; then
  echo "usage: $0 \"/Workspace/Users/<you>/<folder>\" [profile]" >&2
  exit 2
fi
case "$SRC" in
  /Workspace/*) ;;
  *) echo "refusing: source must start with /Workspace/ (got: $SRC)" >&2; exit 2 ;;
esac
if ! command -v databricks >/dev/null 2>&1; then
  echo "databricks CLI not found. Install it first, then run: databricks auth login --host <workspace url>" >&2
  exit 3
fi

PARGS=()
[ -n "$PROFILE" ] && PARGS=(--profile "$PROFILE")

mkdir -p "$DEST"
echo "exporting $SRC -> $DEST"
databricks workspace export-dir "$SRC" "$DEST" --overwrite "${PARGS[@]}"

cd "$HERE"
# safety net: stop if anything that looks like a secret is about to be committed
if grep -rIlE '(dapi[0-9a-f]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16})' notebooks sql evidence bundles generator 2>/dev/null; then
  echo "STOP: possible secret found in the files listed above. Remove it before committing." >&2
  exit 4
fi

git add -A
if git diff --cached --quiet; then
  echo "nothing new to commit"
else
  git commit -q -m "Export workspace $(date +%F\ %H:%M)"
  echo "committed: $(git log -1 --format=%h)"
fi
