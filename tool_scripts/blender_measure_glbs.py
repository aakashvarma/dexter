"""blender_measure_glbs.py — Measure each GLB's world bounding box.

Runs inside Blender (``bpy``). For every ``.glb`` in a directory it imports the
mesh, computes the world-space bounding box, then writes one ``component_dims``
JSON so the placement and critic agents can reason in real units.

Run::

    blender --background --python blender_measure_glbs.py -- \\
        --glbs-dir ../.intermediate/dishwasher/001/component_glbs \\
        --output ../.intermediate/dishwasher/001/component_dims.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glbs-dir", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def measure_glb(path: Path) -> dict:
    """Import one GLB, return its world bbox size/center/min/max."""
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

    lo = Vector((min(c[i] for c in corners) for i in range(3)))
    hi = Vector((max(c[i] for c in corners) for i in range(3)))
    return {
        "size": list(hi - lo),
        "center": list((lo + hi) / 2),
        "min": list(lo),
        "max": list(hi),
    }


def main() -> None:
    args = parse_args()
    glbs_dir = Path(args.glbs_dir).expanduser().resolve()
    parts = {p.stem: measure_glb(p) for p in sorted(glbs_dir.glob("*.glb"))}

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"parts": parts}, indent=2), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
