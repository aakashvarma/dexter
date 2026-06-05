"""blender_simplify_meshes.py — Decimate OBJ meshes for URDF viewing.

Runs inside Blender (``bpy``). For every ``.obj`` in the input directory it
merges duplicate vertices, decimates to an approximate target face count, and
writes the simplified OBJ (plus any ``.mtl`` sidecar) to the output directory.
The simplified meshes back the URDF visual/collision geometry.

Run::

    blender --background --python blender_simplify_meshes.py -- \\
        --input-dir ../.intermediate/dishwasher/001/component_meshes \\
        --output-dir ../.intermediate/dishwasher/001/component_meshes_simp \\
        --target-faces 100000
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import bpy  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--target-faces",
        type=int,
        default=100_000,
        help="Approximate face count per mesh after decimation.",
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=None,
        help="Fixed decimate ratio (0-1). Overrides --target-faces if set.",
    )
    parser.add_argument(
        "--merge-distance",
        type=float,
        default=1e-5,
        help="Merge duplicate vertices (meters) before decimating.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output meshes.",
    )
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def face_count(obj) -> int:
    return sum(len(poly.vertices) for poly in obj.data.polygons)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)


def import_obj(path: Path):
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        bpy.ops.import_scene.obj(filepath=str(path))
    if not bpy.context.selected_objects:
        raise RuntimeError(f"No objects imported from {path}")
    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    return obj


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


def cleanup_mesh(obj, merge_distance: float) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=merge_distance)
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)
    bpy.ops.object.mode_set(mode="OBJECT")


def decimate(obj, ratio: float) -> None:
    ratio = max(min(ratio, 1.0), 0.0001)
    mod = obj.modifiers.new(name="DecimateCollapse", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)


def process_one(
    src: Path,
    dst: Path,
    *,
    target_faces: int,
    ratio: float | None,
    merge_distance: float,
) -> None:
    print(f"\n=== {src.name} ===")
    t0 = time.time()
    clear_scene()
    obj = import_obj(src)
    print(f"  imported: {face_count(obj):,} faces")

    cleanup_mesh(obj, merge_distance)
    faces_clean = face_count(obj)
    print(f"  after merge duplicates: {faces_clean:,} faces")

    if ratio is None:
        use_ratio = 1.0 if faces_clean <= target_faces else target_faces / faces_clean
    else:
        use_ratio = ratio

    print(f"  decimate ratio: {use_ratio:.4f}")
    decimate(obj, use_ratio)
    print(f"  result: {face_count(obj):,} faces")

    export_obj(dst, obj)
    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"  wrote {dst} ({size_mb:.1f} MB) in {time.time() - t0:.1f}s")


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input dir not found: {input_dir}")

    obj_files = sorted(input_dir.glob("*.obj"))
    if not obj_files:
        raise FileNotFoundError(f"No .obj files in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for src in obj_files:
        dst = output_dir / src.name
        if dst.exists() and not args.overwrite:
            print(f"skip (exists): {dst.name}")
            continue
        process_one(
            src,
            dst,
            target_faces=args.target_faces,
            ratio=args.ratio,
            merge_distance=args.merge_distance,
        )
        mtl = src.with_suffix(".mtl")
        if mtl.is_file():
            shutil.copy2(mtl, output_dir / mtl.name)

    print(f"\nDone. Output: {output_dir}")


if __name__ == "__main__":
    main()
