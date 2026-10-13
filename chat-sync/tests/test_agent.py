"""클라이언트 Agent 와 서버를 붙여서 시나리오별로 검증."""

from __future__ import annotations

import os

import httpx
import pytest

from chatsync.client.agent import Agent
from chatsync.client.config import ClientConfig
from chatsync.client.sender import SendError, Sender
from chatsync.client.state import load_state

from conftest import fetch_messages


def make_agent(tmp_path, http, state_name="state.json") -> Agent:
    config = ClientConfig(
        client_id="pc-01",
        source_file=tmp_path / "chat.txt",
        state_file=tmp_path / state_name,
        max_batch_bytes=1024,
        server={"url": "http://testserver", "api_key": "secret-1"},
    )
    sender = Sender("http://testserver", "pc-01", "secret-1", 5)
    sender._client = http  # FastAPI TestClient (httpx.Client 하위 클래스)
    return Agent(config, sender)


def drain(agent: Agent) -> None:
    while agent.tick():
        pass


def append(path, text: str) -> None:
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(text)


def contents(engine):
    return [c for _, c in fetch_messages(engine)]


def test_incremental_send(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    assert agent.tick() is False  # 파일 없음

    append(src, "1\n2\n3")
    drain(agent)
    assert contents(engine) == ["1", "2"]

    append(src, "\n4\n")
    drain(agent)
    assert contents(engine) == ["1", "2", "3", "4"]
    assert load_state(tmp_path / "state.json").offset == os.path.getsize(src)


def test_large_backlog_sent_in_batches(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    append(src, "".join(f"message {i:05d}\n" for i in range(1000)))
    drain(make_agent(tmp_path, http))
    assert contents(engine) == [f"message {i:05d}" for i in range(1000)]


def test_restart_resumes_from_state(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    append(src, "a\nb\n")
    drain(make_agent(tmp_path, http))
    append(src, "c\n")
    drain(make_agent(tmp_path, http))  # 재시작
    assert contents(engine) == ["a", "b", "c"]


def test_lost_state_recovers_from_server(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    append(src, "a\nb\n")
    drain(make_agent(tmp_path, http))
    os.remove(tmp_path / "state.json")
    append(src, "c\n")
    drain(make_agent(tmp_path, http))
    assert contents(engine) == ["a", "b", "c"]  # 중복 없음


def test_truncate_starts_new_stream(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    append(src, "old 1\nold 2\n")
    drain(agent)
    first_stream = agent.state.stream_id
    with open(src, "w") as f:
        f.write("new\n")
    drain(agent)
    assert agent.state.stream_id != first_stream
    assert sorted(contents(engine)) == ["new", "old 1", "old 2"]


def test_rotation_starts_new_stream(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    append(src, "day1\n")
    drain(agent)
    os.replace(src, tmp_path / "chat-day1.txt")
    append(src, "day2 is longer\n")
    drain(agent)
    assert sorted(contents(engine)) == ["day1", "day2 is longer"]


def test_server_down_keeps_offset(tmp_path, http, engine):
    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    append(src, "a\n")
    drain(agent)

    def fail(request):
        raise httpx.ConnectError("down", request=request)

    real = agent.sender._client
    agent.sender._client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(fail))
    append(src, "b\n")
    with pytest.raises(SendError):
        agent.tick()
    assert agent.state.offset == 2  # 전송 실패 → 위치 그대로

    agent.sender._client = real
    append(src, "c\n")
    drain(agent)
    assert contents(engine) == ["a", "b", "c"]


def test_response_lost_does_not_duplicate(tmp_path, http, engine):
    """서버는 저장했는데 응답이 유실된 경우: 재전송해도 중복 저장 안 됨."""
    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    append(src, "a\n")
    drain(agent)

    real_send = agent.sender.send

    def send_then_fail(req):
        real_send(req)
        raise SendError("timeout after server committed")

    agent.sender.send = send_then_fail
    append(src, "b\n")
    with pytest.raises(SendError):
        agent.tick()
    agent.sender.send = real_send
    append(src, "c\n")
    drain(agent)
    assert contents(engine) == ["a", "b", "c"]


def test_server_db_reset_triggers_resend(tmp_path, http, engine):
    """서버 기록이 사라진 경우(409) 서버가 아는 위치부터 다시 보낸다."""
    from chatsync.server.db import Base

    src = tmp_path / "chat.txt"
    agent = make_agent(tmp_path, http)
    append(src, "a\nb\n")
    drain(agent)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    append(src, "c\n")
    drain(agent)
    assert contents(engine) == ["a", "b", "c"]
