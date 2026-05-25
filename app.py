import os
import re
import threading
import asyncio
import time
import sqlite3
import subprocess
import shutil
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import List
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import simulator
import agent
import indexer

app = FastAPI(title="CHRONOS - Local SRE GraphRAG Agent")

# ── Thread-safe Application State (replaces os.environ mutation) ──
class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self._codebase_dir = os.environ.get("CODEBASE_DIR", "services")

    def get_codebase_dir(self) -> str:
        with self._lock:
            return self._codebase_dir

    def set_codebase_dir(self, path: str):
        with self._lock:
            self._codebase_dir = path
            os.environ["CODEBASE_DIR"] = path  # Keep env in sync for agent.py reads

state = AppState()

# ── Allowed git hosts to prevent subprocess injection (Bug #7) ──
ALLOWED_GIT_HOSTS = ("https://github.com/", "https://gitlab.com/", "https://bitbucket.org/")

def _validate_git_url(url: str):
    url = url.strip()
    if not any(url.startswith(host) for host in ALLOWED_GIT_HOSTS):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid URL. Only public repos from GitHub, GitLab, or Bitbucket are allowed."
        )
    return url

# ── Background Simulator Thread (Bug #1: removed dead conn, Bug #2: flush every 10 cycles) ──
def run_background_telemetry():
    """Runs a daemon thread to simulate traffic continuously."""
    print("Background telemetry simulator thread started.")
    cycle = 0
    while True:
        try:
            simulator.simulate_request()
            cycle += 1
            # Issue #2: Force flush every 10 cycles (~12 seconds) for fresh data
            if cycle % 10 == 0:
                simulator.provider.force_flush(timeout_millis=2000)
        except Exception as e:
            print(f"Background simulator error: {e}")
        time.sleep(1.2)

# Start background thread immediately on app startup
@app.on_event("startup")
def startup_event():
    # Bug #2: Always init DB unconditionally to guarantee schema before thread starts
    print("Initializing database schema...")
    simulator.init_db(force=False)

    # Trigger static codebase indexing on default services dir
    try:
        codebase_dir = state.get_codebase_dir()
        indexer.index_codebase(codebase_dir)
    except Exception as e:
        print(f"Error during startup codebase indexing: {e}")

    # Start simulation loop only AFTER DB is guaranteed ready
    t = threading.Thread(target=run_background_telemetry, daemon=True)
    t.start()

# API Models
class AnalyzeRequest(BaseModel):
    query: str
    ollama_url: str = ""
    ollama_model: str = ""
    api_key: str = ""
    api_model: str = ""

class GithubRepoRequest(BaseModel):
    url: str

class SimulateRequest(BaseModel):
    minutes: int
    mode: str

# Endpoints
@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    """Serves the front-end dashboard."""
    if os.path.exists("index.html"):
        with open("index.html", "r") as f:
            return f.read()
    else:
        raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/api/telemetry")
def get_telemetry():
    """Fetches the latest sieved telemetry graph (nodes, edges, logs, metrics)."""
    try:
        data = agent.extract_jit_telemetry(lookback_minutes=20)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze")
async def trigger_agent_analysis(request: AnalyzeRequest):
    """Triggers the GraphRAG agent. Runs LLM call off the main event loop (Issue #1)."""
    try:
        # Extract sieved JIT telemetry (fast DB read, ok on main loop)
        telemetry = agent.extract_jit_telemetry(lookback_minutes=20)
        if "error" in telemetry:
            raise HTTPException(status_code=500, detail=telemetry["error"])

        # Issue #1: Run blocking LLM call in a thread so FastAPI stays responsive
        analysis_result = await asyncio.to_thread(
            agent.analyze_incident,
            telemetry,
            request.query,
            request.ollama_url,
            request.ollama_model,
            request.api_key,
            request.api_model
        )
        return {
            "telemetry": telemetry,
            "analysis": analysis_result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reset")
def reset_database():
    """Wipes the database and resets failure state to none."""
    try:
        simulator.init_db(force=True)
        simulator.invalidate_cache()
        # Also clean up tmp repos
        if os.path.exists(".tmp_repos"):
            shutil.rmtree(".tmp_repos")
        # Reset to default services dir
        state.set_codebase_dir("services")
        indexer.index_codebase("services")
        return {"status": "success", "message": "Database and repos successfully wiped."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/github")
def clone_github_repo(request: GithubRepoRequest):
    """Clones a github repo to a temp directory. Validates URL first."""
    try:
        url = _validate_git_url(request.url)
        repo_dir = ".tmp_repos/github_repo"
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)

        os.makedirs(".tmp_repos", exist_ok=True)
        # Improvement #4: --depth 1 to avoid cloning full git history
        subprocess.run(["git", "clone", "--depth", "1", url, repo_dir], check=True, timeout=120)

        state.set_codebase_dir(repo_dir)
        return {"status": "success", "message": f"Successfully cloned {url}. Ready to index."}
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Git clone timed out after 120 seconds.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/index")
def index_repo():
    """Explicitly triggers the heavy AST indexing on the current codebase directory."""
    try:
        repo_dir = state.get_codebase_dir()
        # Reset DB telemetry before indexing new repo
        simulator.init_db(force=True)
        indexer.index_codebase(repo_dir)
        # Bug #3: Invalidate simulator cache so it picks up new graph immediately
        simulator.invalidate_cache()
        return {"status": "success", "message": f"Successfully built AST Graph for {repo_dir}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/upload")
async def upload_local_folder(
    files: List[UploadFile] = File(...),
    paths: List[str] = Form(...),
):
    """Receives an uploaded folder and stores it for indexing."""
    try:
        repo_dir = ".tmp_repos/upload_repo"
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)

        for file, path in zip(files, paths):
            # Use the explicitly passed path from webkitRelativePath
            file_path = os.path.join(repo_dir, path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)

        state.set_codebase_dir(repo_dir)
        return {"status": "success", "message": f"Successfully uploaded {len(files)} files. Ready to index."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/simulate")
def generate_simulation(request: SimulateRequest):
    """Runs the APM simulation to generate traces and logs."""
    try:
        simulator.set_chaos_state(request.mode)
        simulator.generate_bulk(duration_minutes=request.minutes)
        return {"status": "success", "message": f"Simulated {request.minutes} minutes of APM traffic with {request.mode}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI dashboard on http://localhost:8000...")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
