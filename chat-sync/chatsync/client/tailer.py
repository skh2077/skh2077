"""오프셋 기준으로 파일의 새로 추가된 '완성된 줄'만 읽는다.

파일 핸들을 계속 열어두지 않는다(매번 열고 닫음). Windows 에서 핸들을 잡고 있으면
채팅 프로그램이 파일을 이름변경/삭제하지 못할 수 있기 때문.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from chatsync.protocol import Line

_BOM_UTF8 = b"\xef\xbb\xbf"


def file_identity(st: os.stat_result) -> str:
    """파일 동일성 식별자. 이름이 같아도 새로 만들어진 파일이면 값이 달라진다."""
    return f"{st.st_dev}:{st.st_ino}"


@dataclass
class Batch:
    file_identity: str
    start_offset: int
    end_offset: int
    lines: list[Line]


def read_batch(path: Path, offset: int, max_bytes: int, encoding: str) -> tuple[str, int, Batch | None]:
    """``offset`` 부터 완성된 줄(개행으로 끝나는 줄)을 최대 ``max_bytes`` 만큼 읽는다.

    반환: (file_identity, 현재 파일 크기, Batch 또는 None)
    마지막 줄이 아직 개행 없이 쓰이는 중이면 그 줄은 포함하지 않는다.
    """
    with open(path, "rb") as f:
        st = os.fstat(f.fileno())
        ident, size = file_identity(st), st.st_size
        if size <= offset:
            return ident, size, None

        f.seek(offset)
        buf = f.read(max_bytes)
        end = buf.rfind(b"\n")
        if end < 0:
            if offset + len(buf) >= size:
                return ident, size, None  # 쓰는 중인 줄만 있음
            # 한 줄이 max_bytes 보다 김 → 그 줄 끝까지 이어서 읽는다
            chunks = [buf]
            while True:
                more = f.read(max_bytes)
                if not more:
                    return ident, size, None
                i = more.find(b"\n")
                if i >= 0:
                    chunks.append(more[: i + 1])
                    break
                chunks.append(more)
            buf = b"".join(chunks)
        else:
            buf = buf[: end + 1]

    lines: list[Line] = []
    pos = offset
    for raw in buf.split(b"\n")[:-1]:
        line_offset = pos
        pos += len(raw) + 1
        if line_offset == 0 and raw.startswith(_BOM_UTF8):
            raw = raw[len(_BOM_UTF8):]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        lines.append(Line(offset=line_offset, text=raw.decode(encoding, errors="replace")))
    return ident, size, Batch(file_identity=ident, start_offset=offset, end_offset=pos, lines=lines)
