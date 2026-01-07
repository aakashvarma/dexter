"""blender_render_views.py — Render PNG views from a Blender scene.

What it does
------------
Runs inside Blender (``bpy``). Opens a ``.blend`` file, applies render
settings from JSON, then for each camera entry:

1. Create a camera at ``location`` facing ``look_at``
2. Create a sun at the same pose (light from the view direction)
3. Render one image to ``output_dir`` / ``output``
4. Delete the temporary camera and light

Run::

    blender --background --python blender_render_views.py -- \\
        --blend ../.intermediate/dishwasher/001/assembled.blend \\
        --cameras ../.intermediate/dishwasher/001/render_views.json \\
        --output-dir ../.intermediate/dishwasher/001/renders/

JSON schema (every key required)::

    {
      "resolution": [1920, 1080],       # render size [width, height] in pixels
      "samples": 64,                    # Cycles sample count
      "engine": "CYCLES",               # Blender render engine name
      "file_format": "PNG",             # output image format
      "cameras": [
        {
          "location": [0.0, -12.0, 4.5],  # camera world position [x, y, z]
          "look_at": [0.0, -1.0, 1.8],    # world point the camera faces
          "output": "front.png",          # filename under --output-dir
          "light_energy": 3.0,            # sun strength for this shot
          "light_type": "SUN"             # Blender light type (co-located with camera)
        }
      ]
    }

Logic: Blender cameras and sun lights point along local ``-Z``. Rotation aims
``-Z`` from ``location`` toward ``look_at``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def parse_args() -> argparse.Namespace:
    """Parse arguments passed after Blender's ``--`` separator.

    Returns:
        Parsed arguments with ``blend``, ``cameras``, and ``output_dir`` paths.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--cameras", required=True)
    parser.add_argument("--output-dir", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_config(path: str) -> dict:
    """Load the camera and render settings JSON from disk.

    Args:
        path: Path to the cameras config file.

    Returns:
        Parsed JSON as a dictionary.
    """
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def aim_rotation(location: Vector, look_at: Vector):
    """Compute Euler rotation pointing local ``-Z`` from ``location`` to ``look_at``.

    Args:
        location: Camera or light world position.
        look_at: World point to face.

    Returns:
        Euler rotation for Blender camera/light objects.
    """
    return (look_at - location).to_track_quat("-Z", "Y").to_euler()


def create_shot(entry: dict) -> tuple:
    """Create a temporary camera and co-located light for one camera entry.

    Args:
        entry: One object from the ``cameras`` list in the config JSON.

    Returns:
        ``(camera_object, light_object)`` at the pose from ``location`` and ``look_at``.
    """
    loc = Vector(entry["location"])
    rot = aim_rotation(loc, Vector(entry["look_at"]))

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.collection.objects.link(cam)
    cam.location, cam.rotation_euler = loc, rot

    light = bpy.data.objects.new("Light", bpy.data.lights.new("Light", type=entry["light_type"]))
    bpy.context.collection.objects.link(light)
    light.location, light.rotation_euler = loc, rot
    light.data.energy = entry["light_energy"]

    return cam, light


def delete_shot(cam, light) -> None:
    """Remove temporary camera and light objects after a render.

    Args:
        cam: Camera object from :func:`create_shot`.
        light: Light object from :func:`create_shot`.
    """
    cam_data, light_data = cam.data, light.data
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.objects.remove(light, do_unlink=True)
    bpy.data.cameras.remove(cam_data)
    bpy.data.lights.remove(light_data)


def main() -> None:
    """Open the blend, render one image per camera entry, and write PNGs."""
    args = parse_args()
    config = load_config(args.cameras)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).expanduser().resolve()))

    scene = bpy.context.scene
    scene.render.engine = config["engine"]
    scene.cycles.samples = config["samples"]
    scene.render.resolution_x, scene.render.resolution_y = config["resolution"]
    scene.render.image_settings.file_format = config["file_format"]

    for entry in config["cameras"]:
        cam, light = create_shot(entry)
        scene.camera = cam
        out = output_dir / entry["output"]
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {out}")
        delete_shot(cam, light)


if __name__ == "__main__":
    main()
