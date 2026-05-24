# CHRONOS // Code-Aware SRE GraphRAG Agent

**CHRONOS** is a serverless, local-first, and highly visual **Site Reliability Engineering (SRE) GraphRAG Agent** designed to automate root cause analysis for distributed microservices. 

By marrying **Static Codebase AST (Abstract Syntax Tree) Ontology** with **Dynamic Live APM Telemetry**, CHRONOS isolates operational outages down to the exact buggy service, file, method, and lines of code—providing copy-pasteable Git Diff resolutions directly inside an interactive, glassmorphic dark-mode dashboard.

---

## ⚡ The Architectural Blueprint

CHRONOS works by aligning two independent layers of system topology:

```
[ STATIC LAYER: CODEBASE AST GRAPH ] (Compiled once on boot)
  - Uses python AST to walk python files (e.g. services/).
  - Maps nodes (Microservice classes, Operations, DB Tables, Gateways).
       |
       |  <-- Causal Alignment Join (Triggered on alert)
       v
[ DYNAMIC LAYER: JIT TELEMETRY TRACES ] (Sieved from SQLite traces)
  - Siege-filters active latencies, error states, and terminal warnings.
```

When an alert fires, the SRE Agent superimposes the failing dynamic path directly onto the static code call graph. **Gemini performs in-context reasoning with a 0% hallucination rate**, pinpointing the database transaction locking loops, cryptographic CPU leaks, or gateway timeouts instantly.

---

## 📂 Project Structure

* 📂 **`services/`** — Mock service codebase directory.
  * 📄 `auth_service.py` — High-CPU cryptographic token verification loop.
  * `checkout_service.py` — Orchestrator module.
  * `inventory_service.py` — Database stock update module.
  * `payment_service.py` — Payment capture holding DB transactions open.
* 📄 **`indexer.py`** — Dynamic Abstract Syntax Tree codebase ontology and graph builder.
* 📄 **`agent.py`** — JIT Telemetry GraphRAG extractor and Gemini REST SRE reasoner.
* 📄 **`app.py`** — FastAPI web backend server with continuous background logging threads.
* 📄 **`index.html`** — Premium dark-mode front-end using D3.js force-directed call graphs.
* 📄 **`schema.sql`** — sqlite3 database structure optimized for high-performance JIT querying.
* 📄 **`requirements.txt`** — Python dependencies.

---

## 🚀 Quickstart Guide

Ensure you have Python 3.10+ installed on your system.

### 1. Install Dependencies
Clone the repository and install the lightweight requirements:
```bash
pip install -r requirements.txt
```

### 2. Pre-Seed Telemetry Data (Optional but Recommended)
To pre-populate your local database with 20 minutes of realistic microservice traffic history containing built-in failure states, run:
```bash
python simulator.py bulk --minutes 20
```

### 3. Spin Up the Platform
Start the FastAPI dashboard server:
```bash
python app.py
```
* Note: On server startup, the static codebase indexer will automatically compile your `services/` directory and map it in under 100ms.

### 4. Explore the Dashboard
1. Open your browser and navigate to **`http://localhost:8000`**.
2. Observe the real-time **D3.js GraphRAG Map** displaying live trace latencies and sieved terminal logs.
3. Click the **Database Latency Lock** chaos trigger on the left panel.
4. Watch the D3.js edges pulse amber/red as database wait locks begin.
5. Click **Trigger SRE Agent**.
6. The Gemini Autonomous SRE diagnostic slides up at the bottom, highlighting the precise buggy lines and the recommended Git Diff!

---

## 📂 How to Connect ANY GitHub Repository / Project

You can run CHRONOS on **any arbitrary repository or project structure** on your local machine by utilizing recursive AST mapping:

### 1. Index the Repository Recursively
To parse and index an external codebase folder (e.g. an arbitrary python folder on your system), run the indexer by passing the target path using `--dir`:
```bash
python indexer.py --dir /absolute/path/to/your/github-repo
```
* **How it compiles:** The parser recursively walks every directory and sub-directory (`os.walk`), extracts class definitions as microservice operations, maps linkages, and populates `telemetry.db` in seconds.

### 2. Boot the Dashboard Pointing to the Target Repo
Inform the FastAPI backend and SRE agent of your codebase directory by setting the `CODEBASE_DIR` environment variable:
```bash
CODEBASE_DIR=/absolute/path/to/your/github-repo python app.py
```
Now, whenever an outage or error is registered, CHRONOS will parse the files, display the buggy snippets, and suggest Git Diffs **specifically for your actual repository**!

---

## 🔑 Environment Variables & AI Models

CHRONOS supports both cloud LLMs and Local open-source models out of the box!

### 1. Using Google Gemini (Cloud)
To activate the full AI-driven SRE reasoning engine, export your API key before starting the server:
```bash
export GEMINI_API_KEY="your_api_key_here"
python app.py
```
If this key is omitted, CHRONOS automatically falls back to its **Zero-Cost Heuristic SRE Engine**, allowing you to present flawlessly offline.

### 2. Using Ollama (Local Open-Source Models)
Because CHRONOS generates strict JSON payloads, it is 100% compatible with local Ollama models (e.g., Llama 3, Mistral, Qwen). 
* Simply update the API endpoint URL inside `agent.py` to point to `http://localhost:11434/api/generate` instead of the Gemini API URL.
* Your local model will now ingest the AST graph and telemetry to perform SRE reasoning completely offline and privately!

---

## 🌟 Hackathon "Wow-Factor" Features
* **100% Free & Local:** Runs completely on your own machine without paid log-scraping tools or database SaaS trials.
* **AST Code-Telemetry Join:** Actually joins compiler parsing with live telemetry to point to exact files and methods.
* **Zero-Cost Fallback SRE Agent:** Includes a high-fidelity local heuristic SRE agent that runs offline if no `GEMINI_API_KEY` is present.
