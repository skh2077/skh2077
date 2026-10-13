"""클라이언트-서버 간 HTTP 요청/응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

INGEST_PATH = "/api/v1/ingest"
STREAM_LOOKUP_PATH = "/api/v1/streams/lookup"

CLIENT_ID_HEADER = "X-Client-Id"
API_KEY_HEADER = "X-API-Key"


class Line(BaseModel):
    offset: int = Field(ge=0, description="원본 파일 내 이 줄의 시작 바이트 위치")
    text: str


class IngestRequest(BaseModel):
    """원본 파일의 [start_offset, end_offset) 구간에 해당하는 완성된 줄 묶음."""

    client_id: str = Field(min_length=1, max_length=64)
    stream_id: str = Field(min_length=1, max_length=64)
    source_path: str = Field(max_length=1024)
    file_identity: str = Field(max_length=128)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    lines: list[Line]

    @model_validator(mode="after")
    def _check_range(self) -> "IngestRequest":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset 은 start_offset 보다 커야 합니다")
        prev = self.start_offset - 1
        for line in self.lines:
            if not (self.start_offset <= line.offset < self.end_offset):
                raise ValueError(f"line offset {line.offset} 이 구간을 벗어났습니다")
            if line.offset <= prev:
                raise ValueError("lines 는 offset 오름차순이어야 합니다")
            prev = line.offset
        return self


class IngestResponse(BaseModel):
    committed_offset: int
    inserted: int
    duplicate: bool = False


class GapResponse(BaseModel):
    """요청 시작 위치가 서버가 확정한 위치보다 뒤일 때(중간 누락). 클라이언트는 committed_offset 부터 재전송."""

    detail: str
    committed_offset: int


class StreamInfo(BaseModel):
    stream_id: str
    committed_offset: int
