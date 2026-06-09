"""build_component_prompts.py — Build per-component image prompts from parts.

What it does
------------
Reads a JSON config pointing at a ``parts.json`` file and, for every part,
writes one image-generation prompt of the form::

    Use the attached source image as the visual reference. It shows the full object
    and is being divided into N parts: part1, part2, ...
    Generate <name>: <description>
    Show the complete component from an isometric-style angle that reveals as much
    of its shape as possible.
    Without the following (leave their positions in the frame empty):
    - <other1> - <description1>
    - <other2> - <description2>
    <background_instruction>

The source image is attached separately to the generation call as a visual
reference — descriptions are intentionally brief since the model can see the
image directly.

Run::

    python build_component_prompts.py --config ../.intermediate/dishwasher/001/build_component_prompts.json

JSON schema (every key required)::

    {
      "parts_path": "/path/to/parts.json",     # parts list to read
      "output_path": "/path/to/prompts.json",  # where prompts are written
      "background_instruction":                 # appended to every prompt
        "Isolate only this part on a plain white background."
    }

Output JSON::

    {
      "prompts": [
        {"component": "door", "prompt": "...", "output_filename": "door.png"}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse the ``--config`` command-line argument.

    Returns:
        Parsed arguments with ``config`` set to the prompt-builder JSON path.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def load_json(path: str) -> dict:
    """Load a JSON file from disk.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON as a dictionary.
    """
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def readable(name: str) -> str:
    """Turn a snake_case part name into readable prompt text.

    Args:
        name: Part name such as ``control_panel``.

    Returns:
        Human-readable form such as ``control panel``.
    """
    return name.replace("_", " ").strip()


def build_prompt(
    part: dict,
    other_parts: list[dict],
    all_part_names: list[str],
    background: str,
) -> str:
    """Build the image-generation prompt for one part.

    Args:
        part: Part entry from ``parts.json`` with ``name`` and ``description``.
        other_parts: Every other part entry to exclude.
        all_part_names: Readable names of every part (for the context line).
        background: Background instruction appended to the prompt.

    Returns:
        The full prompt string.
    """
    name = readable(part["name"])
    description = part["description"].strip()
    parts_list = ", ".join(all_part_names)
    exclusion_lines = "\n".join(
        f"- {readable(other['name'])} - {other['description'].strip()}"
        for other in other_parts
    ) or "- nothing"
    return (
        f"Use the attached source image as the visual reference. "
        f"It shows the full object and is being divided into {len(all_part_names)} parts: {parts_list}.\n"
        f"Generate {name}: {description}\n"
        f"Show the complete component from an isometric-style angle that reveals as much of its shape as possible.\n"
        f"Without the following (leave their positions in the frame empty):\n"
        f"{exclusion_lines}\n"
        f"{background}"
    )


def build_prompts(parts: dict, background: str) -> list[dict]:
    """Build one prompt entry per part in the parts list.

    Args:
        parts: Parsed parts JSON.
        background: Background instruction appended to every prompt.

    Returns:
        List of ``{component, prompt, output_filename}`` dictionaries.
    """
    part_entries = parts["parts"]
    all_part_names = [readable(p["name"]) for p in part_entries]
    prompts = []
    for part in part_entries:
        name = part["name"]
        others = [other for other in part_entries if other["name"] != name]
        prompts.append(
            {
                "component": name,
                "prompt": build_prompt(part, others, all_part_names, background),
                "output_filename": f"{name}.png",
            }
        )
    return prompts


def main() -> None:
    """Build component prompts and write them to the output path."""
    args = parse_args()
    config = load_json(args.config)

    parts = load_json(config["parts_path"])
    output_path = Path(config["output_path"]).expanduser().resolve()

    prompts = build_prompts(parts, config["background_instruction"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"prompts": prompts}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(prompts)} prompts to {output_path}")


if __name__ == "__main__":
    main()
