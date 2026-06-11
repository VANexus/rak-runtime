"""共享工具测试"""

import json
import os
import tempfile

import pytest

from src.core._utils import atomic_write_json, safe_json_parse


class TestAtomicWriteJson:
    """原子性 JSON 写入测试"""

    def test_basic_write(self, tmp_dir):
        """基本写入和读取"""
        path = os.path.join(tmp_dir, "test.json")
        data = {"key": "value", "number": 42}
        assert atomic_write_json(path, data) is True

        with open(path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_creates_parent_dirs(self, tmp_dir):
        """应自动创建父目录"""
        path = os.path.join(tmp_dir, "sub", "dir", "test.json")
        assert atomic_write_json(path, {"a": 1}) is True
        assert os.path.exists(path)

    def test_overwrites_existing(self, tmp_dir):
        """应覆盖已有文件"""
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"v": 1})
        atomic_write_json(path, {"v": 2})

        with open(path) as f:
            assert json.load(f) == {"v": 2}

    def test_no_corrupt_file_on_error(self, tmp_dir):
        """写入失败时不应留下损坏的文件"""
        path = os.path.join(tmp_dir, "test.json")
        atomic_write_json(path, {"ok": True})

        # 写入一个不可序列化的对象
        result = atomic_write_json(path, object())
        # 即使失败，原文件也应保持完整
        if not result:
            with open(path) as f:
                assert json.load(f) == {"ok": True}


class TestSafeJsonParse:
    """安全 JSON 解析测试"""

    def test_direct_json(self):
        """直接 JSON 应正常解析"""
        assert safe_json_parse('{"a": 1}') == {"a": 1}

    def test_markdown_code_block(self):
        """应剥离 markdown 代码块"""
        text = '```json\n{"action": "nod"}\n```'
        assert safe_json_parse(text) == {"action": "nod"}

    def test_markdown_without_json_tag(self):
        """无 json 标签的代码块也应解析"""
        text = '```\n{"action": "nod"}\n```'
        assert safe_json_parse(text) == {"action": "nod"}

    def test_embedded_json_object(self):
        """应从文字中提取 JSON 对象"""
        text = 'Here is the result: {"action": "wave"} and more text'
        assert safe_json_parse(text) == {"action": "wave"}

    def test_embedded_json_array(self):
        """应从文字中提取 JSON 数组"""
        text = 'Actions: [{"a": 1}, {"a": 2}] done'
        assert safe_json_parse(text) == [{"a": 1}, {"a": 2}]

    def test_empty_string(self):
        """空字符串应返回 None"""
        assert safe_json_parse("") is None
        assert safe_json_parse(None) is None

    def test_invalid_json(self):
        """无法解析的应返回 None"""
        assert safe_json_parse("not json at all") is None
