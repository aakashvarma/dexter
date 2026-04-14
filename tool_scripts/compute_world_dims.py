"""compute_world_dims.py — Compute per-part world dimensions from assembly.json.

Uses the same transform chain as blender_assemble.py:

    world_size[axis]   = parent_scale[axis] × child_scale[axis] × raw_size[axis]
    world_center[axis] = parent_scale[axis] × (origin_xyz[axis]
                         + child_scale[axis] × raw_mesh_center[axis])

Also detects collisions: any two parts whose world bounding boxes overlap on
all three axes are listed under `collisions`.

Usage::

    python3 tool_scripts/compute_world_dims.py \\
        --assembly <path/to/assembly.json> \\
        --dims     <path/to/component_dims.json> \\
        --output   <path/to/world_dims.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_dims_map(dims_data: dict) -> dict[str, dict]:
    if "parts" in dims_data and isinstance(dims_data["parts"], dict):
        dims_map = dims_data["parts"]
        for k, v in dims_map.items():
            v.setdefault("name", k)
        return dims_map
    if "components" in dims_data:
        return {entry["name"]: entry for entry in dims_data["components"]}
    raise ValueError("component_dims.json must have a 'parts' dict or 'components' array at top level")


def compute_part_dims(
    link: dict,
    raw: dict,
    parent_scale: list[float],
) -> dict:
    """Compute world-space dimensions for one link.

    parent_scale is [1,1,1] for the root; for children it is the parent's scale[] from assembly.json.
    """
    scale      = link["scale"]
    origin_xyz = link["origin"]["xyz"]

    world_size   = [round(parent_scale[i] * scale[i] * raw["size"][i],                  5) for i in range(3)]
    world_center = [round(parent_scale[i] * (origin_xyz[i] + scale[i] * raw["center"][i]), 5) for i in range(3)]
    world_min    = [round(parent_scale[i] * (origin_xyz[i] + scale[i] * raw["min"][i]),    5) for i in range(3)]
    world_max    = [round(parent_scale[i] * (origin_xyz[i] + scale[i] * raw["max"][i]),    5) for i in range(3)]

    return {
        "world_size":   world_size,
        "world_center": world_center,
        "world_min":    world_min,
        "world_max":    world_max,
        "parent_scale": [round(v, 6) for v in parent_scale],
    }


def detect_collisions(parts: dict[str, dict]) -> list[dict]:
    """Return pairs of part names whose world bounding boxes overlap on all axes."""
    names = list(parts.keys())
    collisions = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = parts[names[i]], parts[names[j]]
            overlap = all(
                a["world_min"][ax] < b["world_max"][ax] and
                b["world_min"][ax] < a["world_max"][ax]
                for ax in range(3)
            )
            if overlap:
                collisions.append({"parts": [names[i], names[j]]})
    return collisions


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--assembly", required=True, help="Path to assembly.json")
    p.add_argument("--dims",     required=True, help="Path to component_dims.json")
    p.add_argument("--output",   required=True, help="Output path for world_dims.json")
    args = p.parse_args()

    assembly_path = Path(args.assembly).expanduser().resolve()
    dims_path     = Path(args.dims).expanduser().resolve()
    output_path   = Path(args.output).expanduser().resolve()

    for path, label in [(assembly_path, "assembly.json"), (dims_path, "component_dims.json")]:
        if not path.is_file():
            sys.exit(f"Error: {label} not found: {path}")

    assembly = json.loads(assembly_path.read_text(encoding="utf-8"))
    dims_map = load_dims_map(json.loads(dims_path.read_text(encoding="utf-8")))

    # Index links by name, and build a parent → scale lookup
    links_by_name: dict[str, dict] = {link["name"]: link for link in assembly["links"]}

    parts: dict[str, dict] = {}
    for link in assembly["links"]:
        name = link["name"]
        raw  = dims_map.get(name)
        if raw is None:
            print(f"  [WARN] No dims entry for '{name}' — skipping.", file=sys.stderr)
            continue

        parent_name = link.get("parent")
        if parent_name is None:
            parent_scale = [1.0, 1.0, 1.0]
        else:
            parent_link = links_by_name.get(parent_name)
            if parent_link is None:
                print(f"  [WARN] Parent '{parent_name}' not found for '{name}' — using [1,1,1].", file=sys.stderr)
                parent_scale = [1.0, 1.0, 1.0]
            else:
                parent_scale = parent_link["scale"]

        parts[name] = compute_part_dims(link, raw, parent_scale)

    output = {
        "assembly": str(assembly_path),
        "parts": parts,
        "collisions": detect_collisions(parts),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
