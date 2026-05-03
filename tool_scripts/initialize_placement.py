"""Pre-compute sizes and positions, then write the first assembly layout.

Turns the part list from the analyze step into numbers Blender can place in a scene.

Vocabulary used throughout this file:
  - **part** — one physical piece (e.g. door, drawer, cabinet body).
  - **parent / child** — assembly nesting: a door's parent is the cabinet it attaches to.
  - **raw** — measurements taken directly from the generated .glb mesh file, before any
    resizing. Raw size is whatever the AI mesh happens to be; it is usually wrong scale.
  - **world** — final scene coordinates in metres, shared by the whole assembled object.
    ``world_size`` is how big a part should be; ``world_center`` is where its centre sits.
  - **node** — in Blender, an empty parent object that holds a part's mesh. ``node_scale``
    and ``node_origin`` are local transform values on that empty (used by blender_assemble).
  - **joint** — how a child moves relative to its parent: ``revolute`` = hinge (door),
    ``prismatic`` = slide (drawer), ``fixed`` = does not move.
  - **scale** — stretch factor applied to the raw mesh so it matches the target world size.

The analyze agent writes ``world_size``, ``world_center``, and ``euler_deg`` per non-root
part (the pose shown in the source image). This script only derives Blender ``node_scale``
and ``node_origin`` from those values plus raw GLB dimensions.

Inputs (paths from configs/base.yaml placement_init block):
  - parts.json — part tree with world-space size, centre, and rotation per part
  - component_dims.json — raw width/depth/height of each .glb from Blender

Outputs:
  - placement_init.json — detailed tree (scales, local origins, poses)
  - iterations/001/assembly.json — flat list of parts in world coordinates for Blender

Usage::

    python3 tool_scripts/initialize_placement.py --run-dir <run_dir>
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

from common import (
    REPO_ROOT,
    exit_if_invalid_json,
    exit_if_missing,
    load_dims_map,
    load_json_file,
    load_yaml_config,
    write_json_file,
)


def rotation_matrix_z(degrees: float) -> list[list[float]]:
    """Build math for spinning a point around the vertical (up) axis by ``degrees``."""
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]]


def rotation_matrix_x(degrees: float) -> list[list[float]]:
    """Build math for tilting a point forward/back around the left-right axis."""
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]]


def rotation_matrix_y(degrees: float) -> list[list[float]]:
    """Build math for tilting a point side-to-side around the front-back axis."""
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]]


def multiply_matrix_vector(
    matrix: list[list[float]],
    vector: list[float],
) -> list[float]:
    """Rotate a 3D point using one of the rotation matrices above."""
    return [sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3)]


def compute_node_scale(
    world_size: list[float],
    parent_world_scale: list[float],
    raw_size: list[float],
) -> list[float]:
    """How much to stretch the imported .glb so it matches the desired real-world size.

    ``world_size`` — target width/depth/height in metres for this part.
    ``raw_size`` — width/depth/height of the .glb as generated (usually not to scale).
    ``parent_world_scale`` — how much the parent part was already stretched (children
    inherit that, so their local scale must account for it).

    Returns ``node_scale``: per-axis stretch factors Blender applies on the empty parent.
    """
    node_scale: list[float] = []
    for axis in range(3):
        denominator = parent_world_scale[axis] * raw_size[axis]
        if abs(denominator) < 1e-9:
            print(
                f"Warning: near-zero denominator on axis {axis} — setting scale to 1.0",
                file=sys.stderr,
            )
            node_scale.append(1.0)
        else:
            node_scale.append(world_size[axis] / denominator)
    return node_scale


def compute_node_origin(
    world_center: list[float],
    parent_world_scale: list[float],
    node_scale: list[float],
    raw_mesh_center: list[float],
    euler_deg: list[float] | None = None,
) -> list[float]:
    """Convert a world position into the local offset on the parent's empty object.

    Blender places each part under an empty parent. ``world_center`` is where we want
    the part's centre in the full scene (metres). ``node_origin`` is the matching
    local [x, y, z] on that empty — what blender_assemble.py writes to the object.

    Steps: scale the raw mesh centre, optionally rotate it if the part is tilted,
    then back-solve the local offset from the desired world centre.
    """
    scaled_center = [node_scale[axis] * raw_mesh_center[axis] for axis in range(3)]

    if euler_deg is not None:
        roll, pitch, yaw = euler_deg
        rotated = scaled_center
        for angle, rotation_fn in [
            (yaw, rotation_matrix_z),
            (pitch, rotation_matrix_y),
            (roll, rotation_matrix_x),
        ]:
            if abs(angle) > 0.01:
                rotated = multiply_matrix_vector(rotation_fn(angle), rotated)
        scaled_center = rotated

    return [
        world_center[axis] / parent_world_scale[axis] - scaled_center[axis] for axis in range(3)
    ]


def _flatten_placements_to_parts(
    placements: list[dict],
    parent_name: str,
    glbs_dir: str,
    parts: list[dict],
) -> None:
    """Turn the nested part tree into a flat list for assembly.json."""
    for placement in placements:
        name = placement["name"]
        pose = placement["pose"]
        parts.append(
            {
                "name": name,
                "parent": parent_name,
                "visual_mesh": f"{glbs_dir}/{name}.glb",
                "collision_mesh": f"{glbs_dir}/{name}.glb",
                "world_size": placement["world_size"],
                "world_center": pose["world_center"],
                "euler_deg": pose["euler_deg"],
            }
        )
        _flatten_placements_to_parts(placement["children"], name, glbs_dir, parts)


def build_assembly(
    object_name: str,
    run_dir: Path,
    glbs_dir: str,
    root_name: str,
    root_world_size: list[float],
    root_world_center: list[float],
    child_placements: list[dict],
) -> dict:
    """Package the full object as assembly.json for blender_assemble.py.

    Starts with the root part (no parent), then adds every descendant. The root sits
    on the ground: centre at z = half its height, x and y at zero.
    """
    parts: list[dict] = [
        {
            "name": root_name,
            "parent": None,
            "visual_mesh": f"{glbs_dir}/{root_name}.glb",
            "collision_mesh": f"{glbs_dir}/{root_name}.glb",
            "world_size": [round(value, 5) for value in root_world_size],
            "world_center": [round(value, 5) for value in root_world_center],
            "euler_deg": [0.0, 0.0, 0.0],
        }
    ]
    _flatten_placements_to_parts(child_placements, root_name, glbs_dir, parts)

    return {
        "root": str(run_dir),
        "robot_name": object_name,
        "parts": parts,
    }


def process_children(
    parent_name: str,
    tree: dict[str, list[dict]],
    dims_map: dict[str, dict],
    parent_world_scale: list[float],
) -> list[dict]:
    """Walk the assembly tree and derive Blender scale/origin for each child part.

    Size, centre, and rotation come directly from parts.json. This function only
    computes node_scale and node_origin from raw GLB dimensions.
    """
    children = tree.get(parent_name, [])
    results: list[dict] = []

    for child in children:
        name = child["name"]
        raw_dims = dims_map.get(name)
        if raw_dims is None:
            print(f"[SKIP] No dims entry for '{name}'", file=sys.stderr)
            continue

        world_size = list(child["world_size"])
        world_center = list(child["world_center"])
        euler_deg = list(child["euler_deg"])

        node_scale = compute_node_scale(world_size, parent_world_scale, raw_dims["size"])
        world_scale = [world_size[axis] / raw_dims["size"][axis] for axis in range(3)]
        node_origin = compute_node_origin(
            world_center,
            parent_world_scale,
            node_scale,
            raw_dims["center"],
            euler_deg,
        )

        placement: dict[str, Any] = {
            "name": name,
            "joint_type": child["joint_type"],
            "parent_world_scale": [round(value, 6) for value in parent_world_scale],
            "world_size": [round(value, 5) for value in world_size],
            "raw_size": [round(value, 5) for value in raw_dims["size"]],
            "node_scale": [round(value, 6) for value in node_scale],
            "pose": {
                "world_center": [round(value, 5) for value in world_center],
                "node_origin": [round(value, 5) for value in node_origin],
                "euler_deg": [round(value, 4) for value in euler_deg],
            },
            "children": process_children(name, tree, dims_map, world_scale),
        }
        results.append(placement)

    return results


def initialize_placement(run_dir: str | Path) -> None:
    """Main entry: read inputs, place every part, write the two output JSON files.

    1. Load parts.json (tree + world-space poses) and component_dims.json (raw .glb sizes).
    2. Find the root part (the one with ``parent: null``, e.g. the cabinet body).
    3. Recursively compute node_scale and node_origin for all children.
    4. Write placement_init.json (detailed) and iterations/001/assembly.json (for Blender).

    Skips entirely if both output files already exist.
    """
    config = load_yaml_config()
    placement_config = config["placement_init"]
    run_path = Path(run_dir).expanduser().resolve()

    parts_path = run_path / placement_config["parts_file"]
    dims_path = run_path / placement_config["dims_file"]
    init_path = run_path / placement_config["output"]
    assembly_path = run_path / "iterations" / "001" / "assembly.json"
    glbs_dir = config["fal"]["output_dir"]

    exit_if_missing(parts_path, "parts.json")
    exit_if_missing(dims_path, "component_dims.json")

    if init_path.exists() and assembly_path.exists():
        print(f"skip (exists): {init_path}")
        print(f"skip (exists): {assembly_path}")
        return

    parts_data = load_json_file(parts_path)
    dims_data = load_json_file(dims_path)
    parts = parts_data["parts"]
    dims_map = load_dims_map(dims_data)

    root_part = next((part for part in parts if part["parent"] is None), None)
    if root_part is None:
        sys.exit("No root part found (part with parent=null)")

    root_name = root_part["name"]
    root_world_size = list(root_part["world_size"])

    raw_root = dims_map.get(root_name)
    if raw_root is None:
        sys.exit(f"Error: no dims entry for root part '{root_name}'")

    root_node_scale = compute_node_scale(root_world_size, [1.0, 1.0, 1.0], raw_root["size"])
    root_world_scale = [root_world_size[axis] / raw_root["size"][axis] for axis in range(3)]
    root_world_center = [0.0, 0.0, root_world_size[2] / 2]

    tree: dict[str, list[dict]] = {}
    for part in parts:
        tree.setdefault(part["parent"] or "__root__", []).append(part)

    child_placements = process_children(root_name, tree, dims_map, root_world_scale)
    object_name = parts_data.get("object", root_name)

    init_output: dict[str, Any] = {
        "object": object_name,
        "root_name": root_name,
        "root_world_size": [round(value, 5) for value in root_world_size],
        "root_world_center": [round(value, 5) for value in root_world_center],
        "root_node_scale": [round(value, 6) for value in root_node_scale],
        "config_used": {
            "source": "parts.json",
            "root_world_size": [round(value, 5) for value in root_world_size],
        },
        "parts": child_placements,
    }
    write_json_file(init_path, init_output)
    print(f"Wrote {init_path}")

    placement_init_schema = REPO_ROOT / "schemas" / "placement_init.schema.json"
    if placement_init_schema.exists():
        exit_if_invalid_json(placement_init_schema, init_path)
    else:
        print(
            f"Warning: schema not found at {placement_init_schema}, skipping validation.",
            file=sys.stderr,
        )

    assembly = build_assembly(
        object_name,
        run_path,
        glbs_dir,
        root_name,
        root_world_size,
        root_world_center,
        child_placements,
    )
    write_json_file(assembly_path, assembly)
    print(f"Wrote {assembly_path}")

    assembly_schema = REPO_ROOT / "schemas" / "assembly.schema.json"
    if assembly_schema.exists():
        exit_if_invalid_json(assembly_schema, assembly_path)
    else:
        print(
            f"Warning: schema not found at {assembly_schema}, skipping validation.",
            file=sys.stderr,
        )


def main() -> None:
    """Command-line wrapper: requires ``--run-dir`` pointing at a pipeline run folder."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    initialize_placement(parser.parse_args().run_dir)


if __name__ == "__main__":
    main()
