import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

try:
    from neo4j import GraphDatabase  # type: ignore
    from graph.connection import get_neo4j  # type: ignore
    from graph.schema import GraphSchema  # type: ignore
    NEO4J_AVAILABLE = True
except ImportError:
    get_neo4j = None  # type: ignore
    GraphSchema = None  # type: ignore
    NEO4J_AVAILABLE = False

try:
    import redis.asyncio as redis  # type: ignore
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False

from dotenv import load_dotenv

try:
    from celery.result import AsyncResult  # type: ignore
    from pipeline.orchestrator import run_extraction_pipeline, celery_app  # type: ignore
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

try:
    from agents.orchestrator import run_formulation_agent  # type: ignore
    AGENTS_AVAILABLE = True
except ImportError as e:
    run_formulation_agent = None  # type: ignore
    AGENTS_AVAILABLE = False

from pipeline.models import PipelineJobRequest, PipelineJobResponse, PipelineStatus

load_dotenv()

logger = logging.getLogger(__name__)

# Environment Variables
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Neo4j schema using Phase 2 modules (with graceful degraded fallback)
    if NEO4J_AVAILABLE and get_neo4j is not None and GraphSchema is not None:
        neo4j = get_neo4j()
        try:
            await asyncio.wait_for(neo4j.connect(), timeout=2.0)
            schema = GraphSchema(neo4j)
            await asyncio.wait_for(schema.initialize(), timeout=2.0)
            logger.info("Neo4j initialized successfully.")
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("Neo4j not reachable (%s); running in degraded mode.", e)
    else:
        logger.warning("neo4j driver not installed; running in degraded mode.")

    # Setup global connections (with graceful degraded fallback)
    if REDIS_AVAILABLE and redis is not None:
        try:
            app.state.redis_client = redis.from_url(REDIS_URL, socket_connect_timeout=1.5, socket_timeout=1.5)
            await asyncio.wait_for(app.state.redis_client.ping(), timeout=1.5)
            logger.info("Redis connected successfully.")
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("Redis not reachable (%s); running in degraded mode.", e)
            app.state.redis_client = None
    else:
        logger.warning("Redis client package is not installed; running in degraded mode.")
        app.state.redis_client = None

    print("\n" + "=" * 65)
    print("🚀 FormulaAI Backend started successfully!")
    print("📡 Local API URL:       http://127.0.0.1:8000")
    print("📖 Interactive Docs:    http://127.0.0.1:8000/docs")
    print("💓 Health Check:        http://127.0.0.1:8000/health")
    print("⚡ WebSocket Streaming: ws://127.0.0.1:8000/ws/agent-stream")
    print("💡 Status: Server is active and listening. (Press Ctrl+C to stop)")
    print("=" * 65 + "\n", flush=True)

    yield

    # Cleanup
    if NEO4J_AVAILABLE and get_neo4j is not None:
        try:
            neo4j = get_neo4j()
            await neo4j.close()
        except Exception:
            pass
    if getattr(app.state, "redis_client", None) is not None:
        try:
            await app.state.redis_client.close()
        except Exception:
            pass

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
    status = {"status": "ok", "neo4j": "unknown", "redis": "unknown"}
    
    # Check Neo4j
    if not NEO4J_AVAILABLE or get_neo4j is None:
        status["neo4j"] = "driver not installed"
        status["status"] = "degraded"
    else:
        neo4j = get_neo4j()
        try:
            if neo4j.is_connected:
                await asyncio.wait_for(neo4j.driver.verify_connectivity(), timeout=1.5)
                status["neo4j"] = "connected"
            else:
                status["neo4j"] = "disconnected"
        except Exception as e:
            status["neo4j"] = f"error: {str(e)}"
            status["status"] = "degraded"
        
    # Check Redis
    if not REDIS_AVAILABLE:
        status["redis"] = "client not installed"
        status["status"] = "degraded"
    else:
        try:
            if getattr(app.state, "redis_client", None) is not None:
                await asyncio.wait_for(app.state.redis_client.ping(), timeout=1.5)
                status["redis"] = "connected"
            else:
                status["redis"] = "disconnected"
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
                
            if not AGENTS_AVAILABLE or run_formulation_agent is None:
                await websocket.send_json({
                    "type": "error",
                    "message": "LangChain/LangGraph dependencies not installed. In terminal run: pip install langchain langchain-core langchain-google-genai langgraph"
                })
                await websocket.send_json({"type": "pipeline_complete"})
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
    if not CELERY_AVAILABLE:
        return PipelineJobResponse(
            job_id="celery_unavailable",
            status="failed",
            message="Celery is not installed in the current environment. Run pipeline via docker-compose up or install celery."
        )
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
    if not CELERY_AVAILABLE:
        return PipelineStatus(
            job_id=job_id,
            status="FAILED",
            error="Celery is not installed in the current Python environment."
        )
    task_result = AsyncResult(job_id, app=celery_app)
    
    return PipelineStatus(
        job_id=job_id,
        status=task_result.status,
        result=task_result.result if task_result.successful() else None,
        error=str(task_result.result) if task_result.failed() else None,
    )

