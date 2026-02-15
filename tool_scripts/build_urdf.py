"""build_urdf.py — Convert the assembly IR + joint props into a URDF.

Pure Python (no Blender). Merges ``assembly.json`` (link tree, parent-relative
origins, mesh paths) with ``joint_props.json`` (joint axes and limits) and emits
a ``model.urdf`` that PyBullet (or any URDF viewer) can load. Mesh filenames are
written relative to the URDF file so the output directory is self-contained.

Run::

    python build_urdf.py \\
        --assembly ../.intermediate/dishwasher/001/iterations/006/assembly.json \\
        --joint-props ../.intermediate/dishwasher/001/joint_props.json \\
        --output ../.intermediate/dishwasher/001/iterations/006/model.urdf

The root link (``parent: null``) gets no joint; load it with
``useFixedBase=True``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--joint-props", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def resolve_mesh(root: Path, mesh: str, urdf_dir: Path) -> str:
    """Resolve a mesh path against root and express it relative to the URDF dir."""
    mesh_path = Path(mesh)
    if not mesh_path.is_absolute():
        mesh_path = (root / mesh_path).resolve()
    return os.path.relpath(mesh_path, urdf_dir)


def add_link(robot: ET.Element, name: str, mesh_filename: str) -> None:
    link = ET.SubElement(robot, "link", {"name": name})
    for tag in ("visual", "collision"):
        element = ET.SubElement(link, tag)
        geometry = ET.SubElement(element, "geometry")
        ET.SubElement(geometry, "mesh", {"filename": mesh_filename})


def add_joint(robot: ET.Element, link: dict, joint: dict) -> None:
    joint_type = joint["type"]
    el = ET.SubElement(
        robot, "joint", {"name": joint["joint_name"], "type": joint_type}
    )
    ET.SubElement(el, "parent", {"link": link["parent"]})
    ET.SubElement(el, "child", {"link": link["name"]})

    xyz = link["origin"]["xyz"]
    rpy = [math.radians(v) for v in link["origin"]["rpy_deg"]]
    ET.SubElement(
        el,
        "origin",
        {
            "xyz": " ".join(repr(float(v)) for v in xyz),
            "rpy": " ".join(repr(float(v)) for v in rpy),
        },
    )

    if joint_type == "fixed":
        return

    axis = joint["axis"]
    ET.SubElement(el, "axis", {"xyz": " ".join(repr(float(v)) for v in axis)})

    limit = joint["limit"]
    attrs = {}
    if joint_type in ("revolute", "prismatic"):
        attrs["lower"] = repr(float(limit["lower"]))
        attrs["upper"] = repr(float(limit["upper"]))
    attrs["effort"] = repr(float(limit["effort"]))
    attrs["velocity"] = repr(float(limit["velocity"]))
    ET.SubElement(el, "limit", attrs)


def build_urdf(assembly: dict, joint_props: dict, urdf_dir: Path) -> ET.ElementTree:
    root = Path(assembly["root"]).expanduser().resolve()
    joints_by_child = {j["child"]: j for j in joint_props["joints"]}

    robot = ET.Element("robot", {"name": assembly["robot_name"]})
    for link in assembly["links"]:
        mesh = resolve_mesh(root, link["collision_mesh"], urdf_dir)
        add_link(robot, link["name"], mesh)

    for link in assembly["links"]:
        if not link["parent"]:
            continue
        joint = joints_by_child.get(link["name"])
        if joint is None:
            raise KeyError(f"No joint props for child link '{link['name']}'")
        add_joint(robot, link, joint)

    return ET.ElementTree(robot)


def main() -> None:
    args = parse_args()
    assembly = load_json(args.assembly)
    joint_props = load_json(args.joint_props)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    tree = build_urdf(assembly, joint_props, output.parent)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="unicode", xml_declaration=False)
    output.write_text(
        '<?xml version="1.0"?>\n' + output.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
