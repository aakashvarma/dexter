# AGENTS.md

## Source Of Truth

- The real entrypoint is the `orchestrator` OpenCode agent in `.opencode/agents/orchestrator.md`; there is no `orchestrator/run_pipeline.py` driver despite the README.
- Trust `opencode.json`, `.opencode/agents/*.md`, `config.yaml`, `tool_scripts/`, and `schemas/` over README prose when they disagree.
- Deterministic scripts live in `tool_scripts/`; JSON contracts live in `schemas/`; agent prompts and permissions live in `.opencode/agents/` and `opencode.json`.
- Generated runs live under `.intermediate/<asset>/<run>/` and are gitignored; inspect them to resume work, but do not treat them as source.

## Running The Pipeline

- Setup is `pip install -r requirements.txt`; full runs also need authenticated `opencode`, `FAL_KEY` for fal.ai, and `blender` on `PATH` unless `config.yaml` changes `paths.blender_binary`.
- Run through the orchestrator agent, e.g. `opencode run --agent orchestrator -- "build the dishwasher from input_images/dishwasher.png"`; do not use the stale README `python orchestrator/run_pipeline.py` command.
- The orchestrator must probe `.intermediate/<asset>/<run>/` first and skip any valid existing artifact, so reruns continue from disk state.
- The orchestrator pauses after `parts.json` for human review and must not proceed until the user confirms or edits it.

## Pipeline Semantics

- One-time stages are analyze -> `parts.json`, `build_component_prompts.py` -> `prompts.json`, imagegen -> `component_images/`, `fal_image_to_3d.py` -> `component_glbs/`, `blender_measure_glbs.py` -> `component_dims.json`.
- Iterated stages are placement -> `place_assets.json`, `blender_place_assets.py` -> `assembled.blend`, orchestrator-written `render_views.json`, `blender_render_views.py` -> `renders/`, critic -> `critic.json`.
- Only placement/render/critique loops; component prompts, images, GLBs, and dimensions are regenerated only when their outputs are missing or explicitly redone.
- Loop knobs are in `config.yaml`: `min_loops`, `max_loops`, `score_threshold`, `max_validation_retries`, and `no_improvement_patience`.
- The orchestrator tracks the best score, bases the next placement on the best layout after regressions, and stops when the threshold/min-loop rule, max loop, or no-improvement patience is hit.
- `tool_scripts/openai_imagegen.py` is not the configured component-image path; use it only for an explicit OpenAI Images request with `OPENAI_API_KEY` set.

## Verification

- There is no checked-in test runner, linter, typecheck, CI workflow, or pre-commit config.
- Validate generated JSON with `python tool_scripts/validate_json.py --schema schemas/<name>.schema.json --data <path>`.
- The orchestrator validates `parts.json`, `place_assets.json`, `render_views.json`, and `critic.json`; `component_dims.json` has a schema but is produced by Blender measurement.
- Blender scripts must run through Blender with arguments after `--`, e.g. `blender --background --python tool_scripts/blender_place_assets.py -- --layout <place_assets.json> --output <assembled.blend>`.

## Schema And Agent Gotchas

- Subagents each write exactly one requested artifact; only the orchestrator decides ordering, retries, render views, and stop conditions.
- `place_assets.root` should be the run directory; relative asset paths usually resolve as `component_glbs/<part>.glb` under that root.
- Asset transforms are on parent pivots: child `location`/`rotation`/`scale` are relative to the parent, and scaling or moving a parent moves all children.
- `place_assets.rotation` is degrees in XYZ Euler order; `blender_place_assets.py` converts to radians.
- Placement iteration 1 intentionally uses root-at-origin, measured extents from `component_dims.json`, and `rotation`/`scale` of `[0,0,0]` and `[1,1,1]`; iteration 2+ applies only critic deltas and leaves `locked` components unchanged.
- `render_views.json` is written by the orchestrator, not the critic; cameras use `direction` vectors plus `output`, `light_energy`, `light_type`, and optional `margin`, and `blender_render_views.py` auto-frames on a white background.
- Critic `issues[]` are the placement feedback channel; keep them per-component and actionable with measured `suggested_delta`, `suggested_rotation_delta`, `suggested_scale_factor`, or `locked`.
