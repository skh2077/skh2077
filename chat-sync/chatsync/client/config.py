from __future__ import annotations

import codecs
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ServerSection(BaseModel):
    # 서버 주소. 예) http://192.168.0.10:8000  (API 경로는 자동으로 붙음)
    url: HttpUrl
    api_key: str = Field(min_length=1)
    timeout_sec: float = Field(default=10.0, gt=0)


class RetrySection(BaseModel):
    initial_backoff_sec: float = Field(default=1.0, gt=0)
    max_backoff_sec: float = Field(default=60.0, gt=0)


class ClientConfig(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    # 감시할 채팅 텍스트파일 전체 경로
    source_file: Path
    # 전송 위치 기록 파일
    state_file: Path = Path("./chatsync-state.json")
    # ASCII 호환 인코딩만 지원 (utf-8, cp949, euc-kr 등). UTF-16 불가.
    encoding: str = "utf-8"
    poll_interval_sec: float = Field(default=2.0, gt=0)
    # 파일 변경 이벤트 감시 사용 여부. 꺼도 poll_interval_sec 마다 폴링한다.
    use_file_events: bool = True
    # 한 번에 보낼 최대 바이트 (한 줄이 이보다 길면 그 줄만 단독 전송)
    max_batch_bytes: int = Field(default=256 * 1024, ge=1024)
    log_level: str = "INFO"
    server: ServerSection
    retry: RetrySection = RetrySection()

    @field_validator("encoding")
    @classmethod
    def _check_encoding(cls, v: str) -> str:
        try:
            info = codecs.lookup(v)
        except LookupError:
            raise ValueError(f"알 수 없는 인코딩: {v}") from None
        if "\n".encode(info.name) != b"\n":
            raise ValueError(f"ASCII 호환 인코딩만 지원합니다 (UTF-16/32 불가): {v}")
        return v
