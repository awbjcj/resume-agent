#!/usr/bin/env bash
# Regenerate the committed TypeScript client from the OpenAPI contract.
# Requires Node (npx). Run after scripts/export_openapi.py.
set -euo pipefail
.venv/Scripts/python.exe scripts/export_openapi.py
mkdir -p contracts/ts
if command -v node >/dev/null 2>&1; then
  npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
elif command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command \
    "npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts"
else
  echo "Node.js is required to generate the TypeScript client." >&2
  exit 1
fi
echo "Wrote contracts/ts/api.ts"

# Keep the SPA's local copy in sync with the committed contract.
if [ -d web/src/lib/api ]; then
  cp contracts/ts/api.ts web/src/lib/api/schema.ts
  echo "Copied contract to web/src/lib/api/schema.ts"
fi
