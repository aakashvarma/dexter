#!/usr/bin/env python3
"""
compute_placement_scales.py
===========================
Pre-compute scale factors and placement origins for every part in an articulated
asset so that the LLM placement agent starts from geometrically correct values
rather than guessing.

Reads
-----
  parts.json        — part tree with geometry fields:
                        size_fraction      [w, d, h] fractions of parent world dims
                        position_in_parent keyword string: "left", "bottom-center", etc.
                        hinge_side         "left"|"right"|"top"|"bottom"  (revolute)
                        slide_axis         "-y"|"+y"|"-x"|"+x"|"+z"|"-z" (prismatic)
  component_dims.json — raw GLB bounding boxes (size, center, min, max in metres)

Writes
------
  placement_hints.json  — root_scale, per-part child_scale, closed_pose, open_pose

Usage
-----
  python3 tool_scripts/compute_placement_scales.py \\
      --parts       <run_dir>/parts.json \\
      --dims        <run_dir>/component_dims.json \\
      --output      <run_dir>/placement_hints.json \\
      --root-world-dims 0.90 0.70 1.78 \\
      [--open-angle-deg  90] \\
      [--pullout-fraction 0.5] \\
      [--child-world-dims left_door 0.44 0.04 1.14]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def rotation_matrix_z(deg: float) -> list[list[float]]:
    """3×3 rotation matrix for a rotation of `deg` degrees around the Z axis."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def rotation_matrix_x(deg: float) -> list[list[float]]:
    """3×3 rotation matrix for a rotation of `deg` degrees around the X axis."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rotation_matrix_y(deg: float) -> list[list[float]]:
    """3×3 rotation matrix for a rotation of `deg` degrees around the Y axis."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def mat_vec(R: list[list[float]], v: list[float]) -> list[float]:
    """Multiply 3×3 matrix R by column vector v."""
    return [sum(R[i][j] * v[j] for j in range(3)) for i in range(3)]


def compute_child_scale(
    target_world: list[float],
    parent_effective_scale: list[float],
    raw_size: list[float],
) -> list[float]:
    """
    child_scale[axis] = target_world[axis] / (parent_effective_scale[axis] * raw_size[axis])

    This is the non-negotiable formula for scale inheritance in blender_assemble.py.
    """
    result = []
    for i in range(3):
        denom = parent_effective_scale[i] * raw_size[i]
        if abs(denom) < 1e-9:
            print(f"  Warning: near-zero denominator on axis {i} — setting scale to 1.0", file=sys.stderr)
            result.append(1.0)
        else:
            result.append(target_world[i] / denom)
    return result


