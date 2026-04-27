"""initialize_placement.py — Pre-compute scales and poses, then emit assembly.json.

Reads parts.json and component_dims.json (paths from config.yaml) and writes:
  - placement_init.json  — per-part scales, closed/open poses
  - iterations/001/assembly.json  — ready-to-render assembly from the hints

Per-part open_angle_deg, pullout_fraction, and optional world_dims come from
parts.json. Skips writing if both output files already exist.

Usage::

    python3 tool_scripts/initialize_placement.py --run-dir <run_dir>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Maps a slide_axis string to (world-axis index, movement sign).
_SLIDE_AXIS_IDX  = {"-y": 1, "+y": 1, "-x": 0, "+x": 0, "-z": 2, "+z": 2}
_SLIDE_AXIS_SIGN = {"-y": -1, "+y": 1, "-x": -1, "+x": 1, "-z": -1, "+z": 1}


# --- math ---


def rotation_matrix_z(deg: float) -> list[list[float]]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def rotation_matrix_x(deg: float) -> list[list[float]]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rotation_matrix_y(deg: float) -> list[list[float]]:
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
        for angle, rot_fn in [(rz, rotation_matrix_z), (ry, rotation_matrix_y), (rx, rotation_matrix_x)]:
            if abs(angle) > 0.01:
                v = mat_vec(rot_fn(angle), v)
        scaled_center = v

    return [
        target_world_center[i] / parent_effective_scale[i] - scaled_center[i]
        for i in range(3)
    ]


# --- geometry helpers ---


def _parse_pos_keywords(pos: str) -> tuple[str, str]:
    """
    Split a position_in_parent string into (horizontal_kw, vertical_kw).
    Accepted horizontal: left, center-left, center, center-right, right.
    Accepted vertical:   bottom, lower, middle, upper, top.
    """
    p = pos.lower()
    horiz = "center"
    vert  = "middle"

    for kw in ("center-left", "center-right", "left", "right"):
        if kw in p:
            horiz = kw
            break

    for kw in ("bottom", "lower", "top", "upper"):
        if kw in p:
            vert = kw
            break

    return horiz, vert


def get_world_dims(child: dict, parent_world: list[float]) -> list[float]:
    """
    Return target world [W, D, H] for this part.

    Priority:
      1. world_dims field in parts.json (explicit override)
      2. size_fraction field in parts.json
      3. Fallback: [0.5, 0.5, 0.5] of parent with a warning.
    """
    if child.get("world_dims") is not None:
        return list(child["world_dims"])

    sf = child.get("size_fraction")
    if sf is None:
        print(
            f"  [WARN] '{child['name']}' has no size_fraction — falling back to [0.5, 0.5, 0.5] of parent. "
            "Re-run analyze to add size_fraction.",
            file=sys.stderr,
        )
        sf = [0.5, 0.5, 0.5]

    return [parent_world[i] * sf[i] for i in range(3)]


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
      - joint_type / hinge_side / slide_axis for Y (depth) placement
    """
    pW, pD, pH = parent_world
    cW, cD, cH = child_world

    px_min = parent_world_center[0] - pW / 2
    px_max = parent_world_center[0] + pW / 2
    py_min = parent_world_center[1] - pD / 2   # front face (−Y in Blender)
    pz_min = parent_world_center[2] - pH / 2   # floor
    pz_max = parent_world_center[2] + pH / 2   # ceiling

    jt  = child.get("joint_type", "fixed")
    pos = child.get("position_in_parent", "center")
    horiz, vert = _parse_pos_keywords(pos)

    # X
    if horiz == "left":
        cx = px_min + cW / 2
    elif horiz == "right":
        cx = px_max - cW / 2
    elif horiz == "center-left":
        cx = parent_world_center[0] - cW / 2
    elif horiz == "center-right":
        cx = parent_world_center[0] + cW / 2
    else:
        # Multiple same-type siblings at "center" → split evenly across parent width
        same_type = sorted([s for s in siblings if s.get("joint_type") == jt], key=lambda s: s["name"])
        if len(same_type) > 1:
            idx = next((i for i, s in enumerate(same_type) if s["name"] == child["name"]), 0)
            slot_w = pW / len(same_type)
            cx = px_min + idx * slot_w + slot_w / 2
        else:
            cx = parent_world_center[0]

    # Y (depth): flush with front face for forward-opening joints, else centred
    hs = child.get("hinge_side")
    sa = child.get("slide_axis", "-y")
    front_facing = (
        (jt == "revolute" and hs in ("left", "right", "bottom")) or
        (jt == "prismatic" and sa == "-y")
    )
    cy = (py_min + cD / 2) if front_facing else parent_world_center[1]

    # Z
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


