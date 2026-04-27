"""
apply_critic.py — deterministically apply critic.json corrections to assembly.json.

Usage:
    python3 tool_scripts/apply_critic.py \\
        --prev-assembly <path/to/prev/assembly.json> \\
        --critic        <path/to/critic.json> \\
        --output        <path/to/next/assembly.json>

Rules:
  - corrected_world_size   → replaces link.world_size directly
  - corrected_world_center → replaces link.world_center directly
  - suggested_rotation_delta → added to link.rpy_deg
  - locked: true           → component is untouched
  - un-flagged components  → left unchanged
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def apply_corrections(assembly: dict, critic: dict) -> dict:
    result = copy.deepcopy(assembly)

    issues_by_name: dict[str, dict] = {}
    for issue in critic.get("issues", []):
        name = issue.get("component")
        if name:
            issues_by_name[name] = issue

    for link in result["links"]:
        name = link["name"]
        issue = issues_by_name.get(name)
        if issue is None:
            continue  # un-flagged — leave unchanged

        if issue.get("locked"):
            continue  # explicitly locked — must not change

        corrected_size = issue.get("corrected_world_size")
        if corrected_size is not None:
            link["world_size"] = [round(v, 5) for v in corrected_size]

        corrected_center = issue.get("corrected_world_center")
        if corrected_center is not None:
            link["world_center"] = [round(v, 5) for v in corrected_center]

        rot_delta = issue.get("suggested_rotation_delta")
        if rot_delta is not None:
            link["rpy_deg"] = [
                round(link["rpy_deg"][i] + rot_delta[i], 4) for i in range(3)
            ]

    return result


def validate(output_path: Path, schema_path: Path) -> bool:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "validate_json.py"),
            "--schema", str(schema_path),
            "--data", str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prev-assembly", required=True, type=Path, help="Path to previous assembly.json")
    parser.add_argument("--critic",        required=True, type=Path, help="Path to critic.json")
    parser.add_argument("--output",        required=True, type=Path, help="Output path for next assembly.json")
    args = parser.parse_args()

    for path, label in [(args.prev_assembly, "assembly.json"), (args.critic, "critic.json")]:
        if not path.is_file():
            sys.exit(f"Error: {label} not found: {path}")

    assembly = load_json(args.prev_assembly)
    critic   = load_json(args.critic)

    updated = apply_corrections(assembly, critic)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")

    schema_path = Path(__file__).parent.parent / "schemas" / "assembly.schema.json"
    if schema_path.exists():
        ok = validate(args.output, schema_path)
        if not ok:
            sys.exit(1)
    else:
        print(f"Warning: schema not found at {schema_path}, skipping validation.")


if __name__ == "__main__":
    main()
