"""
Write the web API's OpenAPI schema to web/lib/openapi.json, the source of the frontend's types.
Run it after changing an endpoint or a response model, then regenerate the types:

    python scripts/export_openapi.py
    cd web && npm run gen:api        # -> web/lib/api-schema.d.ts
"""
import sys
import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.api.main import create_app


def main(out: Path):
    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {len(schema['paths'])} paths, {len(schema['components']['schemas'])} schemas -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export the API's OpenAPI schema for the frontend")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "web" / "lib" / "openapi.json"))
    args = parser.parse_args()
    main(Path(args.out))
