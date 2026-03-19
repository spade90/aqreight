import os
import pytest
from fastapi.testclient import TestClient

# Force in-memory vector store so tests never need a running Qdrant instance
os.environ.setdefault("VECTOR_STORE", "memory")

from app.main import app

@pytest.fixture(scope="session")
def client():
    return TestClient(app)
