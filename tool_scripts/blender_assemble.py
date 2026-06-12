"""Build a Blender scene from assembly.json.

Run::

    blender --background --python blender_assemble.py -- \\
        --layout <run_dir>/iterations/006/assembly.json \\
        --output <run_dir>/iterations/006/assembled.blend
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_TOOL_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_TOOL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_SCRIPTS_DIR))

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

from common import exit_if_missing, load_json_file, parse_blender_args, validate_schema


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


def place_part(part: dict, run_dir: Path):
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

    node.location = Vector(part["node_origin"])
    node.rotation_euler = Euler([math.radians(value) for value in part["euler_deg"]], "XYZ")
    node.scale = Vector(part["node_scale"])
    return node


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    args = parse_blender_args(parser)

    layout_path = Path(args.layout).expanduser().resolve()
    exit_if_missing(layout_path, "assembly.json")
    validate_schema("assembly.schema.json", layout_path)

    layout = load_json_file(layout_path)
    run_dir = Path(layout["root"]).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    clear_scene()

    nodes: dict[str, object] = {}
    try:
        for part in layout["parts"]:
            nodes[part["name"]] = place_part(part, run_dir)
    except (KeyError, FileNotFoundError) as exc:
        sys.exit(f"Error: {exc}")

    for part in layout["parts"]:
        parent_name = part["parent"]
        if parent_name is not None:
            child_node = nodes[part["name"]]
            child_node.parent = nodes[parent_name]
            child_node.matrix_parent_inverse.identity()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
