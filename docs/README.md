# Dexter Documentation

Documentation site for the Dexter articulated-asset pipeline, built with [Nextra](https://nextra.site).

## Structure

| Section | Contents |
|---------|----------|
| **Getting Started** | Requirements, installation, configuration, running |
| **Architecture** | Overview, agentic loop, agents, IR, schemas, tools |
| **Sample Runs & Troubleshooting** | Dishwasher walkthrough, common issues |
| **Developer Guide** | Project structure, extending pipeline, schemas, local dev |

## Development

```bash
cd docs
npm install
npm run dev    # http://localhost:3000
```

## Build

```bash
npm run build
npm start
```

Media assets are in `public/assets/` (images and videos from the Dexter blog).
