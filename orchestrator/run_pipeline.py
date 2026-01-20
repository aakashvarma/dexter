"""run_pipeline.py — Orchestrate the articulated-asset pipeline.

Once (skipped if outputs already exist):
  analyze subagent   -> parts.json  -> [human gate]
  build_component_prompts.py        -> prompts.json
  openai_imagegen.py -> component_images/
  fal_image_to_3d.py -> component_glbs/

Loop (iterations/NNN/):
  placement subagent -> place_assets.json  (validated, retried on schema error)
  blender_place_assets.py -> assembled.blend
  critic subagent    -> render_views.json  (validated)
  blender_render_views.py -> renders/
  critic subagent    -> critic.json        (validated)
  exit when score >= score_threshold and N >= min_loops, or N >= max_loops

FAL_KEY must be exported before running.

Run::

    export FAL_KEY=...
    python orchestrator/run_pipeline.py --config config.yaml --image input_images/dishwasher.png
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--run", help="Reuse an existing run id (e.g. 001)")
    parser.add_argument("--skip-human-gate", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_run_dir(config: dict, image: Path, run: str | None) -> Path:
    asset_root = REPO_ROOT / config["paths"]["intermediate_root"] / image.stem
    asset_root.mkdir(parents=True, exist_ok=True)
    if run is not None:
        run_dir = asset_root / run
    else:
        existing = [int(p.name) for p in asset_root.iterdir() if p.is_dir() and p.name.isdigit()]
        run_dir = asset_root / f"{(max(existing) + 1) if existing else 1:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_command(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    if subprocess.run(cmd, cwd=REPO_ROOT).returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def run_script(script: str, config_path: Path) -> None:
    run_command([sys.executable, str(REPO_ROOT / "tool_scripts" / script), "--config", str(config_path)])


def run_blender(blender: str, script: str, args: list[str]) -> None:
    run_command([blender, "--background", "--python", str(REPO_ROOT / "tool_scripts" / script), "--", *args])


def run_agent(agent: str, message: str, files: list[Path]) -> None:
    cmd = ["opencode", "run", "--agent", agent, "--format", "json"]
    for f in files:
        cmd += ["-f", str(f)]
    # -- stops yargs option parsing so the message is not consumed by -f [array]
    cmd += ["--", message]
    run_command(cmd)


def validate(config: dict, schema: str, data_path: Path) -> tuple[bool, str]:
    schema_path = REPO_ROOT / config["paths"]["schemas_dir"] / schema
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tool_scripts" / "validate_json.py"),
         "--schema", str(schema_path), "--data", str(data_path)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def step_analyze(config: dict, run_dir: Path, source: Path) -> Path:
    parts_path = run_dir / "parts.json"
    if parts_path.exists():
        print(f"parts.json exists, skipping: {parts_path}")
        return parts_path

    retries = config["loop"]["max_validation_retries"]
    message = (
        f"Analyse the attached source image and write the minimal URDF parts list to: {parts_path}\n"
        "Conform to schemas/parts.schema.json."
    )
    for attempt in range(retries + 1):
        run_agent("analyze", message, [source])
        ok, report = validate(config, "parts.schema.json", parts_path)
        if ok:
            break
        print(report)
        if attempt == retries:
            raise RuntimeError(f"analyze output failed validation after {retries} retries")
        message = f"{message}\n\nPrevious output failed validation:\n{report}\nFix and rewrite."
    return parts_path


def human_gate(parts_path: Path, skip: bool) -> None:
    if skip:
        return
    print(f"\nReview and edit the parts list if needed:\n  {parts_path}")
    input("Press Enter to continue... ")


def step_prompts(config: dict, run_dir: Path, parts_path: Path) -> Path:
    prompts_path = run_dir / "prompts.json"
    if prompts_path.exists():
        print(f"prompts.json exists, skipping: {prompts_path}")
        return prompts_path

    prompts_config = run_dir / "build_component_prompts.json"
    write_json(prompts_config, {
        "parts_path": str(parts_path),
        "output_path": str(prompts_path),
        "background_instruction": config["image_generation"]["background_instruction"],
    })
    run_script("build_component_prompts.py", prompts_config)
    return prompts_path


def step_images(config: dict, run_dir: Path, prompts_path: Path) -> Path:
    images_dir = run_dir / "component_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))["prompts"]

    if all((images_dir / p["output_filename"]).exists() for p in prompts):
        print(f"component images exist, skipping: {images_dir}")
        return images_dir

    imggen_cfg = config["image_generation"]
    imagegen_config = run_dir / "openai_imagegen.json"
    write_json(imagegen_config, {
        "prompts_path": str(prompts_path),
        "output_dir": str(images_dir),
        "model": imggen_cfg["model"],
        "size": imggen_cfg["size"],
        "quality": imggen_cfg["quality"],
    })
    run_script("openai_imagegen.py", imagegen_config)

    missing = [p["output_filename"] for p in prompts if not (images_dir / p["output_filename"]).exists()]
    if missing:
        raise RuntimeError(f"openai_imagegen did not produce: {', '.join(missing)}")
    return images_dir


def step_3d(config: dict, run_dir: Path, images_dir: Path) -> Path:
    glbs_dir = run_dir / "component_glbs"
    fal = config["fal"]
    fal_config = run_dir / "fal_image_to_3d.json"
    write_json(fal_config, {
        "images_dir": str(images_dir),
        "output_dir": str(glbs_dir),
        "image_extensions": fal["image_extensions"],
        "skip_stems": [],
        "model": {
            "endpoint": fal["endpoint"],
            "generate_type": fal["generate_type"],
            "enable_pbr": fal["enable_pbr"],
            "face_count": fal["face_count"],
            "download_timeout_seconds": fal["download_timeout_seconds"],
        },
    })
    run_script("fal_image_to_3d.py", fal_config)
    return glbs_dir


def run_iteration(n: int, config: dict, run_dir: Path, source: Path, parts_path: Path, prev_iter_dir: Path | None) -> dict:
    iter_dir = run_dir / "iterations" / f"{n:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    retries = config["loop"]["max_validation_retries"]
    blender = config["paths"]["blender_binary"]
    print(f"\n=== Iteration {n} ===")

    # placement
    place_path = iter_dir / "place_assets.json"
    lines = [
        f"Iteration {n}. Write the asset layout JSON to: {place_path}",
        f"Use this exact value for 'root': {run_dir}",
        f"Component GLBs are in: {run_dir / 'component_glbs'} (paths relative to root, e.g. component_glbs/<name>.glb).",
        f"Articulation tree: {parts_path}",
        "Source image attached. Conform to schemas/place_assets.schema.json.",
    ]
    if prev_iter_dir is not None:
        lines += [
            f"Previous layout: {prev_iter_dir / 'place_assets.json'}",
            f"Previous critique: {prev_iter_dir / 'critic.json'}",
            "Apply only the corrections from the critique's issues to the previous layout.",
        ]
    placement_msg = "\n".join(lines)

    for attempt in range(retries + 1):
        run_agent("placement", placement_msg, [source])
        ok, report = validate(config, "place_assets.schema.json", place_path)
        if ok:
            break
        print(report)
        if attempt == retries:
            raise RuntimeError(f"placement output failed validation after {retries} retries")
        placement_msg = f"{placement_msg}\n\nPrevious output failed validation:\n{report}\nFix and rewrite."

    # assemble blend
    blend_path = iter_dir / "assembled.blend"
    run_blender(blender, "blender_place_assets.py", ["--layout", str(place_path), "--output", str(blend_path)])

    # critic: plan render views
    render_views_path = iter_dir / "render_views.json"
    render = config["render"]
    render_plan_msg = "\n".join([
        f"Iteration {n}, phase 1 (plan render views). Write render settings JSON to: {render_views_path}",
        f"Defaults: resolution {render['resolution']}, samples {render['samples']}, engine {render['engine']}, file_format {render['file_format']}.",
        f"Assembled blend: {blend_path}. Renders go to {iter_dir / 'renders'}.",
        "Include at least front, top, left, and isometric views. Conform to schemas/render_views.schema.json.",
    ])

    for attempt in range(retries + 1):
        run_agent("critic", render_plan_msg, [source])
        ok, report = validate(config, "render_views.schema.json", render_views_path)
        if ok:
            break
        print(report)
        if attempt == retries:
            raise RuntimeError(f"critic render_views output failed validation after {retries} retries")
        render_plan_msg = f"{render_plan_msg}\n\nPrevious output failed validation:\n{report}\nFix and rewrite."

    # render
    renders_dir = iter_dir / "renders"
    run_blender(blender, "blender_render_views.py", [
        "--blend", str(blend_path), "--cameras", str(render_views_path), "--output-dir", str(renders_dir),
    ])

    # critic: score and feedback
    critic_path = iter_dir / "critic.json"
    renders = sorted(renders_dir.glob("*.png"))
    critique_msg = "\n".join([
        f"Iteration {n}, phase 2 (critique). Source image and rendered views attached.",
        f"Write critique JSON to: {critic_path} with iteration={n}.",
        "Score 0-100, set 'pass', give actionable per-component issues. Conform to schemas/critic.schema.json.",
    ])

    for attempt in range(retries + 1):
        run_agent("critic", critique_msg, [source, *renders])
        ok, report = validate(config, "critic.schema.json", critic_path)
        if ok:
            break
        print(report)
        if attempt == retries:
            raise RuntimeError(f"critic output failed validation after {retries} retries")
        critique_msg = f"{critique_msg}\n\nPrevious output failed validation:\n{report}\nFix and rewrite."

    return json.loads(critic_path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    image = Path(args.image).expanduser().resolve()
    run_dir = resolve_run_dir(config, image, args.run)
    print(f"Run directory: {run_dir}")

    source = run_dir / "source.png"
    if not source.exists():
        source.write_bytes(image.read_bytes())

    parts_path = step_analyze(config, run_dir, source)
    human_gate(parts_path, args.skip_human_gate)
    prompts_path = step_prompts(config, run_dir, parts_path)
    images_dir = step_images(config, run_dir, prompts_path)
    step_3d(config, run_dir, images_dir)

    loop = config["loop"]
    history: list[dict] = []
    prev_iter_dir: Path | None = None
    stopped_reason = "max_loops"

    for n in range(1, loop["max_loops"] + 1):
        critique = run_iteration(n, config, run_dir, source, parts_path, prev_iter_dir)
        history.append({"iteration": n, "score": critique["score"], "pass": critique["pass"]})
        print(f"Iteration {n} score: {critique['score']}")

        if critique["score"] >= loop["score_threshold"] and n >= loop["min_loops"]:
            stopped_reason = "score_threshold"
            break
        prev_iter_dir = run_dir / "iterations" / f"{n:03d}"

    best = max(history, key=lambda h: h["score"])
    write_json(run_dir / "run.json", {
        "asset": image.stem,
        "run": run_dir.name,
        "score_threshold": loop["score_threshold"],
        "stopped_reason": stopped_reason,
        "best_iteration": best["iteration"],
        "best_score": best["score"],
        "history": history,
    })
    print(f"\nDone. Best iteration {best['iteration']} (score {best['score']}). Stopped: {stopped_reason}")


if __name__ == "__main__":
    main()
