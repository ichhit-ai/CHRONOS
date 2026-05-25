import os
import threading
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

# Background Simulator Thread
def run_background_telemetry():
    """Runs a daemon thread to simulate traffic continuously."""
    print("Background telemetry simulator thread started.")
    # Wait for DB initialization
    time.sleep(0.5)
    
    conn = sqlite3.connect(simulator.DB_PATH)
    while True:
        try:
            simulator.simulate_request()
        except Exception as e:
            print(f"Background simulator error: {e}")
        time.sleep(1.2) # Sleep 1.2s to generate standard paced logs
    conn.close()

# Start background thread immediately on app startup
@app.on_event("startup")
def startup_event():
    # Make sure DB exists and schema is loaded
    if not os.path.exists(simulator.DB_PATH):
        print("Database not found. Initializing database schema...")
        simulator.init_db(force=True)
    
    # Trigger static codebase ontology & graph indexing
    try:
        codebase_dir = os.environ.get("CODEBASE_DIR", "services")
        indexer.index_codebase(codebase_dir)
    except Exception as e:
        print(f"Error during startup codebase indexing: {e}")
    
    # Start the simulation loop
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
def trigger_agent_analysis(request: AnalyzeRequest):
    """Triggers the Ollama/Gemini GraphRAG agent to perform SRE diagnostic analysis."""
    try:
        # Extract sieved JIT telemetry
        telemetry = agent.extract_jit_telemetry(lookback_minutes=20)
        if "error" in telemetry:
            raise HTTPException(status_code=500, detail=telemetry["error"])
        
        # Analyze using agent with user query and settings
        analysis_result = agent.analyze_incident(
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reset")
def reset_database():
    """Wipes the database and resets failure state to none."""
    try:
        simulator.init_db(force=True)
        # Also clean up tmp repos
        if os.path.exists(".tmp_repos"):
            shutil.rmtree(".tmp_repos")
        # Trigger indexer on services as default
        os.environ["CODEBASE_DIR"] = "services"
        indexer.index_codebase("services")
        return {"status": "success", "message": "Database and repos successfully wiped."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/github")
def clone_github_repo(request: GithubRepoRequest):
    """Clones a github repo to a temp directory and indexes it."""
    try:
        repo_dir = ".tmp_repos/github_repo"
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
            
        os.makedirs(".tmp_repos", exist_ok=True)
        subprocess.run(["git", "clone", request.url, repo_dir], check=True)
        
        os.environ["CODEBASE_DIR"] = repo_dir
        return {"status": "success", "message": f"Successfully cloned {request.url}. Ready to index."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/index")
def index_repo():
    """Explicitly triggers the heavy AST indexing on the current codebase directory."""
    try:
        repo_dir = os.environ.get("CODEBASE_DIR", "services")
        # Reset DB before indexing new repo
        simulator.init_db(force=True)
        indexer.index_codebase(repo_dir)
        return {"status": "success", "message": f"Successfully built AST Graph for {repo_dir}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/repo/upload")
async def upload_local_folder(
    files: List[UploadFile] = File(...),
    paths: List[str] = Form(...)
):
    """Receives an uploaded folder and indexes it."""
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
                
        os.environ["CODEBASE_DIR"] = repo_dir
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
    # Pre-emptively install dependencies if not present
    print("Starting FastAPI dashboard on http://localhost:8000...")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
