# OSIA — Architecture & Build Order

*Local-first ambient AI OS layer. MCA final-year project (300 marks).*

This document orders every feature by one question: **what real problem does this solve, if hardware weren't a constraint?** — then groups that ranking into three tiers by what your actual hardware can support right now. Build top-to-bottom within each tier.

---

## Why this ordering

Ranked by real-world value, independent of feasibility, the problems OSIA solves are:

1. **Cloud AI cost dependency** — the original motivator. Every task handled locally is a task that isn't a subscription line item.
2. **Data leaving the device** — privacy isn't a feature, it's the premise. A local AI that quietly leaks PII to the cloud isn't local-first, it's local-first-shaped.
3. **Context loss across models/sessions** — most AI tools forget you the moment you close the tab or swap models. Persistent, model-agnostic memory is a genuinely rare property.
4. **Manual tedium** — file ops, task creation, calendar management via natural language instead of manual clicking.
5. **Trusting an AI with OS-level access** — nobody uses an agent that can `rm -rf` their home folder by mistake. Security isn't a late feature, it's a precondition for 1-4 being usable at all.
6. **Reliability of small local models** — routing/triage exists to make 1-5 actually work on consumer hardware, not as a goal in itself.
7. **Handling messy real-world input** — PDFs, screenshots, spreadsheets — because real requests aren't clean text.

Tiers below are ordered by what's buildable on your current 12GB AMD card vs. what needs more investment (time, hardware, or scope) — but *within* each tier, features are still ordered by that same 1-7 value ranking.

---

## Tier 1 — Budget-Viable Build
*Runs entirely on your current hardware (RX 6700 XT, 12GB VRAM). This is "does the core idea work at all."*

### 1. Three-tier model architecture (solves #1, #6)
The foundation everything else sits on. Without this, there's no product — just three models running in isolation.
- Set up On Duty model (Gemma 3 12B, quantized) — replies to user, executes tasks locally; same weights become Off Duty when idle for janitor work
- Set up Manager model (Qwen 3.5 4B, thinking off) — triage/routing only, never executes
- Design triage classification schema (JSON/tool-calling output)
- Wire up Heavy Duty fallback (BYOK, provider-agnostic)
- Implement chat mode vs agent mode toggle — explicit switch, not auto-detected (MVP)
- Build chat/agent mode toggle (duplicate of above from a later session — merge into one task)

### 2. File management & basic execution (solves #4)
The first thing that makes this feel like an "OS layer" instead of a chatbot.
- Build file management / intent-to-command execution (plain English → bash/PowerShell via subprocess, Linux first)
- Build local music playback feature (mpv/VLC IPC, deterministic metadata matching — no AI-guessed paths)
- Deterministic local execution via VLC/CLI (no hallucination risk)

### 3. Memory that actually persists (solves #3)
The differentiator vs. every other local-AI toy project.
- Build relational ledger (SQLite + JSON/JSONB hybrid schema) — chronological history, temporal anchors, schema-less payload column for rapid attribute evolution
- Build domain-specific vector shards (ChromaDB)
- Build shared bucket for cross-domain facts
- Implement working memory via KV/prefix caching
- Build conversational session checkpointer for chat mode (merge duplicate task)
- Implement confidence threshold + clarification fallback

### 4. Non-negotiable safety layer (solves #5)
This has to exist *before* you demo autonomous execution to anyone, including yourself.
- OS-level permission enforcement (not app-layer trust) — the core principle: "no" means the OS never granted it
- Build safety gating for autonomous command execution — confirmation/dry-run before self-corrected commands re-execute

### 5. Getting it running (infrastructure)
- Install Linux Mint Cinnamon on a separate disk
- Design evaluation methodology for triage router — you need to *measure* whether Tier 1 actually works, not just eyeball it

---

## Tier 2 — Most-Viable Build
*Needs more build time and polish, not necessarily more hardware. This is "a complete, demoable, defensible system."*

### 6. Real security hardening (solves #5, properly this time)
Tier 1's safety layer is a promise; this is the enforcement.
- Dedicated restricted user account for the AI process
- AppArmor (or Firejail/Bubblewrap) profile for kernel-enforced path restrictions
- inotify/fanotify-based first-access interception
- Build 3-option permission prompt UI (allow once / allow always / deny + redirect)
- Define AI space / common space / user space permission tiers
- Define cloud-escalation payload redaction rules — the actual point where local-first has a hole unless handled deliberately

### 7. Handling real-world messy input (solves #7)
- Build attachment preprocessing pipeline (PDF/image/structured data — text-layer detection routes to text extraction or vision, tables to pdfplumber, spreadsheets never touch vision)
- Build PDF/document generation tool

### 8. Making Manager actually reliable (solves #6, properly)
Tonight's testing showed Manager's structure is right but execution wobbles (raw SQL vs. function calls, hallucinated paths). This is the fix.
- Build LoRA or few-shot example set for Manager

### 9. Escalation that doesn't waste Heavy Duty's time
- Escalation: retry-triggered handoff to Heavy Duty (separate from Manager's upfront triage — On Duty bails after N failed attempts, packages its own failed reasoning so Heavy Duty isn't starting cold)
- Cloud escalation pipeline for Todoist task generation
- Implement intermediate-step narration during multi-step tasks (also doubles as demo material and a safety mitigation)

### 10. Memory maturity
- Add persona/mode tag column to memory schema
- Implement bi-temporal versioning (created_at / invalidated_at)
- Design high-priority personalization bucket + decay logic
- Build idle task queue for background janitor duties
- Async janitor pruning/curation for long-term semantic memory
- Janitor: summarize + archive session thread on chat-mode end (merge duplicate task; keep raw log cold, don't delete — consistent with bi-temporal versioning)
- "Grep over vector DBs" flat-file storage for notes (Obsidian-style)
- Define explicit data layer (deterministic CLI/API-manipulated)
- Define cheap pre-check vs full memory trip logic

### 11. Everyday-life integrations (solves #4, extended)
- Google Calendar API integration
- Build habit-based notification broker

### 12. Packaging & shipping
- Package as a .deb for Linux Mint/Ubuntu
- Publish git repo
- Post on Reddit for outside security review
- Run VirusTotal scan on the .deb package
- Record demo videos and screenshots (viva backup)

### 13. Academic writeup (parallel track, not blocking)
- Design evaluation methodology for safety gating
- Write related-work section citing RouteLLM, FrugalGPT, HybridFlow, CE-CoLLM
- Write related-work section citing Letta, Mem0, Zep/Graphiti, MemX
- Write up rejected design alternatives
- Confirm supervisor + team formation, define ownership split

---

## Tier 3 — Extras
*Genuinely optional. Would be built if hardware, time, or team size weren't limiting factors at all.*

- Design manual device-sync mechanism (phone ↔ computer) — no auto-sync, explicit conflict handling
- Scope phone thin-client architecture — computer as inference server, phone as terminal
- Set up CPU transcriber (faster-whisper) — voice input
- Set up CPU embedder (dedicated, if not already covered by main pipeline)
- CalDAV / local calendar option — fully local-first alternative to Google Calendar, documented but not required
- Install Antigravity for Linux

### Deliberately excluded from any tier — needs separate design, not a checkbox
Flagged during tonight's discussion: routing emotional-distress detection through the same Manager classification system as ordinary task categories (coding, poetry review, etc.) is a bad idea. A wrong classification here is a different order of bad than a wrong pick between "coding" and "literature review." If this is in scope at all, it needs its own reliability bar and its own design pass — not a tenth entry in a config picker.
