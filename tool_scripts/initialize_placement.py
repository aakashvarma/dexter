"""Build the first assembly layout from parts.json and raw GLB dimensions.

Usage::

    python3 tool_scripts/initialize_placement.py --run-dir <run_dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import (
    exit_if_missing,
    load_dims_map,
    load_json_file,
    load_yaml_config,
    recompute_blender_transforms,
    validate_schema,
    write_json_file,
)


def order_parts_tree(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {part["name"]: part for part in parts}
    children_of: dict[str, list[dict[str, Any]]] = {}
    root = None
    for part in parts:
        parent = part["parent"]
        if parent is None:
            root = part
        else:
            if parent not in by_name:
                raise ValueError(f"parts.json: unknown parent '{parent}' for '{part['name']}'")
            children_of.setdefault(parent, []).append(part)

    if root is None:
        raise ValueError("parts.json: no root part (parent must be null on exactly one part)")

    ordered: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        ordered.append(part)
        for child in children_of.get(part["name"], []):
            walk(child)

    walk(root)
    if len(ordered) != len(parts):
        raise ValueError("parts.json: invalid part tree (cycle or disconnected part)")
    return ordered


def initialize_placement(run_dir: str | Path) -> None:
    config = load_yaml_config()
    placement_config = config["placement_init"]
    run_path = Path(run_dir).expanduser().resolve()

    parts_path = run_path / placement_config["parts_file"]
    dims_path = run_path / placement_config["dims_file"]
    assembly_path = run_path / placement_config["output"]
    glbs_dir = config["fal"]["output_dir"]

    exit_if_missing(parts_path, "parts.json")
    exit_if_missing(dims_path, "component_dims.json")
    validate_schema("parts.schema.json", parts_path)
    validate_schema("component_dims.schema.json", dims_path)

    if assembly_path.exists():
        print(f"skip (exists): {assembly_path}")
        return

    parts_data = load_json_file(parts_path)
    dims_map = load_dims_map(load_json_file(dims_path))

    assembly_parts = []
    for part in order_parts_tree(parts_data["parts"]):
        name = part["name"]
        assembly_parts.append(
            {
                "name": name,
                "description": part["description"],
                "parent": part["parent"],
                "joint_type": part["joint_type"],
                "visual_mesh": f"{glbs_dir}/{name}.glb",
                "collision_mesh": f"{glbs_dir}/{name}.glb",
                "world_size": [round(v, 5) for v in part["world_size"]],
                "world_center": [round(v, 5) for v in part["world_center"]],
                "euler_deg": [round(v, 4) for v in part["euler_deg"]],
            }
        )

    recompute_blender_transforms(assembly_parts, dims_map)

    write_json_file(
        assembly_path,
        {
            "root": str(run_path),
            "robot_name": parts_data["object"],
            "parts": assembly_parts,
        },
    )
    print(f"Wrote {assembly_path}")
    validate_schema("assembly.schema.json", assembly_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    try:
        initialize_placement(parser.parse_args().run_dir)
    except (KeyError, ValueError) as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
