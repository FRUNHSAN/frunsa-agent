# Frunsa-Agent

> From a university competition entry to an AI Security Agent architecture experiment platform — 18 phases of complete evolution.

[中文](README.md) | English

[![Tests](https://img.shields.io/badge/tests-673%20passed-brightgreen)](godot-qwen-agent/tests/)
[![Guardrails](https://img.shields.io/badge/guardrails-16%20passed-blue)](godot-qwen-agent/guardrails/)
[![Python](https://img.shields.io/badge/python-3.12+-informational)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/phase-18%20complete-orange)](godot-qwen-agent/PLAN.md)

---

## Project Origin

This repo started as an entry for the **2026 SUSTech Agent Competition** — a RAG-based AI assistant for Godot game development. The tech stack was simple: FastAPI + Qwen API + FAISS vector retrieval. Users asked questions through Godot 4.x's HTTPRequest, and the backend retrieved relevant docs from a knowledge base before passing them to Qwen for answers.

I originally intended to compete, but working solo made the project messy. With limited time and energy, I never ended up registering or submitting.

After the competition, the code didn't stop at "good enough to run." Looking back at the unfinished project, I found it impossible to work with — the code was heavily coupled and chaotic. I also noticed that agent platforms were exploding in number that year, driven by rapid model iteration that unlocked new capabilities. Models were becoming well-rounded hexagons, capable of handling increasingly complex task chains. One question emerged: **if this Agent is not just a Q&A bot, but a system capable of autonomous planning, orchestration, and self-evaluation — where is its security boundary?**

From that point, this project pivoted to the research and engineering of AI Agent security architecture.

---

## Design Philosophy

### Core Principle: Security is a First-Class Architectural Citizen, Not an Afterthought

Most AI Agent projects treat security as something to "add later" — plug in some API key management, set up permission checks, done. Frunsa-Agent takes the opposite approach: **security properties were written into the architectural constitution from Phase 1. Every line of code operates within three security boundaries.**

### Three-Layer Verifiable Security

| Layer | Mechanism | Stage | Implementation |
|-------|-----------|-------|----------------|
| **Compile-time** | AST Compliance Scanning | Dev / CI | 16 AST rules auto-detect architecture violations; pre-commit hook enforcement |
| **Runtime** | Safety Isolation | Engine execution | try/except → error terminal (no crash); credential isolation; cross-engine import forbidden |
| **Post-hoc** | Full Audit Trail | Traceability | SQLiteTraceSink single-file database; every LLM call auditable |

### Architectural Evolution: Progressive Refactoring Across 18 Phases

This wasn't a one-shot rewrite. It evolved through 18 phases, each with clear engineering goals, reasoning chain records, and test regression:

| Stage | Phases | Key Deliverables | Tests |
|-------|--------|------------------|-------|
| **Foundation** | 1-5 | Three-platform architecture (Contract → Adapter → Pipeline), I/O adapter pattern, health probes | 107 |
| **Observability Loop** | 6-13 | SQLiteTraceSink, Trace Key system (18 keys), Guardrail scanner | 468 |
| **Engine Layer** | 14-16 | Three engine Stub implementations, orchestration DAG, chaos injection, Sufficiency Report v1-v2 | 560 |
| **Real LLM** | 17-18 | LLM production engines, Factory DI assembly contract, Sufficiency Report v3-v4 | 673 |

Every decision is recorded in `.ai_reasoning/chains/` (21 reasoning chains), with alternatives comparison and anti-pattern warnings for each key trade-off.

### Architectural Constitution: Six Properties + Four Axes

After 18 phases, a guiding framework for long-term maintenance emerged:

**Six Engine Properties** (non-negotiable design goals):
1. **Efficiency** — Maximum concurrent scheduling, zero redundant blocking
2. **Full Transparency** — Execution path is fully white-box observable
3. **Security & Isolation** — Single-point failure must not cascade system-wide
4. **Redundancy / Resilience** — Graceful degradation, timeout circuit-breaking, multi-model fallback
5. **Auditability** — All decision paths leave immutable evidence trails
6. **Updatability / Evolvability** — Stable protocols, hot-swappable implementations

**Four Evolution Axes** (orthogonal expansion dimensions):
- **Engine Axis**: Planning → Orchestration → Critic → Memory → Learner...
- **Orchestration Axis**: Agent collaboration → DAG routing → Parallel merge → Retry/backoff → Multi-pool routing
- **Observability Axis**: Trace Keys → SQLiteSink → Guardrails → Sufficiency Reports → Monitoring dashboards
- **Component Axis**: Tools/Skills → API integration → Data connectors → Standardized packaging

---

## Quick Start

### Requirements

- Python 3.12+
- Git

### Run Tests

```bash
cd godot-qwen-agent

# Install dependencies
pip install -r requirements.txt

# Run full test suite (673 tests)
pytest tests/ -q

# Run architecture compliance check (16 rules)
python -m guardrails check --all
```

### Launch Visual Demo

```bash
cd godot-qwen-agent/demo
pip install -r requirements.txt
streamlit run app.py
```

No API key required — MockBackend drives all engines with reproducible results. Open `http://localhost:8501` in a browser:

| Tab | What It Shows |
|-----|---------------|
| 🧠 Engine Pipeline | Planning → Orchestration → Critic live streaming execution |
| 🛡 Guardrail Scanner | 16 AST rules + dynamic violation injection demo |
| 📋 Trace Audit | SQLite audit log queries + engine timeline chart |
| 📖 Architecture Docs | Technical deep-dives + plain-language explanations |

### CI/CD

Automatically triggered on push to GitHub (`.github/workflows/ci.yml`):
- **test job**: Guardrails ERROR + WARNING + full pytest (673 tests)
- **quick job**: Fast-mode pytest (skip slow markers)

---

## Project Structure

```
agent/                              # Repository root
├── README.md                       # This file (Chinese)
├── README_EN.md                    # English version
├── godot-qwen-agent/               # Main project
│   ├── core/                       #   Infrastructure (contracts / adapters / observability / pipeline)
│   ├── engines/                    #   Engine layer (planning / orchestration / critic, each stub + LLM)
│   ├── guardrails/                 #   AST architecture compliance scanner (16 rules)
│   ├── tests/                      #   673 tests (conformance / integration / e2e)
│   ├── demo/                       #   Streamlit visual demo (zero-intrusion into main codebase)
│   ├── docs/                       #   Docs (security portfolio, RAG test data, etc.)
│   ├── .ai_reasoning/              #   21 reasoning chains + 4 Sufficiency Reports
│   ├── PLAN.md                     #   Full architecture plan (18-phase evolution + constitution)
│   └── CLAUDE.md                   #   AI collaboration protocol + architectural invariants
├── install_deps.bat                # Windows dependency install script
├── vscode-dev-env.ps1              # VSCode dev environment config
└── 启动开发环境.bat                 # One-click dev environment launcher
```

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Test cases | 673 (100% passing) |
| Guardrail rules | 16 (AST-level enforcement) |
| Engine implementations | 6 (Planning × 2 + Orchestration × 2 + Critic × 2) |
| Trace Keys | 18 (full pipeline coverage) |
| Reasoning chains | 21 (each recording decisions / alternatives / anti-patterns) |
| Sufficiency Reports | 4 (formal trace key semantic sufficiency) |
| Phases | 18 (complete engineering record) |

---

## Future Directions

### Short-term (Phase 19-21)

- **Memory Engine**: Introduce persistent memory for cross-session contextual reasoning. Requires new `memory.*` trace keys and Sufficiency Report v5.
- **Multi-level DAG Parallelism**: Currently only supports single-level fan-out (2 branches, WAIT_ALL). Extend to nested DAGs with more merge strategies (WAIT_ANY, PRIORITY).
- **Real LLM Fault Injection**: Replace chaos injection in Stub layer with real failure scenarios — token exhaustion, rate limiting, model unavailability — to verify graceful degradation paths.

### Mid-term (Phase 22-25)

- **Learner Engine**: Auto-optimize Planning strategies based on Critic feedback and historical Traces. This closes the "Plan → Execute → Evaluate → Improve" loop.
- **Multi-Agent Collaboration Protocol**: Inter-agent messaging, task delegation, consensus mechanisms. Explore the new dimension of "multi-agent security" — single-agent safety does not guarantee multi-agent system safety.
- **Monitoring Dashboard**: Upgrade from SQLite to time-series databases (e.g., ClickHouse), build production-grade Trace dashboards (Grafana), implement real-time anomaly alerting.

### Long-term Vision

- **Formal Verification**: Elevate Guardrail rules from AST pattern matching to formal semantic verification. Model critical security properties with TLA+ or Alloy.
- **Security Benchmark Dataset**: Build standardized test sets for AI Agent security, covering prompt injection, privilege escalation, supply chain poisoning, and other attack surfaces. Every security claim backed by reproducible verification paths.
- **Security-as-Code**: Make security policies version-controllable, testable, CI-runnable code artifacts — not "should" statements in documents.

---

## Security Statement

This project implements three-layer security mechanisms at the architecture level (compile-time AST scanning / runtime isolation / post-hoc trace auditing), with a complete threat model and known limitations documented in `docs/security-portfolio/SECURITY.md`. The core claim is: **AI Agent security properties can be engineered, defined, detected, and traced** — not that all attack surfaces are covered.

---

## Author

**FRUNHSAN** — An independently developed AI Agent security architecture experiment platform, also serving as a demonstration of AI security engineering capability.

Built with Claude Code Agent.
