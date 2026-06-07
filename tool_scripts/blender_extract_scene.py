"""blender_extract_scene.py — Emit a physics-planning summary of an assembled scene.

What it does
------------
Runs inside Blender (``bpy``). Opens an ``assembled.blend`` and writes a compact
``scene.json`` describing every object the physics_spec subagent needs to reason
over: name, type, parent, the USD prim path ``blender_export_usd.py`` will emit,
the world-space bounding box, and the aggregate polygon count of the object and
all of its descendants.

It never serializes raw vertices: bounding boxes come from ``obj.bound_box`` (the
8 pre-computed corners) so the output stays small even for million-face meshes.

The ``usd_prim_path`` is computed by walking the Blender parent chain and
sanitizing each name the same way Blender's USD exporter does, then prefixing the
shared ``--root-prim-path`` (default ``/World/Robot``). The physics_spec subagent
copies these paths verbatim so they line up with the exported ``robot.usda``.

Run::

    blender --background --python blender_extract_scene.py -- \\
        --blend ../.intermediate/dishwasher/001/iterations/006/assembled.blend \\
        --output ../.intermediate/dishwasher/001/scene.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root-prim-path", default="/World/Robot")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def usd_safe(name: str) -> str:
    """Sanitize a Blender object name into a valid USD identifier.

    Mirrors ``pxr.Tf.MakeValidIdentifier``: any character outside
    ``[A-Za-z0-9_]`` becomes ``_`` and a leading non-letter is prefixed with
    ``_``. This must match what Blender's USD exporter produces so the prim
    paths in ``scene.json`` resolve against ``robot.usda``.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not safe or not (safe[0].isalpha() or safe[0] == "_"):
        safe = "_" + safe
    return safe


def prim_path(obj, root_prim_path: str) -> str:
    """Build the USD prim path for an object by walking its parent chain."""
    chain = []
    cursor = obj
    while cursor is not None:
        chain.append(usd_safe(cursor.name))
        cursor = cursor.parent
    chain.reverse()
    return root_prim_path.rstrip("/") + "/" + "/".join(chain)


def descendant_meshes(obj) -> list:
    """Return ``obj`` (if a mesh) plus every mesh in its descendant subtree."""
    meshes = [obj] if obj.type == "MESH" else []
    for child in obj.children:
        meshes.extend(descendant_meshes(child))
    return meshes


def aggregate_geometry(obj) -> dict:
    """Aggregate world bbox and polygon count over obj + its descendant meshes."""
    meshes = descendant_meshes(obj)
    corners = [
        mesh.matrix_world @ Vector(corner)
        for mesh in meshes
        for corner in mesh.bound_box
    ]
    poly_count = sum(len(mesh.data.polygons) for mesh in meshes)
    if corners:
        lo = [min(c[i] for c in corners) for i in range(3)]
        hi = [max(c[i] for c in corners) for i in range(3)]
    else:
        lo = hi = [0.0, 0.0, 0.0]
    return {"bbox_min": lo, "bbox_max": hi, "poly_count": poly_count}


def describe(obj, root_prim_path: str) -> dict:
    geom = aggregate_geometry(obj)
    materials = []
    if obj.type == "MESH" and obj.data is not None:
        materials = [m.name for m in obj.data.materials if m is not None]
    return {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "usd_prim_path": prim_path(obj, root_prim_path),
        "location": list(obj.location),
        "rotation_euler_deg": [math.degrees(a) for a in obj.rotation_euler],
        "scale": list(obj.scale),
        "bbox_min": geom["bbox_min"],
        "bbox_max": geom["bbox_max"],
        "poly_count": geom["poly_count"],
        "materials": materials,
        "children": [c.name for c in obj.children],
    }


def main() -> None:
    args = parse_args()
    blend = Path(args.blend).expanduser().resolve()
    bpy.ops.wm.open_mainfile(filepath=str(blend))

    objects = [
        describe(obj, args.root_prim_path)
        for obj in sorted(bpy.data.objects, key=lambda o: o.name)
        if obj.type in {"MESH", "EMPTY"}
    ]
    scene = {
        "blend_file": str(blend),
        "root_prim_path": args.root_prim_path,
        "unit_scale": bpy.context.scene.unit_settings.scale_length,
        "objects": objects,
    }

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
