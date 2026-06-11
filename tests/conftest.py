"""
pytest 共享 fixtures — rak-runtime 测试基础设施

提供 mock 的 LLM 客户端、记忆引擎等，避免测试依赖外部服务。
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_dir():
    """提供临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_llm_client():
    """Mock 的 Anthropic LLM 客户端"""
    client = MagicMock()

    def _create_response(text):
        block = MagicMock()
        block.text = text
        response = MagicMock()
        response.content = [block]
        return response

    # 默认返回一个简单动作
    client.messages.create.return_value = _create_response(
        json.dumps({"action": "nod", "confidence": 0.9, "reason": "test"})
    )
    return client


@pytest.fixture
def mock_memory_engine():
    """Mock 的记忆引擎"""
    engine = MagicMock()
    engine.recall.return_value = []
    engine.remember.return_value = True
    engine.get_stats.return_value = {
        "working_count": 0,
        "short_term_count": 0,
        "long_term_count": 0,
    }
    return engine


@pytest.fixture
def sample_available_actions():
    """标准可用动作列表"""
    return [
        "shake_head", "wave_hand", "lock_open", "lock_close",
        "move_forward", "move_back", "turn_left", "turn_right",
        "dance", "nod", "light_on", "light_off",
        "emergency_stop", "idle",
    ]


@pytest.fixture
def mock_request(sample_available_actions):
    """Mock 的 gRPC ExecuteRequest"""
    request = MagicMock()
    request.trace_id = "test-trace-001"
    request.version = "v0"
    request.action = ""
    request.state = '{"device_id": "test-device", "online": true}'
    request.available_actions = sample_available_actions
    request.params_json = "{}"
    return request
