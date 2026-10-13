"""전송 위치 상태 파일. 원자적 교체(os.replace)로 저장해 도중에 죽어도 깨지지 않는다."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SyncState:
    stream_id: str
    file_identity: str
    offset: int  # 서버 저장이 확인된 위치 (바이트)


def load_state(path: Path) -> SyncState | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SyncState(
            stream_id=str(data["stream_id"]),
            file_identity=str(data["file_identity"]),
            offset=int(data["offset"]),
        )
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError) as e:
        log.error("상태 파일이 손상되어 무시합니다 (%s): %s", path, e)
        return None


def save_state(path: Path, state: SyncState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
