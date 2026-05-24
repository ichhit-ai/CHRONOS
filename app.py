# FastAPI Backend Server for Local GraphRAG SRE Agent
import os
import threading
import time
import sqlite3
from fastapi import FastAPI, HTTPException
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
            simulator.simulate_request(conn)
            conn.commit()
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
    gemini_api_key: str = ""

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
            request.gemini_api_key
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
        return {"status": "success", "message": "Database successfully wiped and reset."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Pre-emptively install dependencies if not present
    print("Starting FastAPI dashboard on http://localhost:8000...")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
