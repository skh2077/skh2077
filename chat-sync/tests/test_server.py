from __future__ import annotations

from chatsync.protocol import API_KEY_HEADER, CLIENT_ID_HEADER, INGEST_PATH, STREAM_LOOKUP_PATH

from conftest import fetch_messages


def body(start, end, lines, stream="s1", client="pc-01"):
    return {
        "client_id": client,
        "stream_id": stream,
        "source_path": "/chat.txt",
        "file_identity": "1:2",
        "start_offset": start,
        "end_offset": end,
        "lines": [{"offset": o, "text": t} for o, t in lines],
    }


def test_ingest_and_duplicate(http, engine):
    r = http.post(INGEST_PATH, json=body(0, 12, [(0, "hello"), (6, "world")]))
    assert r.status_code == 200, r.text
    assert r.json() == {"committed_offset": 12, "inserted": 2, "duplicate": False}

    # 응답 유실 후 같은 요청 재전송 → 저장 안 함
    r = http.post(INGEST_PATH, json=body(0, 12, [(0, "hello"), (6, "world")]))
    assert r.json() == {"committed_offset": 12, "inserted": 0, "duplicate": True}
    assert fetch_messages(engine) == [(0, "hello"), (6, "world")]


def test_partial_overlap_stores_only_new_lines(http, engine):
    http.post(INGEST_PATH, json=body(0, 6, [(0, "hello")]))
    # 재시도 때 파일이 더 자라서 더 큰 묶음으로 같은 시작점부터 보낸 경우
    r = http.post(INGEST_PATH, json=body(0, 18, [(0, "hello"), (6, "world"), (12, "again")]))
    assert r.json()["inserted"] == 2
    assert fetch_messages(engine) == [(0, "hello"), (6, "world"), (12, "again")]


def test_gap_returns_409(http):
    r = http.post(INGEST_PATH, json=body(6, 12, [(6, "world")]))
    assert r.status_code == 409
    assert r.json()["committed_offset"] == 0


def test_streams_are_independent(http, engine):
    http.post(INGEST_PATH, json=body(0, 2, [(0, "a")], stream="s1"))
    r = http.post(INGEST_PATH, json=body(0, 2, [(0, "b")], stream="s2"))
    assert r.json()["inserted"] == 1
    assert len(fetch_messages(engine)) == 2


def test_auth(http):
    r = http.post(INGEST_PATH, json=body(0, 2, [(0, "a")]), headers={API_KEY_HEADER: "wrong"})
    assert r.status_code == 401
    # 다른 클라이언트 이름으로 저장 시도
    r = http.post(INGEST_PATH, json=body(0, 2, [(0, "a")], client="pc-02"))
    assert r.status_code == 403
    r = http.post(INGEST_PATH, json=body(0, 2, [(0, "a")], client="pc-02"),
                  headers={CLIENT_ID_HEADER: "pc-02", API_KEY_HEADER: "secret-2"})
    assert r.status_code == 200


def test_invalid_range_rejected(http):
    r = http.post(INGEST_PATH, json=body(5, 5, []))
    assert r.status_code == 422
    r = http.post(INGEST_PATH, json=body(0, 5, [(9, "out of range")]))
    assert r.status_code == 422


def test_lookup(http):
    assert http.get(STREAM_LOOKUP_PATH, params={"file_identity": "1:2"}).status_code == 404
    http.post(INGEST_PATH, json=body(0, 2, [(0, "a")]))
    r = http.get(STREAM_LOOKUP_PATH, params={"file_identity": "1:2"})
    assert r.json() == {"stream_id": "s1", "committed_offset": 2}