# --- open-pose computation ---


def _rotate_point_around_hinge(
    point: list[float],
    hinge: list[float],
    R: list[list[float]],
) -> list[float]:
    """Rotate `point` around `hinge` using rotation matrix R."""
    v = [point[i] - hinge[i] for i in range(3)]
    v_rot = mat_vec(R, v)
    return [v_rot[i] + hinge[i] for i in range(3)]


def compute_revolute_open_hint(
    child: dict,
    closed_world_center: list[float],
    child_world: list[float],
    parent_effective_scale: list[float],
    child_scale: list[float],
    raw_dims: dict,
) -> dict:
    """
    Compute origin_xyz and rpy_deg for the OPEN pose of a revolute part.

    Rotation conventions (right-hand rule, Blender Z-up −Y-forward):
      hinge_side='left'   → rpy_z = −open_angle  (CCW around Z looks leftward)
      hinge_side='right'  → rpy_z = +open_angle
      hinge_side='bottom' → rpy_x = −open_angle  (top swings forward)
      hinge_side='top'    → rpy_x = +open_angle  (bottom swings forward/backward)
    """
    open_angle = child.get("open_angle_deg")
    if open_angle is None:
        print(
            f"  [WARN] '{child['name']}' has no open_angle_deg — defaulting to 0 (closed). "
            "Add open_angle_deg to parts.json for revolute joints shown open in the source image.",
            file=sys.stderr,
        )
        return {}
    open_angle = float(open_angle)
    if abs(open_angle) < 0.01:
        return {}

    hinge_side = child.get("hinge_side")
    if not hinge_side:
        print(
            f"  [WARN] '{child['name']}' has no hinge_side — defaulting to 'left'. "
            "Add hinge_side to parts.json for accurate open-pose.",
            file=sys.stderr,
        )
        hinge_side = "left"

    cW, cD, cH = child_world
    cx, cy, cz = closed_world_center

    if hinge_side == "left":
        rpy_deg = [0.0, 0.0, -open_angle]
        hinge_local = [cx - cW / 2, cy, cz]
        open_world_center = _rotate_point_around_hinge([cx, cy, cz], hinge_local, rotation_matrix_z(-open_angle))

    elif hinge_side == "right":
        rpy_deg = [0.0, 0.0, open_angle]
        hinge_local = [cx + cW / 2, cy, cz]
        open_world_center = _rotate_point_around_hinge([cx, cy, cz], hinge_local, rotation_matrix_z(open_angle))

    elif hinge_side == "bottom":
        rpy_deg = [-open_angle, 0.0, 0.0]
        hinge_local = [cx, cy, cz - cH / 2]
        open_world_center = _rotate_point_around_hinge([cx, cy, cz], hinge_local, rotation_matrix_x(-open_angle))

    elif hinge_side == "top":
        rpy_deg = [open_angle, 0.0, 0.0]
        hinge_local = [cx, cy, cz + cH / 2]
        open_world_center = _rotate_point_around_hinge([cx, cy, cz], hinge_local, rotation_matrix_x(open_angle))

    else:
        print(f"  [WARN] Unknown hinge_side '{hinge_side}' for '{child['name']}' — no open pose computed.", file=sys.stderr)
        return {}

    open_origin_xyz = compute_origin_xyz(
        open_world_center, parent_effective_scale, child_scale, raw_dims["center"], rpy_deg
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


def compute_prismatic_open_hint(
    child: dict,
    closed_world_center: list[float],
    child_world: list[float],
    parent_effective_scale: list[float],
    child_scale: list[float],
    raw_dims: dict,
) -> dict:
    """
    Compute origin_xyz for the OPEN (extended) pose of a prismatic part.

    The part moves along slide_axis by pullout_fraction × its own size along that axis.
    """
    pullout = child.get("pullout_fraction")
    if pullout is None:
        print(
            f"  [WARN] '{child['name']}' has no pullout_fraction — defaulting to 0 (closed). "
            "Add pullout_fraction to parts.json for prismatic joints shown extended in the source image.",
            file=sys.stderr,
        )
        return {}
    pullout = float(pullout)
    if pullout < 1e-6:
        return {}

    slide_axis = child.get("slide_axis")
    if not slide_axis:
        print(
            f"  [WARN] '{child['name']}' has no slide_axis — defaulting to '-y'. "
            "Add slide_axis to parts.json for accurate open-pose.",
            file=sys.stderr,
        )
        slide_axis = "-y"

    cW, cD, cH = child_world
    ax_idx  = _SLIDE_AXIS_IDX.get(slide_axis, 1)
    ax_sign = _SLIDE_AXIS_SIGN.get(slide_axis, -1)
    travel  = pullout * [cW, cD, cH][ax_idx]

    delta = [0.0, 0.0, 0.0]
    delta[ax_idx] = ax_sign * travel

    open_world_center = [closed_world_center[i] + delta[i] for i in range(3)]
    open_origin_xyz = compute_origin_xyz(
        open_world_center, parent_effective_scale, child_scale, raw_dims["center"]
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
            f"({travel:.4f} m). Adjust pullout_fraction in parts.json to match the source image."
        ),
    }


