import os
from dotenv import load_dotenv

# Does not override variables already set in the environment,
# so docker-compose env always wins over a local .env file.
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", OLLAMA_URL)
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

GEN_MODEL = os.getenv("GEN_MODEL", "llama3:latest")
EMBED_MODEL = os.getenv("EMBED_MODEL", "embeddinggemma:latest")
GEN_MODEL_CLOUD = os.getenv("GEN_MODEL_CLOUD")
EMBED_MODEL_CLOUD = os.getenv("EMBED_MODEL_CLOUD") or os.getenv("OLLAMA_EMBED_MODEL")

# Dimension of EMBED_MODEL output. embeddinggemma -> 768.
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
