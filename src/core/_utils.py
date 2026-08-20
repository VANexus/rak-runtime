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

# 加载项目本地 .env（gitignored）——RAK_LLM_* 显式配置优先于宿主机全局 ANTHROPIC_* 代理环境变量
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:  # 无 python-dotenv 时静默跳过，仍可用环境变量
    pass


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


def get_model() -> str:
    """当前 LLM 模型名。优先级：RAK_LLM_MODEL > ANTHROPIC_MODEL > 默认 mimo-v2.5-pro"""
    return os.getenv("RAK_LLM_MODEL") or os.getenv("ANTHROPIC_MODEL") or "mimo-v2.5-pro"


def resolve_llm_env() -> tuple:
    """
    解析 LLM 认证配置，返回 (key, base_url, auth_scheme)。

    优先级（显式项目配置 > 宿主机全局代理）：
    - RAK_LLM_API_KEY / RAK_LLM_BASE_URL / RAK_LLM_AUTH_SCHEME（项目 .env 或显式设置）
    - ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL（宿主机代理，如 127.0.0.1 网关）
    - LONGCAT_API_KEY（LongCat 官方 CLI 约定）→ 自动用 LongCat base + Bearer
    """
    key = (os.getenv("RAK_LLM_API_KEY")
           or os.getenv("ANTHROPIC_AUTH_TOKEN")
           or os.getenv("LONGCAT_API_KEY") or "")
    base = (os.getenv("RAK_LLM_BASE_URL")
            or os.getenv("ANTHROPIC_BASE_URL") or "")
    scheme = (os.getenv("RAK_LLM_AUTH_SCHEME")
              or os.getenv("ANTHROPIC_AUTH_SCHEME") or "")

    if not base:
        # 用了 LongCat key 且未显式指定 base → 默认 LongCat
        if (os.getenv("LONGCAT_API_KEY") or os.getenv("RAK_LLM_API_KEY")) \
                and not (os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("RAK_LLM_BASE_URL")):
            base = "https://api.longcat.chat/anthropic"
        else:
            base = "https://token-plan-cn.xiaomimimo.com/anthropic"

    if not scheme and "longcat" in base:
        scheme = "bearer"  # LongCat 只认 Authorization: Bearer
    if not scheme:
        scheme = "api_key"

    return key, base, scheme


def make_llm_client(timeout: float = 15.0):
    """
    创建 Anthropic 客户端（统一工厂）。

    支持两种鉴权方式（由 resolve_llm_env 决定）：
    - api_key：发 x-api-key 头（token-plan 代理）
    - bearer：发 Authorization: Bearer 头（LongCat 等代理）
    """
    import anthropic
    key, base, scheme = resolve_llm_env()
    kwargs = dict(base_url=base, timeout=timeout)
    if scheme == "bearer":
        kwargs["auth_token"] = key
    else:
        kwargs["api_key"] = key
    return anthropic.Anthropic(**kwargs)


def make_langchain_anthropic(model: str, timeout: float = 30.0, max_tokens: int = 512):
    """
    创建 langchain-anthropic 的 ChatAnthropic（agent 内核用）。

    langchain-anthropic 内部强制用 api_key 建底层 client，
    bearer 鉴权通过 default_headers 注入 Authorization 头实现。
    """
    from langchain_anthropic import ChatAnthropic
    key, base, scheme = resolve_llm_env()
    kwargs = dict(model=model, base_url=base, timeout=timeout, max_tokens=max_tokens)
    if scheme == "bearer":
        kwargs["default_headers"] = {"Authorization": f"Bearer {key}"}
    else:
        kwargs["api_key"] = key
    return ChatAnthropic(**kwargs)


def thinking_extra() -> dict:
    """
    LLM 调用的 thinking 参数。
    - RAK_THINKING=1 → 显式启用深思
    - 否则 → 不传 thinking 参数（省略）。注意：不能发 `{"type":"disabled"}`
      因为 LongCat-2.0 等模型会拒绝显式 disabled；省略则走模型默认。
    """
    if os.getenv("RAK_THINKING", "0") == "1":
        return {"thinking": {"type": "enabled"}}
    return {}
