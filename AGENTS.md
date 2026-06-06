# AGENTS.md

## Source Of Truth

- The runnable entrypoint is the OpenCode `orchestrator` agent (`opencode.json` -> `.opencode/agents/orchestrator.md`); there is no standalone Python pipeline driver.
- Trust executable/config sources over prose: `opencode.json`, `.opencode/agents/*.md`, `config.yaml`, `tool_scripts/`, and `schemas/`.
- Generated runs are under `.intermediate/<asset>/<NNN>/` and are gitignored; always inspect disk state there before resuming or deciding to redo work.

## Running The Pipeline

- Setup: `pip install -r requirements.txt`; full runs also need authenticated `opencode`, `FAL_KEY` for fal.ai, and `blender` on `PATH` (or change `paths.blender_binary` in `config.yaml`).
- Start through OpenCode, e.g. `opencode run --agent orchestrator -- "build the dishwasher from input_images/dishwasher.png"`.
- Orchestrator behavior is resume-first: skip valid existing artifacts unless the user explicitly asks to redo them.
- Human gate is mandatory: pause after `parts.json` and wait for confirmation before continuing.

## Pipeline Order

- One-time placement inputs: `analyze` -> `parts.json` -> human parts gate -> `build_component_prompts.py` -> `prompts.json` -> `imagegen` -> `component_images/` -> `fal_image_to_3d.py` -> `component_glbs/` -> Blender export/simplify -> `component_meshes/` and `component_meshes_simp/` -> Blender measure -> `component_dims.json`.
- Placement loop per `iterations/<NNN>/`: `placement` -> `assembly.json` -> `blender_assemble.py` -> `assembled.blend` -> orchestrator-written `render_views.json` -> `blender_render_views.py` -> `renders/` -> `critic` -> `critic.json`.
- Pipeline ends when the placement/critic loop converges; the final deliverable is `iterations/<B>/assembled.blend` for the best iteration `B`.
- Loop controls (`min_loops`, `max_loops`, `score_threshold`, `max_validation_retries`, `no_improvement_patience`), fal settings, and render defaults are in `config.yaml`.

## Verification And Commands

- There is no checked-in test runner, linter, typecheck, CI workflow, or pre-commit config.
- Validate generated JSON with `python tool_scripts/validate_json.py --schema schemas/<name>.schema.json --data <path>` for `parts`, `assembly`, and `critic`.
- Blender scripts require Blender plus arguments after `--`, e.g. `blender --background --python tool_scripts/blender_assemble.py -- --layout <assembly.json> --output <assembled.blend>`.

## Schema And Agent Gotchas

- Subagents write exactly one requested artifact; only the orchestrator owns ordering, retries, render views, and stop conditions.
- `assembly.json` is the shared IR: `visual_mesh` should resolve to `component_glbs/<part>.glb`; `collision_mesh` to `component_meshes_simp/<part>.obj`; `root` should be the run directory.
- Link transforms are parent-relative pivots; `origin.rpy_deg` is XYZ Euler degrees. `scale` affects Blender assembly only.
- Placement iteration 1 sets root at origin, rotations `[0,0,0]`, collision-free spacing from `component_dims.json`, and plausible scales; iteration 2+ applies critic deltas. Critic `locked` only when position, size, and collisions are all acceptable.
- Render views are four auto-framed cameras (`front`, `top`, `left`, `isometric`) using `direction`, `output`, `light_energy`, and `light_type`; do not add `location`/`look_at`.
- Critic feedback should be per-component and actionable via `suggested_delta`, `suggested_rotation_delta`, `suggested_scale_factor`, or `locked`; the next placement may be based on the best prior layout after a regression.
- `tool_scripts/openai_imagegen.py` is not the configured component-image path; use it only for an explicit OpenAI Images request with `OPENAI_API_KEY` set.
