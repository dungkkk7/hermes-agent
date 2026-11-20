---
name: teamwork
description: "Delegate complex, long-running projects to the Antigravity Multi-Agent Teamwork Swarm (Sentinel -> Orchestrator -> Strict-AND Adversarial Gate -> Victory Auditor)."
version: 1.0.0
author: Hermes Agent Teamwork Integration
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Multi-Agent, Teamwork, Swarm, Antigravity, Orchestrator, Quality-Gate, Goal-Driven]
    related_skills: [hermes-agent, claude-code, codex]
---

# Hermes Teamwork — Multi-Agent Autonomous Swarm

Delegate complex engineering, refactoring, and multi-stage goals to the **Antigravity Multi-Agent Teamwork** operating architecture integrated into Hermes Agent.

## Core Capabilities

1. **Sentinel Invariant**: The user prompt is permanently frozen as an immutable ground truth in `ORIGINAL_REQUEST.md`.
2. **Project Orchestrator (Wave Model)**:
   - Wave 1 (Explorers): Scouts codebase topology and mining specs.
   - Wave 2 (Workers): Authors deliverables and unit tests.
   - Wave 3 (Reviewers, Challengers, Forensic Auditor): Conducts adversarial verification.
3. **Strict-AND Adversarial Gate**: Code passes a milestone ONLY with unanimous approval (Worker DONE + Auditor CLEAN + All Reviewers APPROVE + All Challengers APPROVE).
4. **Independent Victory Audit**: Before declaring completion, an isolated auditor with clean context verifies AST cleanliness, git diff hygiene, and runs 100% of regression tests to confirm `VICTORY CONFIRMED`.

## Quick Usage

### 1. Run a Mission via CLI
```bash
hermes-teamwork "Build authentication module with JWT and refresh token"
```

### 2. Specify a Custom Project Workspace
```bash
hermes-teamwork "Refactor payment service" --workspace /path/to/project
```

### 3. Combining Goal Mode (/goal) and Teamwork (/teamwork)
Teamwork operates as a standing autonomous Goal engine:
- It tracks milestones and iterations automatically.
- It never stops until quality gates pass and Victory is independently audited.
- To combine within Hermes chat: use `/goal <objective>` with quality gates, or run `hermes-teamwork "<objective>"`.
