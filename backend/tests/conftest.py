import pytest
from fastapi.testclient import TestClient

from app.data import store
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_data_store():
    """Each test gets an empty in-memory data store."""
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())
