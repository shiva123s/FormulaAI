import os
import logging
import asyncio
from dotenv import load_dotenv

from graph.connection import get_neo4j
from graph.schema import GraphSchema

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def initialize_db_async():
    logger.info("Initializing Neo4j Knowledge Graph Ontology (Phase 2)...")
    
    neo4j = get_neo4j()
    try:
        await neo4j.connect()
        schema = GraphSchema(neo4j)
        stats = await schema.initialize()
        logger.info(f"Knowledge Graph Ontology initialized successfully. Stats: {stats}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    finally:
        await neo4j.close()

def initialize_db():
    asyncio.run(initialize_db_async())

if __name__ == "__main__":
    initialize_db()
