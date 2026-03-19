"""blender_assemble.py — Build a Blender scene from the assembly IR.

What it does
------------
Runs inside Blender (``bpy``). For each link in the assembly JSON:

1. Import the visual GLB (path resolved from ``root`` + ``visual_mesh``)
2. Parent imported meshes under an empty pivot
3. Apply ``origin`` (``xyz`` + ``rpy_deg`` in degrees, XYZ) and ``scale`` to the pivot
4. Wire each link to its ``parent`` so children inherit the parent's transform
5. Save the scene as a ``.blend`` file

Run::

    blender --background --python blender_assemble.py -- \\
        --layout ../.intermediate/dishwasher/001/iterations/006/assembly.json \\
        --output ../.intermediate/dishwasher/001/iterations/006/assembled.blend

JSON schema: see ``schemas/assembly.schema.json``. Each link carries an
``origin`` (``xyz``, ``rpy_deg``) and ``scale`` interpreted relative to its
parent, so scaling or moving a parent moves all of its children.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_layout(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


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


def place_link(link: dict, root: Path):
    """Import one link's GLB, apply its transform, and return the pivot empty."""
    path = Path(link["visual_mesh"])
    if not path.is_absolute():
        path = (root / path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    imported = import_glb(path)
    pivot = bpy.data.objects.new(link["name"], None)
    bpy.context.collection.objects.link(pivot)

    for obj in imported:
        obj.parent = pivot

    origin = link["origin"]
    pivot.location = Vector(origin["xyz"])
    pivot.rotation_euler = Vector(math.radians(v) for v in origin["rpy_deg"])
    pivot.scale = Vector(link["scale"])
    return pivot


def main() -> None:
    args = parse_args()
    layout = load_layout(args.layout)
    root = Path(layout["root"]).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    clear_scene()
    pivots = {link["name"]: place_link(link, root) for link in layout["links"]}

    # Wire up parenting so children inherit their parent's transform. Keep the
    # local basis intact (identity parent-inverse) so transforms stay relative.
    for link in layout["links"]:
        parent = link.get("parent")
        if parent:
            child = pivots[link["name"]]
            child.parent = pivots[parent]
            child.matrix_parent_inverse.identity()

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