def compute_origin_xyz(
    target_world_center: list[float],
    parent_effective_scale: list[float],
    child_scale: list[float],
    raw_mesh_center: list[float],
    rpy_deg: list[float] | None = None,
) -> list[float]:
    """
    Back-compute origin_xyz from the desired world-space centre.

    Without rotation:
        origin_xyz[i] = target_world_center[i] / parent_scale[i]
                        - child_scale[i] * raw_mesh_center[i]

    With rotation R:
        origin_xyz = target_world_center / parent_scale
                     - R * (child_scale * raw_mesh_center)
    """
    scaled_center = [child_scale[i] * raw_mesh_center[i] for i in range(3)]

    if rpy_deg is not None:
        rx, ry, rz = rpy_deg
        # Apply rotations in Blender order: Z then Y then X
        v = scaled_center
        if abs(rz) > 0.01:
            v = mat_vec(rotation_matrix_z(rz), v)
        if abs(ry) > 0.01:
            v = mat_vec(rotation_matrix_y(ry), v)
        if abs(rx) > 0.01:
            v = mat_vec(rotation_matrix_x(rx), v)
        scaled_center = v

    return [
        target_world_center[i] / parent_effective_scale[i] - scaled_center[i]
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# Geometry extraction helpers
# ---------------------------------------------------------------------------

def _parse_pos_keywords(pos: str) -> tuple[str, str]:
    """
    Split a position_in_parent string into (horizontal_kw, vertical_kw).
    Accepted horizontal: left, center-left, center, center-right, right.
    Accepted vertical:   bottom, lower, middle, upper, top.
    """
    p = pos.lower()
    horiz = "center"
    vert  = "middle"

    if "center-left" in p:
        horiz = "center-left"
    elif "center-right" in p:
        horiz = "center-right"
    elif "left" in p:
        horiz = "left"
    elif "right" in p:
        horiz = "right"

    if "bottom" in p:
        vert = "bottom"
    elif "lower" in p:
        vert = "lower"
    elif "top" in p:
        vert = "top"
    elif "upper" in p:
        vert = "upper"

    return horiz, vert


def get_world_dims(
    child: dict,
    parent_world: list[float],
    overrides: dict[str, list[float]],
) -> list[float]:
    """
    Return the target world [W, D, H] for this part.

    Priority:
      1. Explicit --child-world-dims override from the CLI.
      2. size_fraction field in parts.json  ← preferred
      3. Fallback: [0.5, 0.5, 0.5] of parent with a warning.
    """
    name = child["name"]
    if name in overrides:
        return list(overrides[name])

    sf = child.get("size_fraction")
    if sf is None:
        print(
            f"  [WARN] '{name}' has no size_fraction — falling back to [0.5, 0.5, 0.5] of parent. "
            "Re-run analyze to add size_fraction.",
            file=sys.stderr,
        )
        sf = [0.5, 0.5, 0.5]

    return [parent_world[i] * sf[i] for i in range(3)]


def get_y_mode(child: dict) -> str:
    """
    Determine whether this part sits at the FRONT face of the parent
    ('front') or is centered in depth ('center') when closed.

    Logic:
      - Left/right/bottom-hinged revolute → flush with front face (front)
      - Top-hinged revolute (lid) → centered in depth (center)
      - Prismatic -y (forward drawer) → flush with front face (front)
      - Prismatic +z/-z/+x/-x → centered in depth (center)
      - Fixed or unknown → centered (center)
    """
    jt = child.get("joint_type", "fixed")
    hs = child.get("hinge_side")
    sa = child.get("slide_axis", "-y")

    if jt == "revolute":
        if hs in ("left", "right", "bottom"):
            return "front"
        if hs == "top":
            return "center"

    if jt == "prismatic":
        return "front" if sa == "-y" else "center"

    return "center"


def get_closed_world_center(
    child: dict,
    siblings: list[dict],
    parent_world: list[float],
    parent_world_center: list[float],
    child_world: list[float],
) -> list[float]:
    """
    Compute the world-space centre of this part in its closed/default pose.

    Uses:
      - position_in_parent for X and Z placement
      - hinge_side / slide_axis for Y (depth) placement
    """
    pW, pD, pH = parent_world
    cW, cD, cH = child_world

    px_min = parent_world_center[0] - pW / 2
    px_max = parent_world_center[0] + pW / 2
    py_min = parent_world_center[1] - pD / 2   # front face (−Y in Blender)
    pz_min = parent_world_center[2] - pH / 2   # floor
    pz_max = parent_world_center[2] + pH / 2   # ceiling

    pos = child.get("position_in_parent", "center")
    horiz, vert = _parse_pos_keywords(pos)

    # --- X ---
    if horiz == "left":
        cx = px_min + cW / 2
    elif horiz == "right":
        cx = px_max - cW / 2
    elif horiz == "center-left":
        cx = parent_world_center[0] - cW / 2
    elif horiz == "center-right":
        cx = parent_world_center[0] + cW / 2
    else:
        # "center" — if multiple same-type siblings and no explicit side, split evenly
        jt = child.get("joint_type", "fixed")
        same_type = sorted(
            [s for s in siblings if s.get("joint_type") == jt],
            key=lambda s: s["name"],
        )
        if len(same_type) > 1:
            idx = next(
                (i for i, s in enumerate(same_type) if s["name"] == child["name"]), 0
            )
            slot_w = pW / len(same_type)
            cx = px_min + idx * slot_w + slot_w / 2
        else:
            cx = parent_world_center[0]

    # --- Y (depth) ---
    y_mode = get_y_mode(child)
    cy = (py_min + cD / 2) if y_mode == "front" else parent_world_center[1]

    # --- Z ---
    if vert == "bottom":
        cz = pz_min + cH / 2
    elif vert == "lower":
        cz = pz_min + cH          # one child-height above the floor
    elif vert == "top":
        cz = pz_max - cH / 2
    elif vert == "upper":
        cz = pz_max - cH          # one child-height below the ceiling
    else:
        cz = parent_world_center[2]  # "middle" / unspecified

    return [cx, cy, cz]


# ---------------------------------------------------------------------------
# Open-pose computation
# ---------------------------------------------------------------------------

def compute_revolute_open_hint(
    child: dict,
    closed_world_center: list[float],
    child_world: list[float],
    parent_effective_scale: list[float],
    child_scale: list[float],
    raw_dims: dict,
    cfg: dict,
) -> dict:
    """
    Compute origin_xyz and rpy_deg for the OPEN pose of a revolute part.

    Rotation conventions (right-hand rule, Blender Z-up −Y-forward):
      hinge_side='left'   → rpy_z = −open_angle  (CCW around Z looks leftward)
      hinge_side='right'  → rpy_z = +open_angle
      hinge_side='bottom' → rpy_x = −open_angle  (top swings forward)
      hinge_side='top'    → rpy_x = +open_angle  (bottom swings forward/backward)
    """
    hinge_side = child.get("hinge_side")
    if not hinge_side:
        print(
            f"  [WARN] '{child['name']}' has no hinge_side — defaulting to 'left'. "
            "Add hinge_side to parts.json for accurate open-pose.",
            file=sys.stderr,
        )
        hinge_side = "left"

    open_angle = cfg["open_angle_deg"]
    cW, cD, cH = child_world
    cx, cy, cz = closed_world_center

    if hinge_side == "left":
        hinge_world_x = cx - cW / 2
        rpy_deg = [0.0, 0.0, -open_angle]
        # hinge stays at its world position; pivot point is at hinge_x, cy, cz
        hinge_local = [hinge_world_x, cy, cz]
        open_world_center = _rotate_point_around_hinge(
            [cx, cy, cz], hinge_local, rotation_matrix_z(-open_angle)
        )

    elif hinge_side == "right":
        hinge_world_x = cx + cW / 2
        rpy_deg = [0.0, 0.0, open_angle]
        hinge_local = [hinge_world_x, cy, cz]
        open_world_center = _rotate_point_around_hinge(
            [cx, cy, cz], hinge_local, rotation_matrix_z(open_angle)
        )

    elif hinge_side == "bottom":
        hinge_world_z = cz - cH / 2
        rpy_deg = [-open_angle, 0.0, 0.0]
        hinge_local = [cx, cy, hinge_world_z]
        open_world_center = _rotate_point_around_hinge(
            [cx, cy, cz], hinge_local, rotation_matrix_x(-open_angle)
        )

    elif hinge_side == "top":
        hinge_world_z = cz + cH / 2
        rpy_deg = [open_angle, 0.0, 0.0]
        hinge_local = [cx, cy, hinge_world_z]
        open_world_center = _rotate_point_around_hinge(
            [cx, cy, cz], hinge_local, rotation_matrix_x(open_angle)
        )

    else:
        print(f"  [WARN] Unknown hinge_side '{hinge_side}' for '{child['name']}' — no open pose computed.", file=sys.stderr)
        return {}

    open_origin_xyz = compute_origin_xyz(
        open_world_center, parent_effective_scale, child_scale,
        raw_dims["center"], rpy_deg
    )

    return {
        "hinge_side": hinge_side,
        "open_angle_deg": open_angle,
        "open_rpy_deg": [round(v, 4) for v in rpy_deg],
        "open_origin_xyz": [round(v, 5) for v in open_origin_xyz],
        "open_world_center": [round(v, 5) for v in open_world_center],
        "note": (
            f"Rotate around {hinge_side} edge by ±{open_angle}°. "
            "Flip rpy_deg sign if image shows the door opening the other way."
        ),
    }


def _rotate_point_around_hinge(
    point: list[float],
    hinge: list[float],
    R: list[list[float]],
) -> list[float]:
    """Rotate `point` around `hinge` using rotation matrix R."""
    v = [point[i] - hinge[i] for i in range(3)]
    v_rot = mat_vec(R, v)
    return [v_rot[i] + hinge[i] for i in range(3)]


def compute_prismatic_open_hint(
    child: dict,
    closed_world_center: list[float],
    child_world: list[float],
    parent_effective_scale: list[float],
    child_scale: list[float],
    raw_dims: dict,
    cfg: dict,
) -> dict:
    """
    Compute origin_xyz for the OPEN (extended) pose of a prismatic part.

    The part moves along slide_axis by pullout_fraction × its own size along that axis.
    """
    slide_axis = child.get("slide_axis")
    if not slide_axis:
        print(
            f"  [WARN] '{child['name']}' has no slide_axis — defaulting to '-y'. "
            "Add slide_axis to parts.json for accurate open-pose.",
            file=sys.stderr,
        )
        slide_axis = "-y"

    cW, cD, cH = child_world
    pullout = cfg["pullout_fraction"]

    _AXIS_DIM_IDX = {"-y": 1, "+y": 1, "-x": 0, "+x": 0, "-z": 2, "+z": 2}
    _AXIS_SIGN    = {"-y": -1, "+y": 1, "-x": -1, "+x": 1, "-z": -1, "+z": 1}
    _AXIS_DIM     = [cW, cD, cH]

    ax_idx  = _AXIS_DIM_IDX.get(slide_axis, 1)
    ax_sign = _AXIS_SIGN.get(slide_axis, -1)
    travel  = pullout * _AXIS_DIM[ax_idx]

    delta = [0.0, 0.0, 0.0]
    delta[ax_idx] = ax_sign * travel

    open_world_center = [closed_world_center[i] + delta[i] for i in range(3)]
    open_origin_xyz = compute_origin_xyz(
        open_world_center, parent_effective_scale, child_scale,
        raw_dims["center"]
    )

    return {
        "slide_axis": slide_axis,
        "pullout_fraction": pullout,
        "pull_distance_m": round(travel, 5),
        "open_origin_xyz": [round(v, 5) for v in open_origin_xyz],
        "open_world_center": [round(v, 5) for v in open_world_center],
        "note": (
            f"Slides along {slide_axis} by {pullout*100:.0f}% of its own "
            f"{'depth' if ax_idx==1 else 'width' if ax_idx==0 else 'height'} "
            f"({travel:.4f} m). Adjust pull_distance_m to match the source image."
        ),
    }


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------

def build_tree(parts: list[dict]) -> dict[str, list[dict]]:
    """Return {parent_name: [child_parts]} mapping."""
    tree: dict[str, list[dict]] = {}
    for p in parts:
        key = p["parent"] or "__root__"
        tree.setdefault(key, []).append(p)
    return tree


def find_root(parts: list[dict]) -> dict:
    for p in parts:
        if p["parent"] is None:
            return p
    raise ValueError("No root part found (part with parent=null)")


# ---------------------------------------------------------------------------
# Recursive processor
# ---------------------------------------------------------------------------

def process_children(
    parent_name: str,
    tree: dict[str, list[dict]],
    dims_map: dict[str, dict],
    parent_world: list[float],
    parent_world_center: list[float],
    parent_effective_scale: list[float],
    cfg: dict,
    depth: int = 0,
) -> list[dict]:
    """
    Recursively process all children of `parent_name` and return their hint dicts.
    """
    children = tree.get(parent_name, [])
    results = []

    for child in children:
        name = child["name"]
        indent = "  " * (depth + 1)
        print(f"{indent}Processing '{name}' (joint={child.get('joint_type','?')})")

        raw = dims_map.get(name)
        if raw is None:
            print(f"{indent}[SKIP] No dims entry for '{name}'", file=sys.stderr)
            continue

        raw_size   = raw["size"]
        raw_center = raw["center"]

        # --- target world dims ---
        target_world = get_world_dims(child, parent_world, cfg["overrides"])
        print(f"{indent}  size_fraction={child.get('size_fraction')} → target_world={[round(v,4) for v in target_world]}")

        # --- child_scale ---
        child_scale = compute_child_scale(target_world, parent_effective_scale, raw_size)
        child_eff_scale = [parent_effective_scale[i] * child_scale[i] for i in range(3)]

        # --- closed world center ---
        siblings = children  # all children of the same parent
        closed_world_center = get_closed_world_center(
            child, siblings, parent_world, parent_world_center, target_world
        )
        print(f"{indent}  position_in_parent='{child.get('position_in_parent','?')}' → closed_center={[round(v,4) for v in closed_world_center]}")

        # --- closed origin_xyz ---
        closed_origin_xyz = compute_origin_xyz(
            closed_world_center, parent_effective_scale, child_scale, raw_center
        )

        # --- open pose ---
        jt = child.get("joint_type", "fixed")
        open_pose: dict[str, Any] = {}
        if jt == "revolute":
            open_pose = compute_revolute_open_hint(
                child, closed_world_center, target_world,
                parent_effective_scale, child_scale, raw, cfg,
            )
        elif jt == "prismatic":
            open_pose = compute_prismatic_open_hint(
                child, closed_world_center, target_world,
                parent_effective_scale, child_scale, raw, cfg,
            )

        # --- recurse ---
        grandchildren_hints = process_children(
            name, tree, dims_map,
            target_world, closed_world_center, child_eff_scale, cfg,
            depth + 1,
        )

        hint: dict[str, Any] = {
            "name": name,
            "joint_type": jt,
            "parent_effective_scale": [round(v, 6) for v in parent_effective_scale],
            "estimated_world_dims": [round(v, 5) for v in target_world],
            "raw_size": [round(v, 5) for v in raw_size],
            "child_scale": [round(v, 6) for v in child_scale],
            "closed_pose": {
                "world_center": [round(v, 5) for v in closed_world_center],
                "origin_xyz":   [round(v, 5) for v in closed_origin_xyz],
                "rpy_deg":      [0.0, 0.0, 0.0],
            },
        }
        if open_pose:
            hint["open_pose"] = open_pose
        if grandchildren_hints:
            hint["children"] = grandchildren_hints

        results.append(hint)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--parts",  required=True, help="Path to parts.json")
    p.add_argument("--dims",   required=True, help="Path to component_dims.json")
    p.add_argument("--output", required=True, help="Output path for placement_hints.json")

    p.add_argument(
        "--root-world-dims", nargs=3, type=float, metavar=("W", "D", "H"),
        required=True,
        help="Real-world dimensions of the ROOT part in metres (width depth height)."
    )
    p.add_argument(
        "--open-angle-deg", type=float, default=90.0,
        help="Default open angle for revolute joints shown open in the source image (default 90°)."
    )
    p.add_argument(
        "--pullout-fraction", type=float, default=0.5,
        help="Default pull-out fraction for prismatic joints shown extended (default 0.5 = 50%%)."
    )
    p.add_argument(
        "--child-world-dims", nargs=4, action="append", default=[],
        metavar=("PART_NAME", "W", "D", "H"),
        help=(
            "Override size_fraction for a specific part with exact world dims. "
            "May be given multiple times. Example: --child-world-dims left_door 0.44 0.04 1.14"
        ),
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    parts_data = json.loads(Path(args.parts).read_text())
    dims_data  = json.loads(Path(args.dims).read_text())

    parts    = parts_data["parts"]

    # component_dims.json may be {"parts": {name: {...}}} or {"components": [{name: ..., ...}]}
    if "parts" in dims_data and isinstance(dims_data["parts"], dict):
        dims_map = dims_data["parts"]
        # Ensure each entry has its own "name" key for convenience
        for k, v in dims_map.items():
            v.setdefault("name", k)
    elif "components" in dims_data:
        dims_map = {entry["name"]: entry for entry in dims_data["components"]}
    else:
        sys.exit("Error: component_dims.json must have a 'parts' dict or 'components' array at top level")

    # Build CLI override map
    overrides: dict[str, list[float]] = {}
    for entry in args.child_world_dims:
        overrides[entry[0]] = [float(entry[1]), float(entry[2]), float(entry[3])]

    cfg = {
        "open_angle_deg":    args.open_angle_deg,
        "pullout_fraction":  args.pullout_fraction,
        "overrides":         overrides,
    }

    root_part  = find_root(parts)
    root_name  = root_part["name"]
    root_world = list(args.root_world_dims)

    print(f"Root: '{root_name}', world dims: {root_world}")

    raw_root = dims_map.get(root_name)
    if raw_root is None:
        sys.exit(f"Error: no dims entry for root part '{root_name}'")

    root_scale = compute_child_scale(root_world, [1.0, 1.0, 1.0], raw_root["size"])
    root_world_center = [0.0, 0.0, root_world[2] / 2]

    tree = build_tree(parts)
    child_hints = process_children(
        root_name, tree, dims_map,
        root_world, root_world_center, root_scale, cfg,
    )

    output: dict[str, Any] = {
        "object":      parts_data.get("object", root_name),
        "root_name":   root_name,
        "root_world_dims":   [round(v, 5) for v in root_world],
        "root_world_center": [round(v, 5) for v in root_world_center],
        "root_scale":        [round(v, 6) for v in root_scale],
        "config_used": {
            "open_angle_deg":   cfg["open_angle_deg"],
            "pullout_fraction": cfg["pullout_fraction"],
            "child_overrides":  overrides,
        },
        "parts": child_hints,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
