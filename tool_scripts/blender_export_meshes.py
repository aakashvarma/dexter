"""blender_export_meshes.py — Export each GLB to a single OBJ.

Runs inside Blender (``bpy``). For every ``.glb`` in a directory it imports the
mesh, joins the imported objects into one, and writes ``<stem>.obj`` (plus its
``.mtl`` sidecar) so the URDF pipeline can reference plain OBJ geometry.

Run::

    blender --background --python blender_export_meshes.py -- \\
        --glbs-dir ../.intermediate/dishwasher/001/component_glbs \\
        --output-dir ../.intermediate/dishwasher/001/component_meshes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glbs-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-export OBJ files that already exist.",
    )
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)


def import_glb(path: Path) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        raise RuntimeError(f"No objects imported from {path}")
    return imported


def join_meshes(objs: list):
    """Join all mesh objects into one and return the active result."""
    meshes = [obj for obj in objs if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh objects to join")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def export_obj(path: Path, obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(bpy.ops.wm, "obj_export"):
        bpy.ops.wm.obj_export(
            filepath=str(path),
            export_selected_objects=True,
            export_materials=True,
            export_normals=True,
            export_uv=True,
            path_mode="RELATIVE",
        )
    else:
        bpy.ops.export_scene.obj(
            filepath=str(path),
            use_selection=True,
            use_materials=True,
            use_normals=True,
            use_uvs=True,
            path_mode="RELATIVE",
        )


def main() -> None:
    args = parse_args()
    glbs_dir = Path(args.glbs_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    glbs = sorted(glbs_dir.glob("*.glb"))
    if not glbs:
        raise FileNotFoundError(f"No .glb files in {glbs_dir}")

    for glb in glbs:
        dst = output_dir / f"{glb.stem}.obj"
        if dst.exists() and not args.overwrite:
            print(f"skip (exists): {dst.name}")
            continue
        clear_scene()
        imported = import_glb(glb)
        obj = join_meshes(imported)
        export_obj(dst, obj)
        print(f"wrote {dst}")

    print(f"Done. Output: {output_dir}")


if __name__ == "__main__":
    main()
