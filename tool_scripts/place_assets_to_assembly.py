"""place_assets_to_assembly.py — Migrate a legacy place_assets.json to assembly.json.

The pipeline replaced the flat ``place_assets.json`` layout with the
``assembly.json`` intermediate representation. This one-shot helper converts an
in-flight run's old layout so the orchestrator can resume it without redoing the
loop. Field mapping:

    assets[].name      -> links[].name
    assets[].parent    -> links[].parent (null for the root)
    assets[].path      -> links[].visual_mesh
    assets[].location  -> links[].origin.xyz
    assets[].rotation  -> links[].origin.rpy_deg
    assets[].scale     -> links[].scale

``collision_mesh`` is filled in as ``component_meshes_simp/<name>.obj`` and
``robot_name`` defaults to the run directory name (override with --robot-name).

Run::

    python place_assets_to_assembly.py \\
        --input ../.intermediate/dishwasher/001/iterations/006/place_assets.json \\
        --output ../.intermediate/dishwasher/001/iterations/006/assembly.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--robot-name",
        default=None,
        help="URDF robot name; defaults to the run (root) directory name.",
    )
    return parser.parse_args()


def convert(place_assets: dict, robot_name: str | None) -> dict:
    root = place_assets["root"]
    name = robot_name or Path(root).name
    links = []
    for asset in place_assets["assets"]:
        links.append(
            {
                "name": asset["name"],
                "parent": asset.get("parent"),
                "visual_mesh": asset["path"],
                "collision_mesh": f"component_meshes_simp/{asset['name']}.obj",
                "origin": {
                    "xyz": asset["location"],
                    "rpy_deg": asset["rotation"],
                },
                "scale": asset["scale"],
            }
        )
    return {"root": root, "robot_name": name, "links": links}


def main() -> None:
    args = parse_args()
    place_assets = json.loads(
        Path(args.input).expanduser().resolve().read_text(encoding="utf-8")
    )
    assembly = convert(place_assets, args.robot_name)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(assembly, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
