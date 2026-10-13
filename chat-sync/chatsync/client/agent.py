"""클라이언트 메인 루프: 감지 → 미전송 구간 읽기 → 전송 → ACK 받으면 위치 저장."""

from __future__ import annotations

import logging
import os
import threading
import uuid

from chatsync.client.config import ClientConfig
from chatsync.client.sender import Gap, SendError, Sender
from chatsync.client.state import SyncState, load_state, save_state
from chatsync.client.tailer import file_identity, read_batch
from chatsync.protocol import IngestRequest

log = logging.getLogger("chatsync.client")


class Agent:
    def __init__(self, config: ClientConfig, sender: Sender) -> None:
        self.config = config
        self.sender = sender
        self.source = config.source_file
        self.state: SyncState | None = load_state(config.state_file)
        self.stop_event = threading.Event()
        self.wakeup = threading.Event()
        self._missing_logged = False

    def stop(self) -> None:
        self.stop_event.set()
        self.wakeup.set()

    # ---- 상태 ---------------------------------------------------------------

    def _save(self) -> None:
        assert self.state is not None
        save_state(self.config.state_file, self.state)

    def _start_new_stream(self, ident: str, reason: str) -> None:
        self.state = SyncState(stream_id=uuid.uuid4().hex, file_identity=ident, offset=0)
        log.info("새 스트림 %s 시작 (%s)", self.state.stream_id, reason)
        self._save()

    def _sync_stream(self, ident: str, size: int) -> None:
        """현재 파일에 맞는 스트림을 정한다 (최초 실행, 파일 교체, 파일 비우기 처리)."""
        if self.state is None:
            # 상태 파일이 없으면 서버에 같은 파일의 스트림이 있는지 물어 이어서 보낸다
            info = self.sender.lookup_stream(ident)
            if info is not None and info.committed_offset <= size:
                self.state = SyncState(info.stream_id, ident, info.committed_offset)
                log.info("서버 기록에서 이어서 전송: stream=%s offset=%d", info.stream_id, info.committed_offset)
                self._save()
            else:
                self._start_new_stream(ident, "최초 실행")
        elif self.state.file_identity != ident:
            self._start_new_stream(ident, "파일이 교체됨")
        elif size < self.state.offset:
            self._start_new_stream(ident, f"파일 크기 감소 {self.state.offset} → {size}")

    # ---- 한 번의 처리 ---------------------------------------------------------

    def tick(self) -> bool:
        """미전송 구간을 한 묶음 전송한다. 아직 보낼 게 남았으면 True."""
        try:
            st = os.stat(self.source)
        except FileNotFoundError:
            if not self._missing_logged:
                log.warning("원본 파일이 없습니다. 생길 때까지 대기: %s", self.source)
                self._missing_logged = True
            return False
        self._missing_logged = False

        ident = file_identity(st)
        self._sync_stream(ident, st.st_size)
        assert self.state is not None

        read_ident, size, batch = read_batch(
            self.source, self.state.offset, self.config.max_batch_bytes, self.config.encoding
        )
        if read_ident != self.state.file_identity:
            return True  # stat 과 open 사이에 파일이 교체됨 → 다시 판단
        if batch is None:
            return False

        req = IngestRequest(
            client_id=self.config.client_id,
            stream_id=self.state.stream_id,
            source_path=str(self.source),
            file_identity=self.state.file_identity,
            start_offset=batch.start_offset,
            end_offset=batch.end_offset,
            lines=batch.lines,
        )
        result = self.sender.send(req)
        if isinstance(result, Gap):
            log.warning("서버 기록과 어긋남: offset %d → %d 부터 재전송",
                        self.state.offset, result.committed_offset)
            self.state.offset = result.committed_offset
        else:
            log.info("전송 완료 [%d, %d) %d줄%s", batch.start_offset, batch.end_offset,
                     result.inserted, " (이미 저장됨)" if result.duplicate else "")
            self.state.offset = result.committed_offset
        self._save()
        return self.state.offset < size

    # ---- 루프 ---------------------------------------------------------------

    def run(self) -> None:
        retry = self.config.retry
        backoff = retry.initial_backoff_sec
        while not self.stop_event.is_set():
            self.wakeup.clear()
            try:
                more = self.tick()
                backoff = retry.initial_backoff_sec
            except SendError as e:
                log.warning("전송 실패, %.1f초 후 재시도: %s", backoff, e)
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, retry.max_backoff_sec)
                continue
            except OSError as e:
                log.warning("파일 읽기 실패, 다음 주기에 재시도: %s", e)
                more = False
            if not more:
                self.wakeup.wait(self.config.poll_interval_sec)
