#!/usr/bin/env bash
# Regenerate the committed TypeScript client from the OpenAPI contract.
# Requires Node (npx). Run after scripts/export_openapi.py.
set -euo pipefail
.venv/Scripts/python.exe scripts/export_openapi.py
mkdir -p contracts/ts
npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
echo "Wrote contracts/ts/api.ts"

# Keep the SPA's local copy in sync with the committed contract.
if [ -d web/src/lib/api ]; then
  cp contracts/ts/api.ts web/src/lib/api/schema.ts
  echo "Copied contract to web/src/lib/api/schema.ts"
fi
