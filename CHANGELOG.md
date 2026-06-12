# Changelog

All notable changes to Dexter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.0] - 2025-06-12

Initial public release. Dexter turns a single product photograph into an articulated 3D asset — separate part meshes, a kinematic tree, and a USD package loadable in NVIDIA Isaac Sim.

### Added

- OpenCode **orchestrator** agent with `analyze` and `critic` subagents (`opencode.json`, `.opencode/agents/`).
- Deterministic tool scripts for component generation, placement init/update, Blender assembly, multi-view rendering, and USD export (`tool_scripts/`).
- JSON schemas for pipeline IRs: `parts`, `assembly`, `critic`, `component_dims`, `render_views` (`schemas/`).
- Centralized pipeline configuration in `configs/base.yaml` (paths, loop limits, placement init).
- Bundled reference inputs for dishwasher, refrigerator, washing machine, and oven (`input_images/`).
- Nextra documentation site with architecture guides, sample runs, and contributor docs (`docs/`).
- Sample run artifacts on [Hugging Face](https://huggingface.co/datasets/varmology/dexter-sample-outputs) for inspection without running the pipeline.
- Human gates after parts review and before USD export.
- Placement iteration loop with critic scoring and regression handling via `update_placement.py`.

### Notes

- **v0.0.0** marks the first tagged release. The pipeline is functional end-to-end but APIs, schemas, and agent prompts may change before **v1.0.0**.
- Requires Python 3.10+, Blender 3.6+, OpenCode, `OPENAI_API_KEY`, and `FAL_KEY`. See [requirements](docs/pages/getting-started/requirements.mdx).

[0.0.0]: https://github.com/aakashvarma/dexter/releases/tag/v0.0.0
