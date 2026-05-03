"""Build a Blender scene from assembly.json.

Run::

    blender --background --python blender_assemble.py -- \\
        --layout ../.intermediate/dishwasher/001/iterations/006/assembly.json \\
        --output ../.intermediate/dishwasher/001/iterations/006/assembled.blend
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

from common import load_dims_file, load_json_file, parse_blender_args


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_glb(path: Path) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        raise RuntimeError(f"No objects imported from {path}")
    return imported


def place_part(
    part: dict,
    run_dir: Path,
    dims_map: dict[str, dict],
    world_scales: dict[str, list[float]],
):
    mesh_path = Path(part["visual_mesh"])
    if not mesh_path.is_absolute():
        mesh_path = (run_dir / mesh_path).resolve()
    if not mesh_path.exists():
        raise FileNotFoundError(mesh_path)

    imported = import_glb(mesh_path)
    node = bpy.data.objects.new(part["name"], None)
    bpy.context.collection.objects.link(node)
    for obj in imported:
        obj.parent = node

    raw_dims = dims_map.get(part["name"])
    if raw_dims is None:
        raise KeyError(f"No dims entry for '{part['name']}' in component_dims.json")

    parent_name = part.get("parent")
    parent_world_scale = (
        world_scales[parent_name]
        if parent_name and parent_name in world_scales
        else [1.0, 1.0, 1.0]
    )

    node_scale = [
        part["world_size"][axis] / (parent_world_scale[axis] * raw_dims["size"][axis])
        for axis in range(3)
    ]
    euler_deg = part["euler_deg"]
    scaled_raw_center = [node_scale[axis] * raw_dims["center"][axis] for axis in range(3)]

    if any(abs(value) > 0.01 for value in euler_deg):
        rotation = Euler([math.radians(value) for value in euler_deg], "XYZ").to_matrix()
        rotated_center = list(rotation @ Vector(scaled_raw_center))
    else:
        rotated_center = scaled_raw_center

    node_origin = [
        part["world_center"][axis] / parent_world_scale[axis] - rotated_center[axis]
        for axis in range(3)
    ]

    node.location = Vector(node_origin)
    node.rotation_euler = Euler([math.radians(value) for value in euler_deg], "XYZ")
    node.scale = Vector(node_scale)

    world_scales[part["name"]] = [
        part["world_size"][axis] / raw_dims["size"][axis] for axis in range(3)
    ]
    return node


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    args = parse_blender_args(parser)

    layout = load_json_file(args.layout)
    run_dir = Path(layout["root"]).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    dims_map = load_dims_file(run_dir)
    clear_scene()

    world_scales: dict[str, list[float]] = {}
    nodes: dict[str, object] = {}
    for part in layout["parts"]:
        nodes[part["name"]] = place_part(part, run_dir, dims_map, world_scales)

    for part in layout["parts"]:
        parent_name = part.get("parent")
        if parent_name:
            child_node = nodes[part["name"]]
            child_node.parent = nodes[parent_name]
            child_node.matrix_parent_inverse.identity()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
