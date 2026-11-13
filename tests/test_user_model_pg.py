"""用户模型持久化测试：本地 JSON + PostgreSQL 多设备同步（P2-1）"""

import json

import pytest

from src.core.user_model import UserModel
from src.core.user_model_pg import UserModelPostgresBackend


class FakePg:
    """可控的 PG 后端替身"""

    def __init__(self, available=True, data=None):
        self.available = available
        self._data = data
        self.save_calls = []

    def load(self):
        return self._data

    def save(self, data, last_seen=0.0):
        self.save_calls.append((data, last_seen))


def _make_model(tmp_path, **kwargs):
    return UserModel(str(tmp_path / "user_model.json"), **kwargs)


@pytest.fixture(autouse=True)
def _no_env_pg(monkeypatch):
    monkeypatch.delenv("RAG_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("RAK_USER_ID", raising=False)


class TestJsonPersistence:
    def test_roundtrip_with_corrections(self, tmp_path):
        """交互 + 纠正都应跨实例存活（纠正原先只存内存，重启即丢）"""
        m1 = _make_model(tmp_path)
        m1.record_interaction("打开灯", "light_on")
        m1.record_correction("把空调关了", "lock_open", "ac_off")
        assert m1._corrections

        m2 = _make_model(tmp_path)
        assert m2.profile.total_interactions == 2
        assert len(m2._corrections) == 1
        assert m2._corrections[0].correction == "ac_off"

    def test_backward_compat_old_json(self, tmp_path):
        """旧格式 JSON（无 user_id/corrections 字段）应正常加载"""
        path = tmp_path / "user_model.json"
        path.write_text(json.dumps({
            "profile": {"expertise_level": 0.8, "communication_style": "技术型"},
            "behavior": {"last_device": "light", "frequent_queries": [["打开灯", 3]]},
            "history": [],
        }), encoding="utf-8")

        m = UserModel(str(path))
        assert m.profile.expertise_level == 0.8
        assert m.profile.communication_style == "技术型"
        assert m._corrections == []


class TestPgSync:
    def test_pg_newer_wins(self, tmp_path):
        """PG 数据较新时应采用 PG（多设备：另一台设备刚同步过）"""
        pg = FakePg(available=True, data={
            "profile": {"last_seen": 200.0},
            "behavior": {},
            "history": [],
            "corrections": [],
        })
        path = tmp_path / "user_model.json"
        path.write_text(json.dumps({
            "profile": {"last_seen": 100.0}, "behavior": {}, "history": [],
        }), encoding="utf-8")

        m = UserModel(str(path), pg_backend=pg)
        assert m.profile.last_seen == 200.0

    def test_json_newer_wins(self, tmp_path):
        """本地 JSON 较新时应采用 JSON（设备离线积累的数据不被旧云端覆盖）"""
        pg = FakePg(available=True, data={
            "profile": {"last_seen": 100.0},
            "behavior": {},
            "history": [],
        })
        path = tmp_path / "user_model.json"
        path.write_text(json.dumps({
            "profile": {"last_seen": 300.0}, "behavior": {}, "history": [],
        }), encoding="utf-8")

        m = UserModel(str(path), pg_backend=pg)
        assert m.profile.last_seen == 300.0

    def test_unavailable_pg_falls_back_to_json(self, tmp_path):
        """PG 不可用时静默走 JSON，不抛异常"""
        pg = FakePg(available=False)
        m = _make_model(tmp_path, pg_backend=pg)
        m.record_interaction("打开灯", "light_on")
        assert m.profile.total_interactions == 1
        assert pg.save_calls == []

    def test_save_syncs_to_pg(self, tmp_path):
        """PG 可用时每次交互都应同步到 PG"""
        pg = FakePg(available=True)
        m = _make_model(tmp_path, pg_backend=pg, user_id="device-a")
        m.record_interaction("打开灯", "light_on")

        assert len(pg.save_calls) == 1
        data, last_seen = pg.save_calls[0]
        assert data["user_id"] == "device-a"
        assert data["profile"]["total_interactions"] == 1
        assert last_seen > 0


class TestUserModelPgBackend:
    def test_bad_dsn_degrades(self, monkeypatch):
        """连不上的 DSN 应标记不可用，load/save 不抛异常"""
        backend = UserModelPostgresBackend(
            "postgresql://nobody:nope@127.0.0.1:1/none", "default")
        assert not backend.available
        assert backend.load() is None
        backend.save({"profile": {}}, 1.0)  # 不应抛异常

    def test_env_user_id(self, monkeypatch, tmp_path):
        """RAK_USER_ID 应决定多设备身份"""
        monkeypatch.setenv("RAK_USER_ID", "living-room")
        m = _make_model(tmp_path)
        assert m._user_id == "living-room"