# --- assembly generation ---


def _flatten_hints_to_links(
    hints: list[dict],
    parent_name: str,
    glbs_dir: str,
    links: list[dict],
) -> None:
    """Recursively flatten nested placement hints into the flat links array for assembly.json."""
    for hint in hints:
        name = hint["name"]
        # Use the open pose if one was computed (open_angle_deg / pullout_fraction > 0),
        # otherwise use the closed pose.
        if "open_pose" in hint:
            world_center = hint["open_pose"]["open_world_center"]
            rpy_deg      = hint["open_pose"].get("open_rpy_deg", [0.0, 0.0, 0.0])
        else:
            world_center = hint["closed_pose"]["world_center"]
            rpy_deg      = hint["closed_pose"]["rpy_deg"]

        links.append({
            "name":         name,
            "parent":       parent_name,
            "visual_mesh":  f"{glbs_dir}/{name}.glb",
            "collision_mesh": f"{glbs_dir}/{name}.glb",
            "world_size":   hint["estimated_world_dims"],
            "world_center": world_center,
            "rpy_deg":      rpy_deg,
        })
        _flatten_hints_to_links(hint.get("children", []), name, glbs_dir, links)


def build_assembly(
    object_name: str,
    run_dir: Path,
    run_dir_str: str,
    glbs_dir: str,
    root_name: str,
    root_world_dims: list[float],
    root_world_center: list[float],
    child_hints: list[dict],
) -> dict:
    """Build the assembly.json dict from placement hints."""
    links: list[dict] = [{
        "name":         root_name,
        "parent":       None,
        "visual_mesh":  f"{glbs_dir}/{root_name}.glb",
        "collision_mesh": f"{glbs_dir}/{root_name}.glb",
        "world_size":   [round(v, 5) for v in root_world_dims],
        "world_center": [round(v, 5) for v in root_world_center],
        "rpy_deg":      [0.0, 0.0, 0.0],
    }]
    _flatten_hints_to_links(child_hints, root_name, glbs_dir, links)

    return {
        "root":       run_dir_str,
        "robot_name": object_name,
        "links":      links,
    }


# --- tree processing ---


def load_dims_map(dims_data: dict) -> dict[str, dict]:
    if "parts" in dims_data and isinstance(dims_data["parts"], dict):
        dims_map = dims_data["parts"]
        for k, v in dims_map.items():
            v.setdefault("name", k)
        return dims_map
    if "components" in dims_data:
        return {entry["name"]: entry for entry in dims_data["components"]}
    raise ValueError("component_dims.json must have a 'parts' dict or 'components' array at top level")


def process_children(
    parent_name: str,
    tree: dict[str, list[dict]],
    dims_map: dict[str, dict],
    parent_world: list[float],
    parent_world_center: list[float],
    parent_effective_scale: list[float],
    depth: int = 0,
) -> list[dict]:
    """Recursively process all children of `parent_name` and return their hint dicts."""
    children = tree.get(parent_name, [])
    results = []

    for child in children:
        name   = child["name"]
        indent = "  " * (depth + 1)
        print(f"{indent}Processing '{name}' (joint={child.get('joint_type', '?')})")

        raw = dims_map.get(name)
        if raw is None:
            print(f"{indent}[SKIP] No dims entry for '{name}'", file=sys.stderr)
            continue

        target_world = get_world_dims(child, parent_world)
        print(f"{indent}  size_fraction={child.get('size_fraction')} → target_world={[round(v, 4) for v in target_world]}")

        child_scale     = compute_child_scale(target_world, parent_effective_scale, raw["size"])
        child_eff_scale = [parent_effective_scale[i] * child_scale[i] for i in range(3)]

        closed_world_center = get_closed_world_center(
            child, children, parent_world, parent_world_center, target_world
        )
        print(f"{indent}  position_in_parent='{child.get('position_in_parent', '?')}' → closed_center={[round(v, 4) for v in closed_world_center]}")

        closed_origin_xyz = compute_origin_xyz(
            closed_world_center, parent_effective_scale, child_scale, raw["center"]
        )

        jt = child.get("joint_type", "fixed")
        open_pose: dict[str, Any] = {}
        if jt == "revolute":
            open_pose = compute_revolute_open_hint(child, closed_world_center, target_world, parent_effective_scale, child_scale, raw)
        elif jt == "prismatic":
            open_pose = compute_prismatic_open_hint(child, closed_world_center, target_world, parent_effective_scale, child_scale, raw)

        grandchildren = process_children(name, tree, dims_map, target_world, closed_world_center, child_eff_scale, depth + 1)

        hint: dict[str, Any] = {
            "name":                   name,
            "joint_type":             jt,
            "parent_effective_scale": [round(v, 6) for v in parent_effective_scale],
            "estimated_world_dims":   [round(v, 5) for v in target_world],
            "raw_size":               [round(v, 5) for v in raw["size"]],
            "child_scale":            [round(v, 6) for v in child_scale],
            "closed_pose": {
                "world_center": [round(v, 5) for v in closed_world_center],
                "origin_xyz":   [round(v, 5) for v in closed_origin_xyz],
                "rpy_deg":      [0.0, 0.0, 0.0],
            },
        }
        if open_pose:
            hint["open_pose"] = open_pose
        if grandchildren:
            hint["children"] = grandchildren

        results.append(hint)

    return results


