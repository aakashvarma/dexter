"""openai_imagegen.py — Generate component images via the OpenAI Images API.

What it does
------------
Reads ``prompts.json`` and calls the OpenAI ``images/generate`` endpoint for
each entry that does not already have an output file, then writes the result
as a PNG to ``output_dir/<output_filename>``.

The API key is **not** in the config file.  Export ``OPENAI_API_KEY`` in your
shell before running.

Run::

    export OPENAI_API_KEY=your_key_here
    python openai_imagegen.py --config ../.intermediate/dishwasher/001/openai_imagegen.json

JSON config schema (every key required)::

    {
      "prompts_path":  "/path/to/prompts.json",    # output of build_component_prompts.py
      "output_dir":    "/path/to/component_images", # folder where PNGs are written
      "model":         "gpt-image-1",               # OpenAI image model
      "size":          "1024x1024",                 # "1024x1024" | "1536x1024" | "1024x1536"
      "quality":       "medium"                     # "low" | "medium" | "high"
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

    for entry in prompts:
        out_file = output_dir / entry["output_filename"]
        if out_file.exists():
            print(f"skip (exists): {out_file.name}")
            continue

        print(f"generating: {out_file.name}  …", flush=True)
        response = client.images.generate(
            model=cfg["model"],
            prompt=entry["prompt"],
            n=1,
            size=cfg["size"],
            quality=cfg["quality"],
            output_format="png",
        )

        image_data = response.data[0]

        # gpt-image-1 returns b64_json; dall-e-3 returns a URL
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
