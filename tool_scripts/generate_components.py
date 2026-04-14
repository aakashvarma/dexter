"""generate_components.py — Generate component PNGs, GLBs, and dimensions from parts.json.

Reads ``config.yaml``, builds prompts from ``parts.json``, generates PNGs,
converts them to GLBs, then measures GLBs with Blender.

Run::

    export OPENAI_API_KEY=your_key_here
    export FAL_KEY=your_key_here
    python3 tool_scripts/generate_components.py --run-dir ../.intermediate/dishwasher/001
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import fal_client
import requests
import yaml
from openai import OpenAI

_REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate component assets for a run")
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    return parser.parse_args()


def load_config() -> dict:
    return yaml.safe_load((_REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))


def run_paths(run_dir: str | Path, config: dict) -> dict:
    run = Path(run_dir).expanduser().resolve()
    img = config["image_generation"]
    fal = config["fal"]
    return {
        "parts_path": run / img["parts_file"],
        "images_dir": run / img["output_dir"],
        "reference_image": run / img["reference_image"],
        "glbs_dir": run / fal["output_dir"],
        "dims_path": run / fal["dims_output"],
        "background_instruction": img["background_instruction"],
        "image_model": img["model"],
        "image_size": img["size"],
        "fal_endpoint": fal["endpoint"],
        "fal_generate_type": fal["generate_type"],
        "fal_enable_pbr": fal["enable_pbr"],
        "fal_face_count": fal["face_count"],
        "fal_download_timeout": fal["download_timeout_seconds"],
        "fal_image_extensions": {ext.lower() for ext in fal["image_extensions"]},
        "blender_binary": config["paths"]["blender_binary"],
    }


def readable(name: str) -> str:
    return name.replace("_", " ").strip()


def build_prompt(
    part: dict,
    other_parts: list[dict],
    all_part_names: list[str],
    background: str,
) -> str:
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


def generate_images(paths: dict, prompts: list[dict]) -> None:
    images_dir = paths["images_dir"]
    images_dir.mkdir(parents=True, exist_ok=True)

    ref_path = paths["reference_image"]
    if not ref_path.exists():
        raise FileNotFoundError(f"reference image not found: {ref_path}")
    print(f"using source image: {ref_path}")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    for entry in prompts:
        out_file = images_dir / entry["output_filename"]
        if out_file.exists():
            print(f"skip (exists): {out_file.name}")
            continue

        print(f"generating: {out_file.name}  …", flush=True)

        with ref_path.open("rb") as ref_fh:
            response = client.images.edit(
                model=paths["image_model"],
                image=ref_fh,
                prompt=entry["prompt"],
                n=1,
                size=paths["image_size"],
            )

        image_data = response.data[0]

        if getattr(image_data, "b64_json", None):
            png_bytes = base64.b64decode(image_data.b64_json)
            out_file.write_bytes(png_bytes)
        else:
            urllib.request.urlretrieve(image_data.url, out_file)  # noqa: S310

        print(f"  saved → {out_file}")

    print("Image generation complete.")


def on_fal_queue_update(update: object) -> None:
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(f"  {log.get('message', log)}")


def generate_glbs(paths: dict) -> None:
    if "FAL_KEY" not in os.environ:
        raise OSError("Set FAL_KEY in your environment before running.")

    glbs_dir = paths["glbs_dir"]
    glbs_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in paths["images_dir"].iterdir()
        if p.is_file() and p.suffix.lower() in paths["fal_image_extensions"]
    )
    pending = [
        img for img in images
        if not (glbs_dir / f"{img.stem}.glb").exists()
    ]
    print(f"Found {len(images)} images, processing {len(pending)} for 3D")

    for i, image_path in enumerate(pending, 1):
        output_path = glbs_dir / f"{image_path.stem}.glb"
        print(f"\n[{i}/{len(pending)}] {image_path.name} → {output_path.name}")

        image_url = fal_client.upload_file(str(image_path))
        result = fal_client.subscribe(
            paths["fal_endpoint"],
            arguments={
                "input_image_url": image_url,
                "generate_type": paths["fal_generate_type"],
                "enable_pbr": paths["fal_enable_pbr"],
                "face_count": paths["fal_face_count"],
            },
            with_logs=True,
            on_queue_update=on_fal_queue_update,
        )

        glb_url = result["model_glb"]["url"]
        data = requests.get(glb_url, timeout=paths["fal_download_timeout"]).content
        output_path.write_bytes(data)
        print(f"Saved {len(data) / 1_000_000:.1f} MB")

    print("3D generation complete.")


def measure_glbs(paths: dict) -> None:
    dims_path = paths["dims_path"]
    if dims_path.exists():
        print(f"skip (exists): {dims_path}")
        return

    script = _REPO_ROOT / "tool_scripts" / "blender_measure_glbs.py"
    subprocess.run(
        [
            paths["blender_binary"],
            "--background",
            "--python",
            str(script),
            "--",
            "--glbs-dir",
            str(paths["glbs_dir"]),
            "--output",
            str(dims_path),
        ],
        check=True,
    )


def require_json(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")


def generate_components(run_dir: str | Path) -> None:
    config = load_config()
    paths = run_paths(run_dir, config)

    require_json(paths["parts_path"], "parts.json")
    parts = json.loads(paths["parts_path"].read_text(encoding="utf-8"))
    prompts = build_prompts(parts, paths["background_instruction"])

    if "OPENAI_API_KEY" not in os.environ:
        raise OSError("Set OPENAI_API_KEY in your environment before running.")

    generate_images(paths, prompts)
    generate_glbs(paths)
    measure_glbs(paths)
    print("Component generation complete.")


def main() -> None:
    try:
        generate_components(parse_args().run_dir)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
