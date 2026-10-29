"""Write the OpenAPI document to a file: `python -m app.export_openapi out.json`."""

import json
import sys

from app.main import create_app


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(create_app().openapi(), f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
