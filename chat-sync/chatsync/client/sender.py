from __future__ import annotations

from dataclasses import dataclass

import httpx

from chatsync.protocol import (
    API_KEY_HEADER,
    CLIENT_ID_HEADER,
    INGEST_PATH,
    STREAM_LOOKUP_PATH,
    IngestRequest,
    IngestResponse,
    StreamInfo,
)


class SendError(Exception):
    """일시적 실패(네트워크, 5xx 등). 재시도 대상."""


class FatalSendError(Exception):
    """설정 오류 등 재시도해도 소용없는 실패 (401/403/422)."""


@dataclass
class Gap:
    committed_offset: int


class Sender:
    def __init__(self, base_url: str, client_id: str, api_key: str, timeout: float,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={CLIENT_ID_HEADER: client_id, API_KEY_HEADER: api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise SendError(f"{type(e).__name__}: {e}") from e
        if resp.status_code in (401, 403, 422):
            raise FatalSendError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        return resp

    def send(self, req: IngestRequest) -> IngestResponse | Gap:
        resp = self._request("POST", INGEST_PATH, content=req.model_dump_json(),
                             headers={"Content-Type": "application/json"})
        if resp.status_code == 409:
            return Gap(committed_offset=int(resp.json()["committed_offset"]))
        if resp.status_code != 200:
            raise SendError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        return IngestResponse.model_validate(resp.json())

    def lookup_stream(self, file_identity: str) -> StreamInfo | None:
        resp = self._request("GET", STREAM_LOOKUP_PATH, params={"file_identity": file_identity})
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SendError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        return StreamInfo.model_validate(resp.json())
