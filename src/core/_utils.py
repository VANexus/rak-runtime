"""
共享工具模块 — 跨模块复用的通用函数

提供：
- atomic_write_json: 原子性 JSON 持久化（写临时文件 + rename）
- safe_json_parse: 多层 fallback 的 JSON 解析
- time_diff_minutes: HH:MM 时间差计算（分钟）
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def atomic_write_json(path: str, data: Any) -> bool:
    """
    原子性 JSON 写入。

    写入临时文件后 rename，避免断电/崩溃导致文件损坏。
    返回是否成功。
    """
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 写入同目录临时文件
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            suffix=".tmp",
            prefix=f".{path.name}.",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
            return True
        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning("原子写入失败 %s: %s", path, e)
        return False


def safe_json_parse(text: str) -> Optional[Any]:
    """
    多层 fallback 的 JSON 解析。

    处理 LLM 常见输出格式：
    1. 直接解析
    2. 剥离 ```json ... ``` 代码块
    3. 查找第一个 { 或 [ 到最后一个 } 或 ]
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 层 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 层 2: 剥离 markdown 代码块
    if "```" in text:
        try:
            # 提取 ``` 后面的内容
            parts = text.split("```")
            if len(parts) >= 3:
                block = parts[1]
                if block.startswith("json"):
                    block = block[4:]
                return json.loads(block.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # 层 3: 查找 JSON 对象/数组边界
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    return None


def time_diff_minutes(time_str: str) -> float:
    """
    计算 HH:MM 时间字符串与当前时间的差值（分钟）。

    用于用户行为模式匹配和主动预测。
    """
    from datetime import datetime
    try:
        now = datetime.now()
        h, m = map(int, time_str.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = (now - target).total_seconds() / 60
        return diff
    except (ValueError, AttributeError):
        return 0.0
