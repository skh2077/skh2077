"""수신 처리 로직. 스트림별 committed_offset 으로 중복·누락을 판정한다.

요청 구간 [start, end) 과 서버의 committed 를 비교:
  - end   <= committed : 이미 저장된 구간 → 아무것도 저장하지 않음 (duplicate)
  - start >  committed : 중간이 비어 있음 → GapError, 클라이언트가 committed 부터 재전송
  - 그 외               : offset >= committed 인 줄만 저장하고 committed = end
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatsync.protocol import IngestRequest, IngestResponse, StreamInfo
from chatsync.server.db import Message, Stream


@dataclass
class GapError(Exception):
    committed_offset: int


def _lock_stream(session: Session, req: IngestRequest) -> Stream:
    """스트림 행을 잠그고 반환. 없으면 만든다 (동시 생성 경합은 재조회로 처리)."""
    stmt = (
        select(Stream)
        .where(Stream.client_id == req.client_id, Stream.stream_id == req.stream_id)
        .with_for_update()
    )
    stream = session.scalars(stmt).one_or_none()
    if stream is not None:
        return stream
    try:
        with session.begin_nested():
            session.add(
                Stream(
                    client_id=req.client_id,
                    stream_id=req.stream_id,
                    source_path=req.source_path,
                    file_identity=req.file_identity,
                    committed_offset=0,
                )
            )
    except IntegrityError:
        pass  # 다른 요청이 먼저 만들었음
    return session.scalars(stmt).one()


def ingest(session: Session, req: IngestRequest) -> IngestResponse:
    """한 트랜잭션 안에서 호출되어야 한다 (커밋은 호출자 책임)."""
    stream = _lock_stream(session, req)
    committed = stream.committed_offset

    if req.start_offset > committed:
        raise GapError(committed)
    if req.end_offset <= committed:
        return IngestResponse(committed_offset=committed, inserted=0, duplicate=True)

    new_lines = [ln for ln in req.lines if ln.offset >= committed]
    session.add_all(
        Message(stream_pk=stream.id, byte_offset=ln.offset, content=ln.text) for ln in new_lines
    )
    stream.committed_offset = req.end_offset
    stream.source_path = req.source_path
    return IngestResponse(committed_offset=req.end_offset, inserted=len(new_lines))


def lookup_stream(session: Session, client_id: str, file_identity: str) -> StreamInfo | None:
    """클라이언트가 상태 파일을 잃었을 때, 같은 파일의 가장 최근 스트림을 찾아 이어 보내기 위함."""
    stmt = (
        select(Stream)
        .where(Stream.client_id == client_id, Stream.file_identity == file_identity)
        .order_by(Stream.id.desc())
        .limit(1)
    )
    stream = session.scalars(stmt).one_or_none()
    if stream is None:
        return None
    return StreamInfo(stream_id=stream.stream_id, committed_offset=stream.committed_offset)
