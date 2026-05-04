from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runner
from app.brands import BrandRepo
from app.main import app


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Swap the module-level `app.runner._repo` with one rooted at tmp_path.

    `main.py` fetches the repo via `get_repo()` which returns `app.runner._repo`,
    so patching the attribute is enough — no need to patch `get_repo` itself.
    """
    repo = BrandRepo(root=tmp_path)
    monkeypatch.setattr(runner, "_repo", repo)
    return repo


@pytest.fixture
def client(tmp_repo):
    """TestClient wired to an isolated tmp repo. Always depend on this for
    any test that touches brand/source/run endpoints."""
    with TestClient(app) as c:
        yield c
