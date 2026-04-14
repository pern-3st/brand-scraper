#!/usr/bin/env bash
# Packages the repo into a Windows-ready zip for distribution to non-technical users.
# Must be run from the repo root. Requires backend/.env to exist (will be baked into the zip).

set -euo pipefail

if [[ ! -f backend/.env ]]; then
  echo "ERROR: backend/.env not found. Create it with the OPENROUTER_API_KEY you want" >&2
  echo "       to ship to the recipient before running this script." >&2
  exit 1
fi

OUT_DIR="dist"
STAGE="$OUT_DIR/brand_scraper_windows"
ZIP="$OUT_DIR/brand_scraper_windows.zip"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"

# Copy tracked files only, plus backend/.env which is gitignored.
git ls-files -z | tar --null -T - -cf - | (cd "$STAGE" && tar -xf -)
cp backend/.env "$STAGE/backend/.env"

# Strip anything the recipient doesn't need.
# Note: frontend/ is a gitlink in this repo, so tar pulls in the whole working
# tree for it — that's why .next and tsbuildinfo artifacts have to be scrubbed here.
rm -rf "$STAGE/docs" \
       "$STAGE/backend/tests" \
       "$STAGE/frontend/node_modules" \
       "$STAGE/frontend/.next" \
       "$STAGE/frontend/out" \
       "$STAGE/backend/.venv"
find "$STAGE/frontend" -name "*.tsbuildinfo" -type f -delete 2>/dev/null || true

# Sanity check — these must be in the staged tree before we zip.
# (git ls-files only includes tracked files, so if you haven't committed
# windows/ yet, the recipient would receive a broken bundle.)
REQUIRED=(
  "$STAGE/windows/setup.bat"
  "$STAGE/windows/run.bat"
  "$STAGE/windows/stop.bat"
  "$STAGE/windows/HOW_TO_USE.txt"
  "$STAGE/backend/.env"
  "$STAGE/backend/pyproject.toml"
  "$STAGE/frontend/package.json"
)
for f in "${REQUIRED[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing from stage: ${f#$STAGE/}" >&2
    echo "       Have you run 'git add windows/ scripts/ ...' and committed?" >&2
    exit 1
  fi
done

( cd "$OUT_DIR" && zip -rq "brand_scraper_windows.zip" "brand_scraper_windows" )

BYTES=$(stat -f%z "$ZIP" 2>/dev/null || stat -c%s "$ZIP")
MB=$(( BYTES / 1024 / 1024 ))
echo "Created $ZIP (${MB} MB)"
echo "Send this zip to the recipient. They extract it and double-click windows/setup.bat."