# --- entry point ---


def require_json(path: Path, label: str) -> None:
    if not path.is_file():
        sys.exit(f"Error: {label} not found: {path}")


def initialize_placement(run_dir: str | Path) -> None:
    config = yaml.safe_load((_REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    pi     = config["placement_init"]
    run    = Path(run_dir).expanduser().resolve()

    parts_path    = run / pi["parts_file"]
    dims_path     = run / pi["dims_file"]
    init_path     = run / pi["output"]
    assembly_path = run / "iterations" / "001" / "assembly.json"
    glbs_dir      = config["fal"]["output_dir"]   # component_glbs

    require_json(parts_path, "parts.json")
    require_json(dims_path,  "component_dims.json")

    if init_path.exists() and assembly_path.exists():
        print(f"skip (exists): {init_path}")
        print(f"skip (exists): {assembly_path}")
        return

    parts_data = json.loads(parts_path.read_text(encoding="utf-8"))
    dims_data  = json.loads(dims_path.read_text(encoding="utf-8"))
    parts      = parts_data["parts"]
    dims_map   = load_dims_map(dims_data)

    root_part = next((p for p in parts if p["parent"] is None), None)
    if root_part is None:
        sys.exit("No root part found (part with parent=null)")

    root_name  = root_part["name"]
    root_world = root_part.get("world_dims")
    if root_world is None:
        sys.exit(
            f"Error: root part '{root_name}' has no world_dims in parts.json. "
            "The analyze agent must estimate [width_m, depth_m, height_m] for the root part."
        )
    root_world = list(root_world)

    print(f"Root: '{root_name}', world dims: {root_world}")

    raw_root = dims_map.get(root_name)
    if raw_root is None:
        sys.exit(f"Error: no dims entry for root part '{root_name}'")

    root_scale        = compute_child_scale(root_world, [1.0, 1.0, 1.0], raw_root["size"])
    root_world_center = [0.0, 0.0, root_world[2] / 2]

    # Build parent → children tree
    tree: dict[str, list[dict]] = {}
    for p in parts:
        tree.setdefault(p["parent"] or "__root__", []).append(p)

    child_hints = process_children(root_name, tree, dims_map, root_world, root_world_center, root_scale)
    object_name = parts_data.get("object", root_name)

    # Write placement_init.json
    init_output: dict[str, Any] = {
        "object":            object_name,
        "root_name":         root_name,
        "root_world_dims":   [round(v, 5) for v in root_world],
        "root_world_center": [round(v, 5) for v in root_world_center],
        "root_scale":        [round(v, 6) for v in root_scale],
        "config_used": {
            "source":          "parts.json",
            "root_world_dims": [round(v, 5) for v in root_world],
        },
        "parts": child_hints,
    }
    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_text(json.dumps(init_output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {init_path}")

    # Write iterations/001/assembly.json
    assembly = build_assembly(
        object_name, run, str(run), glbs_dir,
        root_name, root_world, root_world_center,
        child_hints,
    )
    assembly_path.parent.mkdir(parents=True, exist_ok=True)
    assembly_path.write_text(json.dumps(assembly, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {assembly_path}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", required=True, help="Pipeline run directory")
    initialize_placement(p.parse_args().run_dir)


if __name__ == "__main__":
    main()
