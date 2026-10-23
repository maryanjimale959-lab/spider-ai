"""Shared pytest fixtures: isolated database per test run, inline job execution."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="spider-test-"))
os.environ["SPIDER_DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["SPIDER_STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["SPIDER_RENDERED_DIR"] = str(TEST_ROOT / "storage" / "rendered")
os.environ["SPIDER_SECRET_KEY"] = "test-secret-key-not-for-production"

from app import worker  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import Base, engine  # noqa: E402

settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.rendered_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _inline_jobs(monkeypatch):
    """Background jobs run synchronously in tests so results are deterministic."""
    monkeypatch.setattr(worker, "submit", lambda kind, identifier: worker._run_investigation(identifier)
                        if kind == "investigation" else worker._run_extraction(identifier))
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def samples_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "samples"
