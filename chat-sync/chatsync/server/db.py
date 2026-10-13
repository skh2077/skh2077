"""DB 스키마. PostgreSQL / MySQL 공용 (SQLAlchemy)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# SQLite(테스트용)는 BIGINT PK 자동증가를 지원하지 않아 INTEGER 로 대체
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class Stream(Base):
    """원본 파일 하나(의 한 세대). 파일 교체·비우기가 감지되면 클라이언트가 새 stream_id 를 만든다."""

    __tablename__ = "chat_streams"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", name="uq_stream"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64))
    stream_id: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(String(1024))
    file_identity: Mapped[str] = mapped_column(String(128), index=True)
    # 여기까지(바이트, 미포함) 저장 완료. 항상 줄 경계.
    committed_offset: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """채팅 한 줄."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("stream_pk", "byte_offset", name="uq_message_offset"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    stream_pk: Mapped[int] = mapped_column(ForeignKey("chat_streams.id", ondelete="CASCADE"))
    byte_offset: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def init_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
