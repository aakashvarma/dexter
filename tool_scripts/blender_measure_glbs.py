"""Measure each GLB's world bounding box and write component_dims.json.

Run::

    blender --background --python blender_measure_glbs.py -- \\
        --glbs-dir ../.intermediate/dishwasher/001/component_glbs \\
        --output ../.intermediate/dishwasher/001/component_dims.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

from common import parse_blender_args, validate_schema, write_json_file


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def measure_glb(path: Path) -> dict:
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(path))

    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    if not corners:
        raise RuntimeError(f"No mesh imported from {path}")

    bounds_min = Vector(min(corner[axis] for corner in corners) for axis in range(3))
    bounds_max = Vector(max(corner[axis] for corner in corners) for axis in range(3))
    return {
        "size": list(bounds_max - bounds_min),
        "center": list((bounds_min + bounds_max) / 2),
        "min": list(bounds_min),
        "max": list(bounds_max),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glbs-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parse_blender_args(parser)

    glbs_dir = Path(args.glbs_dir).expanduser().resolve()
    if not glbs_dir.is_dir():
        sys.exit(f"Error: glbs dir not found: {glbs_dir}")

    glb_paths = sorted(glbs_dir.glob("*.glb"))
    if not glb_paths:
        sys.exit(f"Error: no .glb files in {glbs_dir}")

    output_path = Path(args.output).expanduser().resolve()
    try:
        parts = {path.stem: measure_glb(path) for path in glb_paths}
    except RuntimeError as exc:
        sys.exit(f"Error: {exc}")

    write_json_file(output_path, {"parts": parts})
    print(f"Wrote {output_path}")
    validate_schema("component_dims.schema.json", output_path)


if __name__ == "__main__":
    main()
