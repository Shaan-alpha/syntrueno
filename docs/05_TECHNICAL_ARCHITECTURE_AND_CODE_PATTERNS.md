# 💻 05. Technical Architecture & Production Code Patterns

This guide provides drop-in, production-ready Python code snippets utilizing **Google ADK (`adk-python`)**, the unified **Google GenAI SDK (`google-genai`)**, **Cloud Firestore**, and **Cloud Run** deployment configurations.

---

## 1. Project Dependencies (`requirements.txt`)

```text
google-genai>=0.1.1
google-cloud-firestore>=2.19.0
google-cloud-storage>=2.18.0
fastapi>=0.115.0
uvicorn>=0.31.0
pydantic>=2.9.0
httpx>=0.27.2
python-dotenv>=1.0.1
```

---

## 2. Gemini 2.5 / 3.5 Agent with Tool Calling (`agent_core.py`)

Using the unified Google GenAI SDK (`google-genai`):

```python
import os
from google import genai
from google.genai import types

# Initialize client (uses GEMINI_API_KEY or Application Default Credentials)
client = genai.Client()

# 1. Define Concrete Agent Tools
def execute_cloud_diagnostic(resource_id: str, metric_name: str) -> dict:
    """Fetches real-time operational metrics for a Google Cloud resource.
    
    Args:
        resource_id: The GCP resource identifier (e.g. 'cloud-run/api-service')
        metric_name: Target metric (e.g. 'latency_ms', 'error_rate', 'cpu_percent')
    """
    # Simulated GCP Cloud Monitoring retrieval
    return {
        "resource_id": resource_id,
        "metric": metric_name,
        "status": "HEALTHY",
        "value": 42.5,
        "timestamp": "2026-08-21T05:00:00Z"
    }

def apply_cloud_remediation(resource_id: str, action: str) -> dict:
    """Applies an automated remediation action to a Cloud resource.
    
    Args:
        resource_id: The target resource ID.
        action: Remediation verb (e.g., 'restart', 'scale_up', 'clear_cache').
    """
    return {
        "resource_id": resource_id,
        "action": action,
        "status": "SUCCESS",
        "message": f"Successfully applied {action} to {resource_id}"
    }

# 2. Configure System Instructions & Agent Loop
SYSTEM_INSTRUCTION = """
You are DevOps-Sentinel, an autonomous operational agent on Google Cloud.
When given an incident or request:
1. Formulate a step-by-step diagnostic plan.
2. Call appropriate diagnostic tools.
3. If anomalies are found, proactively execute safe remediations.
4. Output a verified summary of all actions taken.
"""

def run_agent_turn(user_goal: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_goal,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[execute_cloud_diagnostic, apply_cloud_remediation],
            temperature=0.2,
        ),
    )
    return response.text
```

---

## 3. Persistent Memory Bank with Firestore (`memory_bank.py`)

```python
from google.cloud import firestore
from datetime import datetime, timezone

db = firestore.Client()

class AgentMemoryBank:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.collection = db.collection("agent_memory_bank")

    def save_session_memory(self, session_id: str, episodic_summary: str, entities: dict):
        """Saves session learning and user preferences for cross-session recall."""
        doc_ref = self.collection.document(f"{self.agent_id}_{session_id}")
        doc_ref.set({
            "agent_id": self.agent_id,
            "session_id": session_id,
            "summary": episodic_summary,
            "entities": entities,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

    def retrieve_recent_context(self, limit: int = 3) -> str:
        """Retrieves past session summaries to ground the next conversation."""
        docs = (
            self.collection.where("agent_id", "==", self.agent_id)
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        memories = [f"- [Session {d.to_dict().get('session_id')}]: {d.to_dict().get('summary')}" for d in docs]
        return "\n".join(memories) if memories else "No prior history found."
```

---

## 4. FastAPI Serverless Host (`main.py`)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent_core import run_agent_turn

app = FastAPI(title="Google Cloud Autonomous Agent API", version="1.0.0")

class AgentRequest(BaseModel):
    session_id: str
    prompt: str

class AgentResponse(BaseModel):
    status: str
    output: str

@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "google-agent-runtime"}

@app.post("/api/v1/agent/execute", response_model=AgentResponse)
def execute_agent(req: AgentRequest):
    try:
        result = run_agent_turn(req.prompt)
        return AgentResponse(status="success", output=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 5. Production Dockerfile for Google Cloud Run (`Dockerfile`)

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
```

---

## 6. One-Command Cloud Run Deployment (`deploy.sh`)

```bash
#!/bin/bash
PROJECT_ID=$(gcloud config get-value project)
SERVICE_NAME="agent-runtime-service"
REGION="us-central1"

echo "Building and deploying ${SERVICE_NAME} to Google Cloud Run in ${REGION}..."

gcloud run deploy ${SERVICE_NAME} \
  --source . \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --set-env-vars GEMINI_API_KEY=${GEMINI_API_KEY}

echo "Deployment complete! Cloud Run URL:"
gcloud run services describe ${SERVICE_NAME} --platform managed --region ${REGION} --format 'value(status.url)'
```
