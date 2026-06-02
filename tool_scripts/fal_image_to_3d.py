"""fal_image_to_3d.py — Convert images to GLB files via fal.ai.

What it does
------------
Reads a JSON config, finds images in ``images_dir``, skips stems listed in
``skip_stems`` and any image that already has a matching ``.glb`` in
``output_dir``, then for each remaining image:

1. Upload the image to fal.ai
2. Call the Hunyuan image-to-3D endpoint with settings from ``model``
3. Download the returned GLB to ``output_dir/<image_stem>.glb``

The API key is **not** in JSON. Export ``FAL_KEY`` in your shell before running.

Run::

    export FAL_KEY=your_key_here
    python fal_image_to_3d.py --config ../.intermediate/dishwasher/001/fal_image_to_3d.json

JSON schema (every key required)::

    {
      "images_dir": "/path/to/images",  # folder of input images
      "output_dir": "/path/to/glbs",    # folder where GLBs are written
      "image_extensions": [".png"],     # file extensions to pick up
      "skip_stems": [],                 # image stems to skip (use [] for none)
      "model": {
        "endpoint": "fal-ai/...",       # fal model id
        "generate_type": "Normal",      # passed to the fal API
        "enable_pbr": true,             # PBR materials on/off
        "face_count": 1500000,          # target mesh face count
        "download_timeout_seconds": 300 # HTTP timeout when downloading the GLB
      }
    }
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import fal_client
import requests


def parse_args() -> argparse.Namespace:
    """Parse the ``--config`` command-line argument.

    Returns:
        Parsed arguments with ``config`` set to the pipeline JSON path.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def require_fal_key() -> None:
    """Ensure ``FAL_KEY`` is set in the environment.

    Raises:
        OSError: If ``FAL_KEY`` is missing.
    """
    if "FAL_KEY" not in os.environ:
        raise OSError("Set FAL_KEY in your environment before running.")


def load_config(path: str) -> dict:
    """Load the pipeline JSON config from disk.

    Args:
        path: Path to the config file.

    Returns:
        Parsed JSON as a dictionary.
    """
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def list_images(config: dict) -> list[Path]:
    """List image files in ``images_dir`` matching ``image_extensions``.

    Args:
        config: Pipeline JSON config.

    Returns:
        Sorted list of image paths.
    """
    images_dir = Path(config["images_dir"]).expanduser().resolve()
    extensions = {ext.lower() for ext in config["image_extensions"]}
    return sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    )


def images_to_process(config: dict, images: list[Path]) -> list[Path]:
    """Filter images that still need a GLB generated.

    Args:
        config: Pipeline JSON config.
        images: Candidate images from :func:`list_images`.

    Returns:
        Images not in ``skip_stems`` and without an existing output GLB.
    """
    output_dir = Path(config["output_dir"]).expanduser().resolve()
    skip = set(config["skip_stems"])
    return [
        img for img in images
        if img.stem not in skip and not (output_dir / f"{img.stem}.glb").exists()
    ]


def on_queue_update(update: object) -> None:
    """Print fal.ai progress logs during model generation.

    Args:
        update: Status update from ``fal_client.subscribe``.
    """
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(f"  {log.get('message', log)}")


def generate_glb(image_path: Path, output_path: Path, config: dict) -> None:
    """Upload one image, run image-to-3D, and save the GLB.

    Args:
        image_path: Source image file.
        output_path: Destination ``.glb`` path.
        config: Pipeline JSON config.
    """
    model = config["model"]
    print(f"\nProcessing: {image_path.name} → {output_path}")

    image_url = fal_client.upload_file(str(image_path))
    result = fal_client.subscribe(
        model["endpoint"],
        arguments={
            "input_image_url": image_url,
            "generate_type": model["generate_type"],
            "enable_pbr": model["enable_pbr"],
            "face_count": model["face_count"],
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    glb_url = result["model_glb"]["url"]
    data = requests.get(glb_url, timeout=model["download_timeout_seconds"]).content
    output_path.write_bytes(data)
    print(f"Saved {len(data) / 1_000_000:.1f} MB")


def main() -> None:
    """Run image-to-3D for every pending image in the config."""
    args = parse_args()
    require_fal_key()
    config = load_config(args.config)
    output_dir = Path(config["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    images = list_images(config)
    pending = images_to_process(config, images)
    print(f"Found {len(images)} images, processing {len(pending)}")

    for i, image_path in enumerate(pending, 1):
        print(f"\n[{i}/{len(pending)}]")
        generate_glb(image_path, output_dir / f"{image_path.stem}.glb", config)

    print("\nDone.")


if __name__ == "__main__":
    main()
