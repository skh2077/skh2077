from __future__ import annotations

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    # SQLAlchemy URL. 예)
    #   postgresql+psycopg://user:pass@localhost:5432/chatsync
    #   mysql+pymysql://user:pass@localhost:3306/chatsync?charset=utf8mb4
    database_url: str
    # client_id -> API 키. 각 클라이언트는 자기 client_id 로만 저장할 수 있다.
    api_keys: dict[str, str] = Field(min_length=1)
    log_level: str = "INFO"
