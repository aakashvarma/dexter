"""Apply critic feedback to produce the next assembly layout.

Usage::

    python3 tool_scripts/update_placement.py \\
        --prev-assembly <path/to/prev/assembly.json> \\
        --critic        <path/to/critic.json> \\
        --output        <path/to/next/assembly.json>
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from common import (
    exit_if_missing,
    load_dims_file,
    load_json_file,
    recompute_blender_transforms,
    validate_schema,
    write_json_file,
)


def update_placement_feedback(assembly: dict, critic: dict) -> dict:
    result = copy.deepcopy(assembly)
    issues = {issue["part"]: issue for issue in critic["issues"]}

    for part in result["parts"]:
        issue = issues.get(part["name"])
        if issue is None or issue.get("locked"):
            continue
        if "corrected_world_size" in issue:
            part["world_size"] = [round(v, 5) for v in issue["corrected_world_size"]]
        if "corrected_world_center" in issue:
            part["world_center"] = [round(v, 5) for v in issue["corrected_world_center"]]
        if "suggested_rotation_delta" in issue:
            delta = issue["suggested_rotation_delta"]
            part["euler_deg"] = [round(part["euler_deg"][i] + delta[i], 4) for i in range(3)]

    run_dir = Path(result["root"]).expanduser().resolve()
    dims_path = run_dir / "component_dims.json"
    exit_if_missing(dims_path, "component_dims.json")
    validate_schema("component_dims.schema.json", dims_path)
    recompute_blender_transforms(result["parts"], load_dims_file(run_dir))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prev-assembly", required=True, type=Path)
    parser.add_argument("--critic", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    exit_if_missing(args.prev_assembly, "assembly.json")
    exit_if_missing(args.critic, "critic.json")
    validate_schema("assembly.schema.json", args.prev_assembly)
    validate_schema("critic.schema.json", args.critic)

    try:
        updated = update_placement_feedback(
            load_json_file(args.prev_assembly),
            load_json_file(args.critic),
        )
    except (KeyError, ValueError) as exc:
        sys.exit(f"Error: {exc}")

    write_json_file(args.output, updated)
    print(f"Wrote {args.output}")
    validate_schema("assembly.schema.json", args.output)


if __name__ == "__main__":
    main()
