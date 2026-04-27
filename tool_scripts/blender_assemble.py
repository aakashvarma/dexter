"""blender_assemble.py — Build a Blender scene from the assembly IR.

What it does
------------
Runs inside Blender (``bpy``). For each link in the assembly JSON:

1. Import the visual GLB (path resolved from ``root`` + ``visual_mesh``)
2. Parent imported meshes under an empty pivot
3. Derive the Blender-native ``scale`` and ``origin.xyz`` from the link's
   world-space ``world_size``, ``world_center``, and ``rpy_deg``, using the raw
   mesh bounding box from ``<root>/component_dims.json``:

       blender_scale[i]  = world_size[i] / (parent_blender_scale[i] * raw_size[i])
       origin_xyz[i]     = world_center[i] / parent_blender_scale[i]
                           − (R(rpy_deg) × (blender_scale × raw_center))[i]

   Dividing by ``parent_blender_scale`` is required because children are parented
   with ``matrix_parent_inverse.identity()``, so Blender multiplies the parent's
   scale into every child's local scale. For the root link ``parent_blender_scale``
   is ``[1, 1, 1]`` so the formula reduces to the simpler ``world_size / raw_size``.

4. Wire each link to its ``parent`` so children inherit the parent's transform
5. Save the scene as a ``.blend`` file

Run::

    blender --background --python blender_assemble.py -- \\
        --layout ../.intermediate/dishwasher/001/iterations/006/assembly.json \\
        --output ../.intermediate/dishwasher/001/iterations/006/assembled.blend

JSON schema: see ``schemas/assembly.schema.json``. Links must be listed
parent-before-child. ``component_dims.json`` is loaded automatically from the
``root`` directory stored in the assembly file.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_layout(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def load_dims_map(root: Path) -> dict[str, dict]:
    dims_path = root / "component_dims.json"
    dims_data = json.loads(dims_path.read_text(encoding="utf-8"))
    if "parts" in dims_data and isinstance(dims_data["parts"], dict):
        return dims_data["parts"]
    if "components" in dims_data:
        return {entry["name"]: entry for entry in dims_data["components"]}
    raise ValueError(f"Unrecognised component_dims.json format in {dims_path}")


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


def place_link(
    link: dict,
    root: Path,
    dims_map: dict[str, dict],
    blender_scales: dict[str, list[float]],
):
    """Import one link's GLB, derive its Blender transform from world values, and
    return the pivot empty. Stores the computed blender_scale in ``blender_scales``
    so children can use it as their parent_blender_scale."""
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

    raw = dims_map.get(link["name"])
    if raw is None:
        raise KeyError(f"No dims entry for '{link['name']}' in component_dims.json")

    parent_name = link.get("parent")
    parent_blender_scale = (
        blender_scales[parent_name] if parent_name and parent_name in blender_scales
        else [1.0, 1.0, 1.0]
    )

    # Divide by parent_blender_scale because children inherit the parent's scale
    # in Blender when parented with matrix_parent_inverse.identity(). The local
    # scale must be world_size / (parent_scale * raw_size) so that the effective
    # world scale ends up as world_size / raw_size (i.e., exactly world_size).
    blender_scale = [link["world_size"][i] / (parent_blender_scale[i] * raw["size"][i]) for i in range(3)]

    rpy_deg = link["rpy_deg"]
    scaled_raw_center = [blender_scale[i] * raw["center"][i] for i in range(3)]

    # Rotate scaled raw center by rpy_deg (XYZ Euler) to correctly invert the
    # world_center → origin_xyz formula when the part is rotated.
    if any(abs(v) > 0.01 for v in rpy_deg):
        rot = Euler([math.radians(v) for v in rpy_deg], "XYZ").to_matrix()
        rotated_center = list(rot @ Vector(scaled_raw_center))
    else:
        rotated_center = scaled_raw_center

    origin_xyz = [
        link["world_center"][i] / parent_blender_scale[i] - rotated_center[i]
        for i in range(3)
    ]

    pivot.location = Vector(origin_xyz)
    pivot.rotation_euler = Euler([math.radians(v) for v in rpy_deg], "XYZ")
    pivot.scale = Vector(blender_scale)

    blender_scales[link["name"]] = blender_scale
    return pivot


def main() -> None:
    args = parse_args()
    layout = load_layout(args.layout)
    root = Path(layout["root"]).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    dims_map = load_dims_map(root)

    clear_scene()

    # Process links in order (assembly guarantees parents before children).
    blender_scales: dict[str, list[float]] = {}
    pivots: dict[str, object] = {}
    for link in layout["links"]:
        pivots[link["name"]] = place_link(link, root, dims_map, blender_scales)

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
