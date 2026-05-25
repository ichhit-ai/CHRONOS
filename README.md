# CHRONOS // Code-Aware SRE GraphRAG Agent

**CHRONOS** is a completely autonomous, codebase-agnostic **Site Reliability Engineering (SRE) GraphRAG Agent** that automates root cause analysis for any Python repository. 

By marrying **Static Codebase AST (Abstract Syntax Tree) Ontology** with **Dynamic Live APM Telemetry**, CHRONOS isolates operational outages down to the exact buggy function and lines of code. It uses GraphRAG to provide copy-pasteable Git Diff resolutions directly inside an interactive, glassmorphic dark-mode dashboard.

---

## ⚡ The Architectural Blueprint

CHRONOS works by aligning two independent layers of system topology:

```
[ STATIC LAYER: CODEBASE AST GRAPH ] (Built autonomously from ANY Repo)
  - Uses a Python AST Parser to walk your codebase.
  - Maps Nodes (Classes, Functions) and Edges (Call structures).
       |
       |  <-- Causal Alignment Join (Triggered on alert)
       v
[ DYNAMIC LAYER: DYNAMIC OPEN-TELEMETRY SIMULATOR ] 
  - Performs dynamic "Random Walks" across the AST graph.
  - Generates authentic APM Spans and Latency metrics based on your actual codebase.
```

When an alert fires, CHRONOS superimposes the failing dynamic path directly onto the static code call graph. The **GraphRAG Agent** receives the topology, the live logs, AND the raw Python source code to pinpoint exactly where the code is bottlenecking, completely automatically!

---

## 🚀 Quickstart Guide

Ensure you have Python 3.10+ installed on your system.

### 1. Install Dependencies
Clone the repository and install the lightweight requirements:
```bash
pip install -r requirements.txt
```

### 2. Spin Up the Platform
Start the FastAPI dashboard server:
```bash
python3 app.py
```

### 3. Explore the Dashboard (http://localhost:8000)
1. **Upload a Codebase:** Use the left panel to either clone a public GitHub repository (e.g. `https://github.com/gleitz/howdoi`) or upload a local folder from your machine directly into the browser!
2. **Index AST Graph:** Click the "Index AST Graph" button. The backend parses the files, builds the topological map, and visualizes it instantly using D3.js.
3. **Simulate Outage:** Click a Chaos Trigger (like "Database Lock" or "Auth Leak") to inject OpenTelemetry traffic onto your codebase map. Watch the nodes turn red as failures propagate.
4. **Trigger Agent:** Enter your OpenRouter or Gemini API Key, type a query like *"Analyze the codebase for bottlenecks"*, and click **Ask Agent**. CHRONOS will return the causal chain and a Git Diff to fix the exact function that is failing!

---

## 🔑 Agent LLM Support (Local & Cloud)

CHRONOS has a dynamic router built into the dashboard that supports almost any LLM!

### 1. OpenRouter (Cloud Models)
You can use powerful models like `nvidia/nemotron-4-340b-instruct` or OpenAI's `gpt-4o`.
- **API Key Box:** Paste your OpenRouter API Key.
- **API Model Box:** Paste the model name (e.g., `openai/gpt-4o`).
*Note: Massive free-tier models on OpenRouter may take up to 60 seconds to process the entire GraphRAG payload.*

### 2. Local Ollama (Private Models)
Run CHRONOS completely offline and securely on your own hardware!
- Leave the OpenRouter fields blank.
- Ensure Ollama is running locally.
- Keep the default URL (`http://localhost:11434/api/generate`) and type your model name (e.g., `llama3`).

---

## 🌟 Key Features
* **Codebase-Agnostic:** Upload absolutely ANY Python codebase and CHRONOS will parse its AST, build the topology, and simulate traffic over it automatically.
* **Synchronous UI Uploads:** Decoupled indexer with real-time XMLHttpRequest progress bars ensures the dashboard remains extremely responsive, even when ingesting massive projects.
* **Resilient JSON Extraction:** Bulletproof Regex sanitization handles strict JSON or markdown-wrapped responses from rogue LLMs safely.
* **100% Free & Local-Ready:** No paid log-scraping tools or SaaS databases required. Everything runs locally in SQLite.
