from __future__ import annotations

import hmac
import logging
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from chatsync.protocol import (
    INGEST_PATH,
    STREAM_LOOKUP_PATH,
    GapResponse,
    IngestRequest,
    IngestResponse,
    StreamInfo,
)
from chatsync.server.config import ServerConfig
from chatsync.server.db import init_schema, make_engine
from chatsync.server.ingest import GapError, ingest, lookup_stream

log = logging.getLogger("chatsync.server")


def create_app(config: ServerConfig, engine: Engine | None = None) -> FastAPI:
    engine = engine or make_engine(config.database_url)
    init_schema(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI(title="chatsync", version="0.1.0")

    def get_session() -> Iterator[Session]:
        with SessionLocal() as session:
            yield session

    def authenticate(
        x_client_id: str = Header(...),
        x_api_key: str = Header(...),
    ) -> str:
        expected = config.api_keys.get(x_client_id)
        if expected is None or not hmac.compare_digest(expected, x_api_key):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid client id or api key")
        return x_client_id

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        INGEST_PATH,
        response_model=IngestResponse,
        responses={409: {"model": GapResponse}},
    )
    def post_ingest(
        req: IngestRequest,
        client_id: str = Depends(authenticate),
        session: Session = Depends(get_session),
    ):
        if req.client_id != client_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "client_id mismatch")
        try:
            with session.begin():
                resp = ingest(session, req)
        except GapError as e:
            log.warning(
                "gap: client=%s stream=%s start=%d committed=%d",
                req.client_id, req.stream_id, req.start_offset, e.committed_offset,
            )
            body = GapResponse(detail="gap before start_offset", committed_offset=e.committed_offset)
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())
        log.info(
            "ingest: client=%s stream=%s [%d,%d) inserted=%d%s",
            req.client_id, req.stream_id, req.start_offset, req.end_offset,
            resp.inserted, " (duplicate)" if resp.duplicate else "",
        )
        return resp

    @app.get(STREAM_LOOKUP_PATH, response_model=StreamInfo)
    def get_stream(
        file_identity: str = Query(...),
        client_id: str = Depends(authenticate),
        session: Session = Depends(get_session),
    ):
        info = lookup_stream(session, client_id, file_identity)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "stream not found")
        return info

    return app
