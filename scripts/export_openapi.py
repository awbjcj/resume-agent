"""Dump the FastAPI OpenAPI schema to contracts/openapi.json (the published contract)."""

import json
from pathlib import Path

from resume_agent.api.app import create_app


def main() -> None:
    spec = create_app(db_url="sqlite://").openapi()
    out = Path("contracts/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
