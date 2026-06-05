"""Shared helpers for pipeline tool scripts.

Validate JSON from the command line::

    python3 tool_scripts/common.py --schema schemas/assembly.schema.json \\
        --data .intermediate/dishwasher/001/iterations/001/assembly.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "base.yaml"


def load_json_file(path: Path | str) -> Any:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG_PATH
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def require_existing_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")


def exit_if_missing(path: Path, label: str) -> None:
    if not path.is_file():
        sys.exit(f"Error: {label} not found: {path}")


def load_dims_file(run_dir: Path) -> dict[str, dict[str, Any]]:
    dims_path = run_dir / "component_dims.json"
    return load_dims_map(load_json_file(dims_path))


def load_dims_map(dims_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parts = dims_data.get("parts")
    if isinstance(parts, dict):
        dims_map = parts
        for name, entry in dims_map.items():
            entry.setdefault("name", name)
        return dims_map

    components = dims_data.get("components")
    if isinstance(components, list):
        return {entry["name"]: entry for entry in components}

    raise ValueError(
        "component_dims.json must have a 'parts' dict or 'components' array at top level"
    )


def parse_blender_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def collect_schema_errors(schema: dict, data: object) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def validate_json_file(schema_path: Path | str, data_path: Path | str) -> list[str]:
    """Return schema validation errors; an empty list means the file is valid."""
    schema = load_json_file(schema_path)
    data = load_json_file(data_path)
    return collect_schema_errors(schema, data)


def exit_if_invalid_json(schema_path: Path | str, data_path: Path | str) -> None:
    """Print validation result per tool-script conventions and exit 1 when invalid."""
    data_path = Path(data_path)
    errors = validate_json_file(schema_path, data_path)
    if errors:
        print(f"INVALID: {data_path}")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    print(f"OK: {data_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a JSON file against a JSON Schema.")
    parser.add_argument("--schema", required=True, help="Path to the JSON Schema file")
    parser.add_argument("--data", required=True, help="Path to the JSON file to validate")
    args = parser.parse_args()
    exit_if_invalid_json(args.schema, args.data)


if __name__ == "__main__":
    main()
