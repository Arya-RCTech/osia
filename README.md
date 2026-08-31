# OSIA

> **O.S.I.A.** — *On-device Sovereign Intent Agent*

OSIA started as an attempt to answer a simple, annoying question: why does every AI assistant forget you the moment you switch models, close the tab, or run out of free credits? It's a local-first AI system built to run on your own hardware, remember you across sessions and models, and act on your machine — without handing your data or your wallet to a cloud provider by default.

This project is **under active development**. Some of what's below is working and tested; some is architecture that's built but not yet hardened; none of it is a finished product.

## Why OSIA exists

Building this meant actually living inside the constraints most AI tools quietly assume away: consumer GPUs that overheat, local inference stacks that leak memory, and models that hallucinate tool calls in formats nobody documented. The `documentation/` folder has the real bug history behind this project. If you're evaluating this project, that folder is worth more than this README.

## What it actually does

- **Runs locally, by default.** Inference happens on-device via local models, with no internet connection or external server required for core functionality. Cloud models (Gemini, Groq) are optional, bring-your-own-key fallbacks for when local hardware isn't enough — not a hidden dependency.
- **Remembers across models and sessions.** Memory is stored in SQLite (structured/relational) and ChromaDB (semantic/vector), so context isn't tied to a single model or a single chat window. This persistence — and getting it to survive model swaps cleanly — is the core engineering problem this project is actually about.
- **Two-tier model orchestration.** An "On Duty" local model handles day-to-day chat and task execution; a "Heavy Duty" cloud fallback steps in for harder tasks. Routing between them is a live area of the project, not a solved one.
- **Built with a safety-first stance on OS-level access.** Any design that lets an AI touch your filesystem or run commands needs an explicit confirmation gate for anything destructive. This is a design principle the project is being built around — check `documentation/` for current implementation status rather than assuming it's fully wired up.

## Architecture

- **Frontend:** Flutter (desktop), real-time streaming UI.
- **Backend:** Modular Python, headless FastAPI server, Server-Sent Events (SSE) streaming.
- **Memory:** SQLite (relational) + ChromaDB (semantic vector store).

For the full file-by-file breakdown and call flow, see `documentation/`.

## Status & limitations

This is a solo project, actively changing shape. Expect rough edges, incomplete features, and architecture decisions that are still being second-guessed and revised. Version numbers follow a personal scheme (major = big overhaul, minor = features/fixes, micro decimal = save-points) rather than strict semver — check commit messages for the real detail on any given change.

Check `documentation/` for current build status, known bugs, and what's actually finished versus in-progress.

## License

All rights reserved for now — no license granted. This will be revisited once the project is further along.

---
*OSIA — version 0.1.0*