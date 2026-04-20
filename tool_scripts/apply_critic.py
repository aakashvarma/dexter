"""
apply_critic.py — deterministically apply critic.json corrections to assembly.json.

Usage:
    python3 tool_scripts/apply_critic.py \
        --prev-assembly <path/to/prev/assembly.json> \
        --critic        <path/to/critic.json> \
        --output        <path/to/next/assembly.json>

Rules:
  - suggested_delta         → added to origin.xyz
  - suggested_scale_factor  → multiplies each scale axis (scalar OR 3-element array)
  - suggested_rotation_delta → added to origin.rpy_deg
  - locked: true            → component is untouched
  - un-flagged components   → left unchanged
"""

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def apply_corrections(assembly: dict, critic: dict) -> dict:
    result = copy.deepcopy(assembly)

    # Build lookup: component name -> issue entry
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

        origin = link["origin"]

        delta = issue.get("suggested_delta")
        if delta is not None:
            origin["xyz"] = [origin["xyz"][i] + delta[i] for i in range(3)]

        rot_delta = issue.get("suggested_rotation_delta")
        if rot_delta is not None:
            origin["rpy_deg"] = [
                origin["rpy_deg"][i] + rot_delta[i] for i in range(3)
            ]

        scale_factor = issue.get("suggested_scale_factor")
        if scale_factor is not None:
            if isinstance(scale_factor, (int, float)):
                link["scale"] = [s * scale_factor for s in link["scale"]]
            else:
                # per-axis array
                link["scale"] = [
                    link["scale"][i] * scale_factor[i] for i in range(3)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prev-assembly", required=True, type=Path)
    parser.add_argument("--critic", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    assembly = load_json(args.prev_assembly)
    critic = load_json(args.critic)

    updated = apply_corrections(assembly, critic)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(updated, f, indent=2)
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
