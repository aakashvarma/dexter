# Dexter — Articulated Asset Agent System

**Dexter** turns a single product photograph into an **articulated 3D asset** — separate part meshes, a kinematic tree, and a USD package loadable in [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac/sim).

An OpenCode **orchestrator** agent drives the pipeline. Output lands in `.intermediate/<asset>/<NNN>/`; the final deliverable is `robot.usda`.

📖 **[Documentation](docs/README.md)** — architecture, sample runs, schemas, and developer guide.

Browse locally: `cd docs && npm i && npm run dev` → http://localhost:3000

## Quick start

**Requirements:** Python 3.10+, Blender 3.6+, OpenCode, `OPENAI_API_KEY`, `FAL_KEY`. See [requirements](docs/pages/getting-started/requirements.mdx) for the full checklist.

```bash
# Install OpenCode and authenticate
curl -fsSL https://opencode.ai/install | bash
opencode          # then /connect

# Python deps and API keys
pip install -r requirements.txt
export OPENAI_API_KEY=...   # component PNGs
export FAL_KEY=...          # image-to-3D GLBs
# blender must be on PATH (or set paths.blender_binary in configs/base.yaml)

# First time in repo: opencode, then /init (writes AGENTS.md)

# Run the pipeline
opencode run --agent orchestrator -- "build the dishwasher from input_images/dishwasher.png"
```

Resume or iterate on an existing run:

```bash
opencode run --agent orchestrator -- "resume .intermediate/dishwasher/001/"
```

Interactive TUI: run `opencode`, press **Tab** to select the **orchestrator** agent.

## Learn more

| Topic | Link |
|-------|------|
| Install & run | [Getting Started](docs/pages/getting-started/installation.mdx) |
| How the pipeline works | [Architecture](docs/pages/architecture/overview.mdx) · [Agentic Loop](docs/pages/architecture/agentic-loop.mdx) |
| End-to-end example | [Dishwasher sample run](docs/pages/sample-runs/dishwasher-example.mdx) |
| Troubleshooting | [Common failures](docs/pages/sample-runs/troubleshooting.mdx) |
| Contributing | [Developer Guide](docs/pages/contributing/overview.mdx) |

Pipeline config: [`configs/base.yaml`](configs/base.yaml). Agent definitions: [`opencode.json`](opencode.json), prompts in [`.opencode/agents/`](.opencode/agents/).

## Objects Dexter has articulated

From a single product photo each, Dexter has generated full articulated 3D assets — per-part GLBs, an assembly layout, and USD export — for these household appliances:

| Dishwasher | Refrigerator |
|:---:|:---:|
| ![Dishwasher](docs/public/assets/images/dexter/examples/dishwasher.png) | ![Refrigerator](docs/public/assets/images/dexter/examples/refrigerator.png) |
| Door and dish racks as separate moving parts | French doors and freezer drawer |

| Washing machine | Oven |
|:---:|:---:|
| ![Washing machine](docs/public/assets/images/dexter/examples/washingmachine.png) | ![Oven](docs/public/assets/images/dexter/examples/oven.png) |
| Front-load door and cabinet | Drop-down oven door and cooktop |

Bundled inputs live in [`input_images/`](input_images/). See the [dishwasher sample run](docs/pages/sample-runs/dishwasher-example.mdx) for a full end-to-end walkthrough.
