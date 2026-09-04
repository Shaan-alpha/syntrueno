# Syntrueno — operations console

The React front end for Syntrueno: the surface where an operator reads an
incident, inspects what the agent swarm proposed, and signs the single-use
approval that lets a remediation execute.

It is a client only. Every decision, guard and signature lives in the FastAPI
backend — see the [root README](../README.md) for the architecture.

## Running it

The console expects the backend on `http://localhost:8000`. Start both together
with `./dev.sh` from the repository root, or run this half on its own:

```bash
npm install
npm run dev        # Vite dev server
```

## Scripts

| Command | What it does |
| :--- | :--- |
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | `tsc -b` then a production Vite build |
| `npm run preview` | Serve the built bundle locally |
| `npm run test` | Vitest, single run |
| `npm run test:watch` | Vitest in watch mode |
| `npm run lint` | Oxlint |
