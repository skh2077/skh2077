from __future__ import annotations

from chatsync.client.state import SyncState, load_state, save_state


def test_roundtrip(tmp_path):
    p = tmp_path / "sub" / "state.json"
    assert load_state(p) is None
    save_state(p, SyncState("s1", "1:2", 42))
    assert load_state(p) == SyncState("s1", "1:2", 42)
    save_state(p, SyncState("s1", "1:2", 100))
    assert load_state(p).offset == 100
    assert [f.name for f in p.parent.iterdir()] == ["state.json"]  # 임시파일 안 남음


def test_corrupt_state_is_ignored(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert load_state(p) is None
