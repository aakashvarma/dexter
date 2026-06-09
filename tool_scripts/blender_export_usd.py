"""blender_export_usd.py — Export an assembled scene to USD for Isaac Sim.

What it does
------------
Runs inside Blender (``bpy``). Opens an ``assembled.blend`` and writes a ``.usda``
with all geometry nested under ``--root-prim-path`` (default ``/World/Robot``).

Blender is natively Z-up, which is also what Isaac Sim expects, so the exporter
runs with ``convert_orientation=False`` to keep the scene's native Z-up axes
(setting a Y-up conversion here would tip the whole asset on its side in Isaac
Sim). Geometry and materials only — no PhysX schemas.

Alongside the USD it writes ``<output_stem>_prim_map.json`` mapping each Blender
object name to the prim path it received in the exported stage.

Run::

    blender --background --python blender_export_usd.py -- \\
        --blend ../.intermediate/dishwasher/001/iterations/006/assembled.blend \\
        --output ../.intermediate/dishwasher/001/robot.usda
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root-prim-path", default="/World/Robot")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def usd_safe(name: str) -> str:
    """Sanitize a Blender object name into a valid USD identifier.

    Used when building ``robot_prim_map.json`` for downstream prim-path lookup.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not safe or not (safe[0].isalpha() or safe[0] == "_"):
        safe = "_" + safe
    return safe


def prim_path(obj, root_prim_path: str) -> str:
    chain = []
    cursor = obj
    while cursor is not None:
        chain.append(usd_safe(cursor.name))
        cursor = cursor.parent
    chain.reverse()
    return root_prim_path.rstrip("/") + "/" + "/".join(chain)


def supported_kwargs(desired: dict) -> dict:
    """Drop kwargs the installed Blender's usd_export operator does not expose."""
    valid = set(bpy.ops.wm.usd_export.get_rna_type().properties.keys())
    return {k: v for k, v in desired.items() if k in valid}


def pack_images() -> None:
    """Ensure every image in the scene is packed into the blend file.

    GLBs imported via ``bpy.ops.import_scene.gltf`` embed their textures as
    packed images.  Any that are still referencing an external file path would
    silently be skipped by the USD exporter, so we pack them all here so the
    exporter can extract them into the ``textures/`` directory next to the USD.
    """
    for img in bpy.data.images:
        if img.source in {"FILE", "SEQUENCE"} and not img.packed_file:
            try:
                img.pack()
            except Exception as exc:
                print(f"[WARN] Could not pack image '{img.name}': {exc}")


def main() -> None:
    args = parse_args()
    blend = Path(args.blend).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(blend))

    # Pack loose textures so the USD exporter can extract them.
    pack_images()

    kwargs = supported_kwargs(
        {
            "filepath": str(output),
            "export_materials": True,
            "export_uvmaps": True,
            "export_normals": True,
            # export_textures: copy all images into a textures/ subdirectory
            # next to the USD file so Isaac Sim can resolve them.
            "export_textures": True,
            "overwrite_textures": True,
            "root_prim_path": args.root_prim_path,
            "convert_orientation": False,
        }
    )
    bpy.ops.wm.usd_export(**kwargs)

    prim_map = {
        obj.name: prim_path(obj, args.root_prim_path)
        for obj in bpy.data.objects
        if obj.type in {"MESH", "EMPTY"}
    }
    map_path = output.with_name(f"{output.stem}_prim_map.json")
    map_path.write_text(json.dumps(prim_map, indent=2), encoding="utf-8")

    print(f"Wrote {output}")
    print(f"Wrote {map_path}")


if __name__ == "__main__":
    main()
