from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from chatsync.protocol import API_KEY_HEADER, CLIENT_ID_HEADER
from chatsync.server.app import create_app
from chatsync.server.config import ServerConfig
from chatsync.server.db import Base

API_KEYS = {"pc-01": "secret-1", "pc-02": "secret-2"}

# 실제 PostgreSQL/MySQL 로도 돌리려면: CHATSYNC_TEST_DATABASE_URL=postgresql+psycopg://...
_DB_URLS = ["sqlite"]
if os.environ.get("CHATSYNC_TEST_DATABASE_URL"):
    _DB_URLS.append(os.environ["CHATSYNC_TEST_DATABASE_URL"])


@pytest.fixture(params=_DB_URLS)
def engine(request, tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}" if request.param == "sqlite" else request.param
    eng = create_engine(url)
    Base.metadata.drop_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def app(engine):
    config = ServerConfig(database_url=str(engine.url), api_keys=API_KEYS)
    return create_app(config, engine=engine)


@pytest.fixture
def http(app):
    with TestClient(app, headers={CLIENT_ID_HEADER: "pc-01", API_KEY_HEADER: "secret-1"}) as c:
        yield c


def fetch_messages(engine) -> list[tuple[int, str]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT byte_offset, content FROM chat_messages ORDER BY byte_offset"))
        return [(r[0], r[1]) for r in rows]
