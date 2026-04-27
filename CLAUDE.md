# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.14. Virtual environment is at `.venv/`.

```
source .venv/bin/activate
```

System dependencies: `graphviz` (installed via Homebrew).

## Project Overview

An AI-powered Azure Solution Architect agent that analyzes Azure architecture diagrams and generates improved ones using official Azure icons.

## Key Files

| File | Purpose |
|------|---------|
| `agent.py` | Core agent — analyze diagrams, generate diagrams, Q&A |
| `app.py` | Streamlit web UI (4 tabs) |
| `skills/unzip.py` | Utility to unzip files |
| `skills/fetch_context.py` | Fetch and store webpage context for firm-specific guidelines |
| `.env` | Anthropic API key (`ANTHROPIC_API_KEY`) — never commit |

## Running the App

```bash
source .venv/bin/activate
streamlit run app.py
# Opens at http://localhost:8501
```

## CLI Usage

```bash
source .venv/bin/activate

# Analyze a diagram screenshot
python agent.py analyze path/to/diagram.png

# Generate a new diagram
python agent.py generate "microservices with AKS, Cosmos DB, and Service Bus"

# Unzip a file
python skills/unzip.py archive.zip [destination]
```

## UI Tabs

- **Analyze Diagram** — Upload a screenshot, get WAF scores + auto-generated improved diagram
- **Generate Diagram** — Describe an architecture, generate PNG with official Azure icons
- **Ask Architect** — Free-form Q&A with senior Azure Solution Architect persona
- **Context Links** — Add webpage URLs (firm standards, compliance policies) to guide diagram generation

## Skills

### azure-diagrams skill
Located at `azure-diagrams/azure-diagrams/`. Provides:
- 700+ official Microsoft Azure icons via the `diagrams` Python library
- Reference docs in `azure-diagrams/azure-diagrams/references/`
- Component index auto-built at runtime from the installed `diagrams` library

### fetch_context skill
Located at `skills/fetch_context.py`. Fetches and stores webpage content in `context/`.
Stored context is automatically injected into every diagram generation prompt.

## Key Design Decisions

- `_COMPONENT_INDEX` in `agent.py` — built at import time by scanning all installed `diagrams.azure.*` modules. Used to validate and correct model-generated import statements.
- `_fix_imports()` in `agent.py` — rewrites any wrong `diagrams.azure` module paths and hoists misplaced imports (inside `with` blocks) to the top of generated code. Prevents `ImportError` and `IndentationError`.
- `analyze_and_improve()` — single API call that returns both the WAF analysis report and the improved diagram code in one response.
- Context from `context/` is loaded and injected into prompts at call time, not at startup, so adding new URLs takes effect immediately.

## Dependencies

```
anthropic
python-dotenv
streamlit
diagrams
matplotlib
requests
beautifulsoup4
graphviz (system)
```

## Output Files

Generated diagrams are saved to `outputs/` as PNG files.
Context documents are stored in `context/` as plain text with an `index.json` index.

## Notes

- `.env` and `context/` contain potentially sensitive data — both are in `.gitignore`
- Never commit the `outputs/` folder if diagrams contain proprietary architecture info
