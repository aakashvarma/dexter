"""blender_render_views.py — Render PNG views, auto-framed to the assembly.

Runs inside Blender (``bpy``). Opens a ``.blend``, computes the scene bounding
box, then for each camera entry places a camera along ``direction`` looking at
the box center, at a distance that fits the whole assembly in frame. A white
world background and a co-located light keep renders bright and comparable to a
plain-background source photo.

Run::

    blender --background --python blender_render_views.py -- \\
        --blend ../.intermediate/dishwasher/001/iterations/001/assembled.blend \\
        --cameras ../.intermediate/dishwasher/001/iterations/001/render_views.json \\
        --output-dir ../.intermediate/dishwasher/001/iterations/001/renders/

JSON schema (per camera: name, direction, output, light_energy, light_type;
optional margin)::

    {
      "resolution": [1920, 1080],
      "samples": 64,
      "engine": "CYCLES",
      "file_format": "PNG",
      "cameras": [
        {
          "name": "front",
          "direction": [0.0, -1.0, 0.2],  # view direction from the assembly center
          "margin": 1.3,                  # >1 leaves padding around the assembly
          "output": "front.png",
          "light_energy": 5.0,
          "light_type": "SUN"
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

DEFAULT_MARGIN = 1.3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--cameras", required=True)
    parser.add_argument("--output-dir", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_config(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def scene_bounds() -> tuple:
    """Return ``(center, radius)`` of the world bounding box of all meshes."""
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    center = (lo + hi) / 2
    return center, (hi - lo).length / 2


def set_white_background() -> None:
    """Give the scene a bright white world so renders match a plain source."""
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 1.0


def aim_rotation(location: Vector, look_at: Vector):
    """Euler rotation pointing local ``-Z`` from ``location`` toward ``look_at``."""
    return (look_at - location).to_track_quat("-Z", "Y").to_euler()


def create_shot(entry: dict, center: Vector, radius: float) -> tuple:
    """Create a camera and co-located light framing the assembly center."""
    direction = Vector(entry["direction"]).normalized()
    distance = radius * entry.get("margin", DEFAULT_MARGIN) / 0.4
    loc = center + direction * distance
    rot = aim_rotation(loc, center)

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.collection.objects.link(cam)
    cam.location, cam.rotation_euler = loc, rot

    light = bpy.data.objects.new("Light", bpy.data.lights.new("Light", type=entry["light_type"]))
    bpy.context.collection.objects.link(light)
    light.location, light.rotation_euler = loc, rot
    light.data.energy = entry["light_energy"]

    return cam, light


def delete_shot(cam, light) -> None:
    cam_data, light_data = cam.data, light.data
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.objects.remove(light, do_unlink=True)
    bpy.data.cameras.remove(cam_data)
    bpy.data.lights.remove(light_data)


def main() -> None:
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
    set_white_background()

    center, radius = scene_bounds()
    for entry in config["cameras"]:
        cam, light = create_shot(entry, center, radius)
        scene.camera = cam
        out = output_dir / entry["output"]
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {out}")
        delete_shot(cam, light)


if __name__ == "__main__":
    main()
