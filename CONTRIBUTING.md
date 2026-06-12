# Contributing to Dexter

Thank you for your interest in contributing. Dexter is an agentic pipeline built around OpenCode agents, JSON schemas, and Blender tool scripts — contributions in any of those areas are welcome.

## Where to start

| Topic | Guide |
|-------|-------|
| Overview | [Contributing overview](docs/pages/contributing/overview.mdx) |
| Repo layout | [Project structure](docs/pages/contributing/project-structure.mdx) |
| Tool scripts | [Tool script standards](docs/pages/contributing/tool-script-standards.mdx) |
| Schemas | [Schemas and validation](docs/pages/contributing/schemas-and-validation.mdx) |
| Local setup | [Local development](docs/pages/contributing/local-development.mdx) |

Pipeline behavior for agents is summarized in [`AGENTS.md`](AGENTS.md). Executable config lives in [`configs/base.yaml`](configs/base.yaml) and [`opencode.json`](opencode.json).

## Development workflow

1. Fork the repository and create a branch from `main`.
2. Install dependencies: `pip install -r requirements.txt`.
3. For tool script changes, run `ruff check tool_scripts/` and `ruff format tool_scripts/`.
4. Validate JSON against schemas when touching IRs:
   ```bash
   python tool_scripts/common.py --schema schemas/<name>.schema.json --data <path>
   ```
5. Open a pull request with a clear description of the change and how you tested it.

## Reporting issues

Use [GitHub Issues](https://github.com/aakashvarma/dexter/issues) for bugs and feature requests. Include your environment (OS, Python, Blender version), the command or prompt you ran, and relevant logs or intermediate artifacts when possible.

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Please be respectful and constructive in all interactions.
