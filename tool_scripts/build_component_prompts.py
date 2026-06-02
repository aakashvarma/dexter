"""build_component_prompts.py — Build per-component image prompts from parts.

What it does
------------
Reads a JSON config pointing at a ``parts.json`` file and, for every part,
writes one image-generation prompt of the form::

    Generate <part> Without the following: <other parts>

A white-background instruction is appended to each prompt. The result is
written to ``output_path`` for ``openai_generate_components.py`` to consume.

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


def build_prompt(part_name: str, other_names: list[str], background: str) -> str:
    """Build the image-generation prompt for one part.

    Args:
        part_name: Name of the part to generate.
        other_names: Names of every other part to exclude.
        background: Background instruction appended to the prompt.

    Returns:
        The full prompt string.
    """
    others = ", ".join(readable(n) for n in other_names) or "nothing"
    return f"Generate {readable(part_name)} Without the following: {others}. {background}"


def build_prompts(parts: dict, background: str) -> list[dict]:
    """Build one prompt entry per part in the parts list.

    Args:
        parts: Parsed parts JSON.
        background: Background instruction appended to every prompt.

    Returns:
        List of ``{component, prompt, output_filename}`` dictionaries.
    """
    names = [part["name"] for part in parts["parts"]]
    prompts = []
    for name in names:
        others = [other for other in names if other != name]
        prompts.append(
            {
                "component": name,
                "prompt": build_prompt(name, others, background),
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
