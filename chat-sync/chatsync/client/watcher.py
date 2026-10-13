"""파일 변경 이벤트(watchdog) → threading.Event 로 알림. 폴링과 함께 쓰는 보조 수단."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class FileWatcher:
    def __init__(self, path: Path, wakeup: threading.Event) -> None:
        self._path = os.path.normcase(os.path.abspath(path))
        self._wakeup = wakeup
        self._observer = None

    def start(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("watchdog 미설치: 폴링만 사용합니다")
            return

        target, wakeup = self._path, self._wakeup

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):  # noqa: ANN001
                paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
                if any(p and os.path.normcase(os.path.abspath(p)) == target for p in paths):
                    wakeup.set()

        directory = os.path.dirname(self._path)
        try:
            observer = Observer()
            observer.schedule(Handler(), directory, recursive=False)
            observer.start()
        except (OSError, RuntimeError) as e:
            log.warning("파일 이벤트 감시 시작 실패, 폴링만 사용합니다: %s", e)
            return
        self._observer = observer
        log.info("파일 이벤트 감시 시작: %s", directory)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
