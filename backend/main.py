import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
import redis.asyncio as redis
from dotenv import load_dotenv
from celery.result import AsyncResult

from db_init import initialize_db
from graph.connection import get_neo4j
from graph.schema import GraphSchema
from pipeline.models import PipelineJobRequest, PipelineJobResponse, PipelineStatus
from pipeline.orchestrator import run_extraction_pipeline, celery_app
from agents.orchestrator import run_formulation_agent

load_dotenv()

logger = logging.getLogger(__name__)

# Environment Variables
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Neo4j schema using Phase 2 modules
    neo4j = get_neo4j()
    await neo4j.connect()
    schema = GraphSchema(neo4j)
    await schema.initialize()
    
    # Setup global connections
    app.state.redis_client = redis.from_url(REDIS_URL)
    
    yield
    
    # Cleanup
    await neo4j.close()
    await app.state.redis_client.close()

app = FastAPI(title="FormulaAI API", lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    neo4j = get_neo4j()
    status = {"status": "ok", "neo4j": "unknown", "redis": "unknown"}
    
    # Check Neo4j
    try:
        if neo4j.is_connected:
            neo4j.driver.verify_connectivity()
            status["neo4j"] = "connected"
        else:
            status["neo4j"] = "disconnected"
    except Exception as e:
        status["neo4j"] = f"error: {str(e)}"
        status["status"] = "degraded"
        
    # Check Redis
    try:
        await app.state.redis_client.ping()
        status["redis"] = "connected"
    except Exception as e:
        status["redis"] = f"error: {str(e)}"
        status["status"] = "degraded"
        
    return status

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/agent-stream")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Expecting JSON payload with formulation requirements
            data = await websocket.receive_json()
            
            user_prompt = data.get("user_prompt")
            active_ingredient = data.get("active_ingredient")
            target_pest = data.get("target_pest")
            payload_type = data.get("payload_type", "chemical")
            
            if not all([user_prompt, active_ingredient, target_pest]):
                await websocket.send_json({
                    "type": "error", 
                    "message": "Missing required fields: user_prompt, active_ingredient, target_pest"
                })
                continue
                
            # Trigger the multi-agent formulation pipeline
            try:
                await run_formulation_agent(
                    user_prompt=user_prompt,
                    active_ingredient=active_ingredient,
                    target_pest=target_pest,
                    payload_type=payload_type,
                    websocket=websocket
                )
                
                # Notify the client that the pipeline has concluded
                await websocket.send_json({"type": "pipeline_complete"})
            except Exception as e:
                logger.error(f"Agent pipeline error: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Pipeline crashed: {str(e)}"
                })
                await websocket.send_json({"type": "pipeline_complete"})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ── Pipeline API Endpoints ───────────────────────────────────────────────────

@app.post("/api/pipeline/ingest", response_model=PipelineJobResponse)
async def start_pipeline_job(request: PipelineJobRequest):
    """
    Trigger a new extraction pipeline job via Celery.
    """
    task = run_extraction_pipeline.delay(request.source_type, request.source_args)
    return PipelineJobResponse(
        job_id=task.id,
        status="queued",
        message=f"Pipeline job for {request.source_type} queued successfully."
    )

@app.get("/api/pipeline/status/{job_id}", response_model=PipelineStatus)
async def get_pipeline_status(job_id: str):
    """
    Check the status of a Celery pipeline job.
    """
    task_result = AsyncResult(job_id, app=celery_app)
    
    return PipelineStatus(
        job_id=job_id,
        status=task_result.status,
        result=task_result.result if task_result.successful() else None,
        error=str(task_result.result) if task_result.failed() else None,
    )

