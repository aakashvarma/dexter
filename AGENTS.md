# AGENTS.md

## Repository Shape

- Main entrypoint is the `orchestrator` OpenCode agent (`.opencode/agents/orchestrator.md`); it owns all control flow and invokes the analyze/imagegen/placement/critic subagents plus deterministic scripts. There is no Python driver.
- Prefer `opencode.json` and `.opencode/agents/*.md` over `README.md` for pipeline behavior; the README still references a non-existent `orchestrator/run_pipeline.py` and critic-planned render views.
- Deterministic scripts live in `tool_scripts/`; JSON contracts live in `schemas/`; agent prompts and permissions live in `.opencode/agents/` and `opencode.json`.
- Pipeline output is generated under `.intermediate/<asset>/<run>/` and is gitignored; do not treat it as source.
- Ignore `.opencode/node_modules/` during searches; `.opencode/.gitignore` marks the local OpenCode npm files as ignored.

## Setup And Run

- Install Python deps with `pip install -r requirements.txt`.
- Full pipeline requires `opencode` authenticated, `FAL_KEY` exported for fal.ai, and `blender` on `PATH` unless `config.yaml` changes `paths.blender_binary`.
- Run it by chatting with the orchestrator: `opencode` then switch to the `orchestrator` agent (or `opencode run --agent orchestrator -- "build the dishwasher from input_images/dishwasher.png"`).
- The orchestrator probes `.intermediate/<asset>/<run>/` to see what already exists and skips any step whose valid output is present, so re-running continues from where it left off.
- It pauses after `parts.json` for manual review, then proceeds on your confirmation.

## Pipeline Semantics

- One-time stages: analyze -> `parts.json`, `build_component_prompts.py` -> `prompts.json`, imagegen -> `component_images/`, `fal_image_to_3d.py` -> `component_glbs/`.
- Iterated stages: placement -> `place_assets.json`, Blender assembly -> `assembled.blend`, orchestrator writes the standard `render_views.json`, Blender renders -> `renders/`, critic score -> `critic.json`.
- Only placement/render/critique loop; component images and GLBs are not regenerated in later iterations unless their outputs are missing.
- Loop limits and defaults are in `config.yaml`: `min_loops`, `max_loops`, `score_threshold`, `max_validation_retries`, fal settings, and render defaults.
- `tool_scripts/openai_imagegen.py` exists but the configured pipeline uses the `imagegen` subagent for component images; use the script only if the user explicitly asks for the OpenAI Images path and has `OPENAI_API_KEY` set.

## Verification

- There is no repo test runner, linter, typecheck, CI, or pre-commit config currently checked in.
- Validate generated JSON directly: `python tool_scripts/validate_json.py --schema schemas/<name>.schema.json --data <path>`.
- The orchestrator validates `parts.json`, `place_assets.json`, `render_views.json`, and `critic.json` and retries the responsible subagent on schema failure (up to `max_validation_retries`).
- Blender scripts must be run through Blender, e.g. `blender --background --python tool_scripts/blender_place_assets.py -- --layout <place_assets.json> --output <assembled.blend>`.

## Agent And Schema Gotchas

- Subagents write exactly the one artifact the orchestrator requests; the orchestrator, not the subagents, decides ordering, retries, and stop conditions.
- `place_assets.root` must be the run directory; relative asset paths should resolve under it, usually `component_glbs/<part>.glb`.
- `place_assets.rotation` is degrees in XYZ Euler order; the Blender script converts degrees to radians.
- `render_views.json` is written by the orchestrator (not the critic) and each camera must include `name`, `location`, `look_at`, `output`, `light_energy`, and `light_type`; use front, top, left, and isometric views.
- Iteration 1 placement is location-only (`rotation` `[0,0,0]`, `scale` `[1,1,1]`); iteration 2+ applies critic corrections including `suggested_rotation_delta` and `suggested_scale_factor`.
- Critique feedback is consumed by the next placement pass, so keep `issues[]` actionable with component names and, when possible, `suggested_delta`, `suggested_rotation_delta`, or `suggested_scale_factor`.
