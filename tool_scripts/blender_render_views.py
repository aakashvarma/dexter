"""Render PNG views auto-framed to the assembly.

Run::

    blender --background --python blender_render_views.py -- \\
        --blend ../.intermediate/dishwasher/001/iterations/001/assembled.blend \\
        --cameras ../.intermediate/dishwasher/001/iterations/001/render_views.json \\
        --output-dir ../.intermediate/dishwasher/001/iterations/001/renders/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

from common import exit_if_missing, load_json_file, parse_blender_args, validate_schema

DEFAULT_MARGIN = 1.3


def scene_bounds() -> tuple[Vector, float]:
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    bounds_min = Vector(min(corner[axis] for corner in corners) for axis in range(3))
    bounds_max = Vector(max(corner[axis] for corner in corners) for axis in range(3))
    center = (bounds_min + bounds_max) / 2
    return center, (bounds_max - bounds_min).length / 2


def set_white_background() -> None:
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    background.inputs[1].default_value = 1.0


def aim_rotation(location: Vector, look_at: Vector):
    return (look_at - location).to_track_quat("-Z", "Y").to_euler()


def create_shot(entry: dict, center: Vector, radius: float) -> tuple:
    direction = Vector(entry["direction"]).normalized()
    distance = radius * entry.get("margin", DEFAULT_MARGIN) / 0.4
    location = center + direction * distance
    rotation = aim_rotation(location, center)

    camera = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.collection.objects.link(camera)
    camera.location, camera.rotation_euler = location, rotation

    light = bpy.data.objects.new("Light", bpy.data.lights.new("Light", type=entry["light_type"]))
    bpy.context.collection.objects.link(light)
    light.location, light.rotation_euler = location, rotation
    light.data.energy = entry["light_energy"]

    return camera, light


def delete_shot(camera, light) -> None:
    camera_data, light_data = camera.data, light.data
    bpy.data.objects.remove(camera, do_unlink=True)
    bpy.data.objects.remove(light, do_unlink=True)
    bpy.data.cameras.remove(camera_data)
    bpy.data.lights.remove(light_data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--cameras", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parse_blender_args(parser)

    blend_path = Path(args.blend).expanduser().resolve()
    cameras_path = Path(args.cameras).expanduser().resolve()
    exit_if_missing(blend_path, "assembled.blend")
    exit_if_missing(cameras_path, "render_views.json")
    validate_schema("render_views.schema.json", cameras_path)

    config = load_json_file(cameras_path)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    scene = bpy.context.scene
    scene.render.engine = config["engine"]
    scene.cycles.samples = config["samples"]
    scene.render.resolution_x, scene.render.resolution_y = config["resolution"]
    scene.render.image_settings.file_format = config["file_format"]
    set_white_background()

    center, radius = scene_bounds()
    for entry in config["cameras"]:
        camera, light = create_shot(entry, center, radius)
        scene.camera = camera
        output_path = output_dir / entry["output"]
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        delete_shot(camera, light)


if __name__ == "__main__":
    main()
