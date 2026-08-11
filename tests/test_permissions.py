"""权限门测试"""

from src.core.permissions import PermissionPolicy, get_permission_policy


class TestPermissionPolicy:
    def test_cognitive_allow(self):
        """认知工具默认 allow"""
        p = PermissionPolicy()
        d = p.evaluate("search_memory")
        assert d.allowed and d.verdict == "allow"

    def test_meta_allow(self):
        """finalize 内部决策 allow"""
        p = PermissionPolicy()
        assert p.evaluate("finalize").allowed

    def test_device_default_allow(self):
        """设备动作默认 allow（保留现有决策链路）"""
        p = PermissionPolicy()
        d = p.evaluate("light_on")
        assert d.category == "device"
        assert d.allowed

    def test_emergency_stop_always_allowed(self):
        """emergency_stop 永远放行（即使 override 为 deny）"""
        p = PermissionPolicy()
        p.deny("emergency_stop")
        assert p.evaluate("emergency_stop").allowed

    def test_outbound_deny_by_default(self, monkeypatch):
        """出站默认 deny，RAK_OUTBOUND=1 才放行"""
        monkeypatch.delenv("RAK_OUTBOUND", raising=False)
        p = PermissionPolicy()
        assert p.evaluate("publish_action").verdict == "deny"
        monkeypatch.setenv("RAK_OUTBOUND", "1")
        assert p.evaluate("publish_action").allowed

    def test_stress_upgrades_device_to_ask(self):
        """高压力 → 设备动作升级 ask（单调收紧）"""
        p = PermissionPolicy()
        d = p.evaluate("light_on", context={"stress": 0.8})
        assert d.verdict == "ask"

    def test_config_override(self):
        """配置可把设备动作设为 ask"""
        p = PermissionPolicy({"actions": {"lock_open": "ask"}})
        assert p.evaluate("lock_open").verdict == "ask"

    def test_unknown_action_defaults_device(self):
        """未知动作归为 device 类"""
        p = PermissionPolicy()
        assert p.categorize("some_new_action") == "device"

    def test_singleton(self):
        """单例复用"""
        assert get_permission_policy() is get_permission_policy()
