from __future__ import annotations

import os

from chatsync.client.tailer import read_batch


def write(path, data: bytes, mode="wb"):
    with open(path, mode) as f:
        f.write(data)


def texts(batch):
    return [ln.text for ln in batch.lines]


def test_reads_only_complete_lines(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, b"hello\nworld\npartial")
    _, size, batch = read_batch(p, 0, 1024, "utf-8")
    assert size == 19
    assert texts(batch) == ["hello", "world"]
    assert [ln.offset for ln in batch.lines] == [0, 6]
    assert (batch.start_offset, batch.end_offset) == (0, 12)

    # 쓰는 중인 줄만 남았으면 아무것도 안 보냄
    _, _, batch = read_batch(p, 12, 1024, "utf-8")
    assert batch is None

    write(p, b" done\n", "ab")
    _, _, batch = read_batch(p, 12, 1024, "utf-8")
    assert texts(batch) == ["partial done"]
    assert batch.end_offset == os.path.getsize(p)


def test_nothing_new(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, b"a\n")
    assert read_batch(p, 2, 1024, "utf-8")[2] is None


def test_crlf_bom_and_korean(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, "﻿[10:00] 철수: 안녕\r\n[10:01] 영희: 반가워\r\n".encode("utf-8"))
    _, _, batch = read_batch(p, 0, 1024, "utf-8")
    assert texts(batch) == ["[10:00] 철수: 안녕", "[10:01] 영희: 반가워"]


def test_cp949(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, "안녕하세요\n".encode("cp949"))
    _, _, batch = read_batch(p, 0, 1024, "cp949")
    assert texts(batch) == ["안녕하세요"]


def test_batch_limit_splits_on_line_boundary(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, b"".join(b"line%03d\n" % i for i in range(200)))  # 8 bytes/line
    _, _, batch = read_batch(p, 0, 1024 + 4, "utf-8")  # 128줄 + 4바이트
    assert len(batch.lines) == 128
    assert batch.end_offset == 1024
    _, _, nxt = read_batch(p, batch.end_offset, 1028, "utf-8")
    assert nxt.lines[0].text == "line128"


def test_line_longer_than_batch(tmp_path):
    p = tmp_path / "chat.txt"
    long_line = b"x" * 5000
    write(p, long_line + b"\nnext\n")
    _, _, batch = read_batch(p, 0, 1024, "utf-8")
    assert texts(batch) == ["x" * 5000]
    assert batch.end_offset == 5001


def test_long_partial_line_waits(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, b"x" * 5000)
    assert read_batch(p, 0, 1024, "utf-8")[2] is None


def test_identity_changes_when_file_replaced(tmp_path):
    p = tmp_path / "chat.txt"
    write(p, b"a\n")
    ident1, _, _ = read_batch(p, 0, 1024, "utf-8")
    keep = tmp_path / "old.txt"
    os.replace(p, keep)  # 로테이션 흉내 (기존 파일 보존 → inode 재사용 방지)
    write(p, b"b\n")
    ident2, _, _ = read_batch(p, 0, 1024, "utf-8")
    assert ident1 != ident2
