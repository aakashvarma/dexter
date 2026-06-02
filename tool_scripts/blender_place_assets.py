"""blender_place_assets.py — Import GLBs from JSON and save a Blender scene.

What it does
------------
Runs inside Blender (``bpy``). For each entry in the layout JSON:

1. Import the GLB (path resolved from ``root`` + ``path``)
2. Parent imported meshes under an empty pivot
3. Apply ``location``, ``rotation`` (degrees, XYZ), and ``scale`` to the pivot
4. Save the scene as a ``.blend`` file

Run::

    blender --background --python blender_place_assets.py -- \\
        --layout ../.intermediate/dishwasher/001/place_assets.json \\
        --output ../.intermediate/dishwasher/001/assembled.blend

JSON schema (every key required)::

    {
      "root": "/path/to/project",       # base dir for relative GLB paths
      "assets": [
        {
          "path": "glbs/body.glb",      # GLB path (relative to root or absolute)
          "location": [0.0, 0.0, 0.0],  # pivot world position [x, y, z]
          "rotation": [0.0, 0.0, 0.0],  # pivot rotation in degrees, XYZ Euler
          "scale": [1.0, 1.0, 1.0]      # pivot scale [x, y, z]
        }
      ]
    }
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
    """Parse arguments passed after Blender's ``--`` separator.

    Returns:
        Parsed arguments with ``layout`` and ``output`` paths.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_layout(path: str) -> dict:
    """Load the asset layout JSON from disk.

    Args:
        path: Path to the layout file.

    Returns:
        Parsed JSON as a dictionary.
    """
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def clear_scene() -> None:
    """Remove all objects from the current Blender scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_glb(path: Path) -> list:
    """Import a GLB and return the objects created by the import.

    Args:
        path: Path to the ``.glb`` file.

    Returns:
        Newly created Blender objects.

    Raises:
        RuntimeError: If the import produces no objects.
    """
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        raise RuntimeError(f"No objects imported from {path}")
    return imported


def place_asset(entry: dict, root: Path) -> None:
    """Import one GLB and apply transform from a layout entry.

    Args:
        entry: One object from the ``assets`` list in the layout JSON.
        root: Base directory for resolving relative ``path`` values.
    """
    path = Path(entry["path"])
    if not path.is_absolute():
        path = (root / path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    imported = import_glb(path)
    pivot = bpy.data.objects.new(path.stem, None)
    bpy.context.collection.objects.link(pivot)

    for obj in imported:
        obj.parent = pivot
        obj.matrix_parent_inverse = pivot.matrix_world.inverted()

    pivot.location = Vector(entry["location"])
    pivot.rotation_euler = Vector(math.radians(v) for v in entry["rotation"])
    pivot.scale = Vector(entry["scale"])


def main() -> None:
    """Place all assets from the layout JSON and save a ``.blend`` file."""
    args = parse_args()
    layout = load_layout(args.layout)
    root = Path(layout["root"]).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    clear_scene()
    for entry in layout["assets"]:
        place_asset(entry, root)

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
