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
    REPO_ROOT,
    exit_if_invalid_json,
    exit_if_missing,
    load_json_file,
    write_json_file,
)


def update_placement_feedback(assembly: dict, critic: dict) -> dict:
    result = copy.deepcopy(assembly)

    issues_by_name: dict[str, dict] = {}
    for issue in critic.get("issues", []):
        part_name = issue.get("part")
        if part_name:
            issues_by_name[part_name] = issue

    for part in result["parts"]:
        name = part["name"]
        issue = issues_by_name.get(name)
        if issue is None or issue.get("locked"):
            continue

        corrected_size = issue.get("corrected_world_size")
        if corrected_size is not None:
            part["world_size"] = [round(value, 5) for value in corrected_size]

        corrected_center = issue.get("corrected_world_center")
        if corrected_center is not None:
            part["world_center"] = [round(value, 5) for value in corrected_center]

        rotation_delta = issue.get("suggested_rotation_delta")
        if rotation_delta is not None:
            part["euler_deg"] = [
                round(part["euler_deg"][axis] + rotation_delta[axis], 4) for axis in range(3)
            ]

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prev-assembly", required=True, type=Path)
    parser.add_argument("--critic", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    exit_if_missing(args.prev_assembly, "assembly.json")
    exit_if_missing(args.critic, "critic.json")

    updated = update_placement_feedback(
        load_json_file(args.prev_assembly),
        load_json_file(args.critic),
    )
    write_json_file(args.output, updated)
    print(f"Wrote {args.output}")

    schema_path = REPO_ROOT / "schemas" / "assembly.schema.json"
    if schema_path.exists():
        exit_if_invalid_json(schema_path, args.output)
    else:
        print(
            f"Warning: schema not found at {schema_path}, skipping validation.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
