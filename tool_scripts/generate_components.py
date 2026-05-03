"""Generate component PNGs, GLBs, and dimensions from parts.json.

Run::

    export OPENAI_API_KEY=your_key_here
    export FAL_KEY=your_key_here
    python3 tool_scripts/generate_components.py --run-dir ../.intermediate/dishwasher/001
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import fal_client
import requests
from openai import OpenAI

from common import exit_if_missing, load_json_file, load_yaml_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate component assets for a run")
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    return parser.parse_args()


def build_run_paths(run_dir: str | Path, config: dict) -> dict:
    run_path = Path(run_dir).expanduser().resolve()
    image_config = config["image_generation"]
    fal_config = config["fal"]
    return {
        "parts_path": run_path / image_config["parts_file"],
        "images_dir": run_path / image_config["output_dir"],
        "reference_image": run_path / image_config["reference_image"],
        "glbs_dir": run_path / fal_config["output_dir"],
        "dims_path": run_path / fal_config["dims_output"],
        "background_instruction": image_config["background_instruction"],
        "image_model": image_config["model"],
        "image_size": image_config["size"],
        "fal_endpoint": fal_config["endpoint"],
        "fal_generate_type": fal_config["generate_type"],
        "fal_enable_pbr": fal_config["enable_pbr"],
        "fal_face_count": fal_config["face_count"],
        "fal_download_timeout": fal_config["download_timeout_seconds"],
        "fal_image_extensions": {ext.lower() for ext in fal_config["image_extensions"]},
        "blender_binary": config["paths"]["blender_binary"],
    }


def format_snake_case_name(name: str) -> str:
    return name.replace("_", " ").strip()


def build_prompt(
    part: dict,
    other_parts: list[dict],
    all_part_names: list[str],
    background: str,
) -> str:
    display_name = format_snake_case_name(part["name"])
    description = part["description"].strip()
    parts_list = ", ".join(all_part_names)
    exclusion_lines = (
        "\n".join(
            f"- {format_snake_case_name(other['name'])} - {other['description'].strip()}"
            for other in other_parts
        )
        or "- nothing"
    )
    return (
        f"Use the attached source image as the visual reference. "
        f"It shows the full object and is being divided into "
        f"{len(all_part_names)} parts: {parts_list}.\n"
        f"Generate {display_name}: {description}\n"
        "Show the complete component from an isometric-style angle "
        "that reveals as much of its shape as possible.\n"
        f"Without the following (leave their positions in the frame empty):\n"
        f"{exclusion_lines}\n"
        f"{background}"
    )


def build_prompts(parts: dict, background: str) -> list[dict]:
    part_entries = parts["parts"]
    all_part_names = [format_snake_case_name(part["name"]) for part in part_entries]
    prompts: list[dict] = []
    for part in part_entries:
        name = part["name"]
        other_parts = [other for other in part_entries if other["name"] != name]
        prompts.append(
            {
                "component": name,
                "prompt": build_prompt(part, other_parts, all_part_names, background),
                "output_filename": f"{name}.png",
            }
        )
    return prompts


def generate_images(paths: dict, prompts: list[dict]) -> None:
    images_dir = paths["images_dir"]
    images_dir.mkdir(parents=True, exist_ok=True)

    reference_image = paths["reference_image"]
    if not reference_image.exists():
        raise FileNotFoundError(f"reference image not found: {reference_image}")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    for entry in prompts:
        output_file = images_dir / entry["output_filename"]
        if output_file.exists():
            print(f"skip (exists): {output_file.name}")
            continue

        with reference_image.open("rb") as reference_handle:
            response = client.images.edit(
                model=paths["image_model"],
                image=reference_handle,
                prompt=entry["prompt"],
                n=1,
                size=paths["image_size"],
            )

        image_data = response.data[0]

        if getattr(image_data, "b64_json", None):
            output_file.write_bytes(base64.b64decode(image_data.b64_json))
        else:
            urllib.request.urlretrieve(image_data.url, output_file)  # noqa: S310


def generate_glbs(paths: dict) -> None:
    if "FAL_KEY" not in os.environ:
        raise OSError("Set FAL_KEY in your environment before running.")

    glbs_dir = paths["glbs_dir"]
    glbs_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        path
        for path in paths["images_dir"].iterdir()
        if path.is_file() and path.suffix.lower() in paths["fal_image_extensions"]
    )
    pending = [
        image_path for image_path in images if not (glbs_dir / f"{image_path.stem}.glb").exists()
    ]

    for image_path in pending:
        output_path = glbs_dir / f"{image_path.stem}.glb"
        image_url = fal_client.upload_file(str(image_path))
        result = fal_client.subscribe(
            paths["fal_endpoint"],
            arguments={
                "input_image_url": image_url,
                "generate_type": paths["fal_generate_type"],
                "enable_pbr": paths["fal_enable_pbr"],
                "face_count": paths["fal_face_count"],
            },
        )

        glb_url = result["model_glb"]["url"]
        glb_bytes = requests.get(glb_url, timeout=paths["fal_download_timeout"]).content
        output_path.write_bytes(glb_bytes)


def measure_glbs(paths: dict) -> None:
    dims_path = paths["dims_path"]
    if dims_path.exists():
        print(f"skip (exists): {dims_path}")
        return

    script_path = Path(__file__).resolve().parent / "blender_measure_glbs.py"
    subprocess.run(
        [
            paths["blender_binary"],
            "--background",
            "--python",
            str(script_path),
            "--",
            "--glbs-dir",
            str(paths["glbs_dir"]),
            "--output",
            str(dims_path),
        ],
        check=True,
    )


def generate_components(run_dir: str | Path) -> None:
    config = load_yaml_config()
    paths = build_run_paths(run_dir, config)

    exit_if_missing(paths["parts_path"], "parts.json")
    parts = load_json_file(paths["parts_path"])
    prompts = build_prompts(parts, paths["background_instruction"])

    if "OPENAI_API_KEY" not in os.environ:
        raise OSError("Set OPENAI_API_KEY in your environment before running.")

    generate_images(paths, prompts)
    generate_glbs(paths)
    measure_glbs(paths)


def main() -> None:
    try:
        generate_components(parse_args().run_dir)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
