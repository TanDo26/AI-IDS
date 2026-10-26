"""
The OpenAPI schema the frontend's types are generated from (web/lib/openapi.json -> api-schema.d.ts).
"""

import json

from src.api.main import create_app
from tests.conftest import PROJECT_ROOT

REGENERATE = "run: python scripts/export_openapi.py && cd web && npm run gen:api"


def test_schema_names_are_unique():
    # Two response models with the same class name get module-path names
    # (src__api__admin__schemas__UploadStats), and the frontend's friendly type names break
    names = create_app().openapi()["components"]["schemas"]
    clashes = sorted(n for n in names if "__" in n)
    assert clashes == [], f"rename one of the clashing response models: {clashes}"


def test_frontend_types_match_the_api():
    committed = json.loads((PROJECT_ROOT / "web" / "lib" / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi(), f"web/lib/openapi.json is stale; {REGENERATE}"
