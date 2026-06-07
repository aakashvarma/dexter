"""openai_imagegen.py — Generate component images via the OpenAI Images API.

What it does
------------
Reads ``prompts.json`` and calls the OpenAI ``images/edit`` endpoint for each
entry that does not already have an output file, then writes the result as a PNG
to ``output_dir/<output_filename>``.

``reference_image_path`` must point to ``source.png``. The source image is
always attached as a visual reference via ``images.edit()`` so the model can see
the full object while isolating each part. ``images.generate()`` does not accept
a reference image — ``images.edit()`` is the correct endpoint for this.

The API key is **not** in the config file.  Export ``OPENAI_API_KEY`` in your
shell before running.

Run::

    export OPENAI_API_KEY=your_key_here
    python openai_imagegen.py --config ../.intermediate/dishwasher/001/openai_imagegen.json

JSON config schema::

    {
      "prompts_path":         "/path/to/prompts.json",    # output of build_component_prompts.py
      "output_dir":           "/path/to/component_images", # folder where PNGs are written
      "model":                "gpt-image-2",               # OpenAI image model (gpt-image-2 or dall-e-3)
      "size":                 "1024x1024",                 # "1024x1024" | "1536x1024" | "1024x1536"
      "quality":              "medium",                    # "low" | "medium" | "high"
      "reference_image_path": "/path/to/source.png"       # required; always passed as visual reference
    }
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from openai import OpenAI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate component images via OpenAI")
    parser.add_argument("--config", required=True, help="Path to the JSON config file")
    return parser.parse_args()


def load_config(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def generate_images(cfg: dict) -> None:
    prompts_path = Path(cfg["prompts_path"])
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))["prompts"]

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    ref_image_path = cfg.get("reference_image_path")
    if not ref_image_path:
        raise OSError("reference_image_path is required and must point to source.png")
    ref_path = Path(ref_image_path).expanduser().resolve()
    if not ref_path.exists():
        raise FileNotFoundError(f"reference image not found: {ref_path}")
    print(f"using source image: {ref_path}")

    for entry in prompts:
        out_file = output_dir / entry["output_filename"]
        if out_file.exists():
            print(f"skip (exists): {out_file.name}")
            continue

        print(f"generating: {out_file.name}  …", flush=True)

        # images.edit() is the correct endpoint for passing a reference image;
        # images.generate() does not accept an image argument.
        with ref_path.open("rb") as ref_fh:
            response = client.images.edit(
                model=cfg["model"],
                image=ref_fh,
                prompt=entry["prompt"],
                n=1,
                size=cfg["size"],
            )

        image_data = response.data[0]

        if getattr(image_data, "b64_json", None):
            png_bytes = base64.b64decode(image_data.b64_json)
            out_file.write_bytes(png_bytes)
        else:
            import urllib.request
            urllib.request.urlretrieve(image_data.url, out_file)  # noqa: S310

        print(f"  saved → {out_file}")

    print("Image generation complete.")


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    generate_images(cfg)


if __name__ == "__main__":
    main()
