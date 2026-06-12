"""Shared helpers for pipeline tool scripts.

Validate JSON from the command line::

    python3 tool_scripts/common.py --schema schemas/assembly.schema.json \\
        --data <run_dir>/iterations/001/assembly.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "base.yaml"


def resolve_config_path(path_str: str, *, repo_root: Path | None = None) -> Path:
    """Resolve a config path relative to the repo root, or as an absolute path."""
    path = Path(path_str).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (repo_root or REPO_ROOT) / path


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


def schema_path(name: str) -> Path:
    path = REPO_ROOT / "schemas" / name
    if not path.is_file():
        sys.exit(f"Error: schema not found: {path}")
    return path


def validate_schema(schema_name: str, data_path: Path | str) -> None:
    """Validate a JSON file against a repo schema; exit with fix hints on failure."""
    exit_if_invalid_json(schema_path(schema_name), data_path)


def load_dims_file(run_dir: Path) -> dict[str, dict[str, Any]]:
    dims_path = run_dir / "component_dims.json"
    return load_dims_map(load_json_file(dims_path))


def load_dims_map(dims_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dims_data["parts"]


def _rotate_scaled_center(
    scaled_center: list[float],
    euler_deg: list[float],
) -> list[float]:
    roll, pitch, yaw = euler_deg
    rotated = scaled_center
    for angle, axis in [(yaw, "z"), (pitch, "y"), (roll, "x")]:
        radians = math.radians(angle)
        cosine, sine = math.cos(radians), math.sin(radians)
        if axis == "z":
            matrix = [[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]]
        elif axis == "y":
            matrix = [[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]]
        else:
            matrix = [[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]]
        rotated = [sum(matrix[row][col] * rotated[col] for col in range(3)) for row in range(3)]
    return rotated


def recompute_blender_transforms(
    parts: list[dict[str, Any]],
    dims_map: dict[str, dict[str, Any]],
) -> None:
    world_scales: dict[str, list[float]] = {}
    for part in parts:
        name = part["name"]
        if name not in dims_map:
            raise KeyError(f"component_dims.json has no entry for part '{name}'")
        raw_size = dims_map[name]["size"]
        raw_center = dims_map[name]["center"]

        parent_name = part["parent"]
        if parent_name is None:
            parent_world_scale = [1.0, 1.0, 1.0]
        elif parent_name not in world_scales:
            raise ValueError(
                f"Part '{name}' must appear after parent '{parent_name}' "
                "in assembly.json parts list"
            )
        else:
            parent_world_scale = world_scales[parent_name]

        world_size = part["world_size"]
        world_center = part["world_center"]
        euler_deg = part["euler_deg"]

        node_scale = [
            world_size[axis] / (parent_world_scale[axis] * raw_size[axis]) for axis in range(3)
        ]
        scaled_center = _rotate_scaled_center(
            [node_scale[axis] * raw_center[axis] for axis in range(3)],
            euler_deg,
        )
        node_origin = [
            world_center[axis] / parent_world_scale[axis] - scaled_center[axis] for axis in range(3)
        ]

        part["node_scale"] = [round(value, 6) for value in node_scale]
        part["node_origin"] = [round(value, 5) for value in node_origin]
        world_scales[name] = [world_size[axis] / raw_size[axis] for axis in range(3)]


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
        schema_name = Path(schema_path).name
        print(f"INVALID: {data_path}")
        for error in errors:
            print(f"  {error}")
        print(f"Fix the file to match schemas/{schema_name}, then rerun.")
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
