# Dexter Documentation

Documentation site for the Dexter articulated-asset pipeline, built with [Nextra](https://nextra.site).

## Structure

| Section | Contents |
|---------|----------|
| **Getting Started** | Requirements, installation & run |
| **Architecture** | Overview, agentic loop (agents, IR, tool scripts, schemas) |
| **Sample Runs** | End-to-end dishwasher walkthrough |
| **Troubleshooting** | Common issues and recovery |
| **Developer Guide** | Project structure, extending pipeline, tool script standards, local dev |

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

Media assets are in `public/assets/` (images and videos from the Dexter blog and example runs).

## Deploy on Vercel

The docs site is a Next.js app in this directory. Vercel builds it when changes under `docs/` land on `main`.

### One-time setup

1. Sign in at [vercel.com](https://vercel.com) and **Add New → Project**.
2. Import the `dexter` GitHub repository.
3. Set **Root Directory** to `docs` (click Edit next to the root path).
4. Leave **Framework Preset** as **Next.js** (auto-detected).
5. Build settings (defaults are fine):
   - **Install Command:** `npm install`
   - **Build Command:** `npm run build`
   - **Output Directory:** leave empty (Vercel handles Next.js output)
6. Set **Production Branch** to `main`.
7. Deploy.

`vercel.json` in this folder skips builds when a push does not touch this directory (the ignore command uses `.` because Vercel runs it from the Root Directory).

### After setup

Every merge or push to `main` that changes files under `docs/` triggers a production deploy. Preview deploys are created for other branches if enabled in the Vercel project settings.

### Custom domain (optional)

In the Vercel project: **Settings → Domains** → add your domain and follow the DNS instructions.
