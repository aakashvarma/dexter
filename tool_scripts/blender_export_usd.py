"""Export an assembled scene to USD for Isaac Sim.

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

from common import parse_blender_args


def sanitize_usd_name(name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not safe_name or not (safe_name[0].isalpha() or safe_name[0] == "_"):
        safe_name = f"_{safe_name}"
    return safe_name


def build_prim_path(obj, root_prim_path: str) -> str:
    chain: list[str] = []
    cursor = obj
    while cursor is not None:
        chain.append(sanitize_usd_name(cursor.name))
        cursor = cursor.parent
    chain.reverse()
    return root_prim_path.rstrip("/") + "/" + "/".join(chain)


def supported_export_kwargs(desired: dict) -> dict:
    valid_keys = set(bpy.ops.wm.usd_export.get_rna_type().properties.keys())
    return {key: value for key, value in desired.items() if key in valid_keys}


def pack_images() -> None:
    for image in bpy.data.images:
        if image.source in {"FILE", "SEQUENCE"} and not image.packed_file:
            try:
                image.pack()
            except Exception as exc:
                print(
                    f"Warning: could not pack image '{image.name}': {exc}",
                    file=sys.stderr,
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root-prim-path", default="/World/Robot")
    args = parse_blender_args(parser)

    blend_path = Path(args.blend).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    pack_images()

    export_kwargs = supported_export_kwargs(
        {
            "filepath": str(output_path),
            "export_materials": True,
            "export_uvmaps": True,
            "export_normals": True,
            "export_textures": True,
            "overwrite_textures": True,
            "root_prim_path": args.root_prim_path,
            "convert_orientation": False,
        }
    )
    bpy.ops.wm.usd_export(**export_kwargs)

    prim_map = {
        obj.name: build_prim_path(obj, args.root_prim_path)
        for obj in bpy.data.objects
        if obj.type in {"MESH", "EMPTY"}
    }
    map_path = output_path.with_name(f"{output_path.stem}_prim_map.json")
    map_path.write_text(json.dumps(prim_map, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {output_path}")
    print(f"Wrote {map_path}")


if __name__ == "__main__":
    main()
