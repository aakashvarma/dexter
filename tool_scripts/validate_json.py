"""validate_json.py — Validate a JSON file against a JSON Schema.

What it does
------------
Loads a JSON Schema and a data file, validates the data, and reports the
result. Prints ``OK`` and exits 0 when valid; prints each schema error and
exits 1 when invalid. Used as the gate for ``parts.json``,
``place_assets.json``, and ``render_views.json``.

Run::

    python validate_json.py \\
        --schema ../schemas/place_assets.schema.json \\
        --data ../.intermediate/dishwasher/001/iterations/001/place_assets.json

No JSON config of its own; both inputs are passed as file paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema


def parse_args() -> argparse.Namespace:
    """Parse the ``--schema`` and ``--data`` command-line arguments.

    Returns:
        Parsed arguments with ``schema`` and ``data`` paths.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", required=True)
    parser.add_argument("--data", required=True)
    return parser.parse_args()


def load_json(path: str) -> object:
    """Load a JSON file from disk.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON.
    """
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def collect_errors(schema: dict, data: object) -> list[str]:
    """Validate data against schema and collect human-readable errors.

    Args:
        schema: Parsed JSON Schema.
        data: Parsed JSON data to validate.

    Returns:
        Sorted list of error messages; empty when the data is valid.
    """
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in errors]


def main() -> None:
    """Validate the data file and exit non-zero on any schema error."""
    args = parse_args()
    schema = load_json(args.schema)
    data = load_json(args.data)

    errors = collect_errors(schema, data)
    if errors:
        print(f"INVALID: {args.data}")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)

    print(f"OK: {args.data}")


if __name__ == "__main__":
    main()
