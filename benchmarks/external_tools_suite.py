"""
外部 MCP 工具 benchmark 套件（G6/G19 固化）— 验证大脑在配置外部 MCP 服务器时
能物化并调用外部工具（LangGraph agent 可真调外部 MCP server）。

离线安全：用本地 stdio stub 服务器（/tmp/rak_stub_mcp.py），零网络。
经验证外部工具 mcp_stub_square 被物化且调用返回 36。
"""

import json
import logging
import sys

from src.harness.benchmark import BenchmarkTask, TaskSuite

logger = logging.getLogger(__name__)

_DESCRIPTION = (
    "外部 MCP 工具：配置 RAK_MCP_SERVERS 后，agent 内核应物化 mcp_stub_* 外部工具，"
    "且经 stdio 真调用 stub 服务器返回正确结果（G6/G19）"
)


def external_tools_runner(text: str) -> dict:
    """
    离线 runner：配置 stub stdio MCP 服务器 → _build_tools 物化外部工具 → 调用验证。
    返回与大脑决策同构的 dict（匹配由 expected 子串完成）。
    """
    import os
    import src.tools.mcp_client as mc
    # save/restore 全局状态，避免泄漏到同进程其它测试/套件
    saved_env = os.environ.get("RAK_MCP_SERVERS")
    saved_client = mc._client
    mc._client = None  # 重读 env（配置下面注入）
    cfg = [
        {"name": "stub", "command": sys.executable,
         "args": ["-u", "/tmp/rak_stub_mcp.py"]},
    ]
    os.environ["RAK_MCP_SERVERS"] = json.dumps(cfg)

    try:
        from src.core import agent_loop
        tools, _ = agent_loop._build_tools(["idle"], "")
        names = {getattr(t, "name", "?") for t in tools}
        if "mcp_stub_square" not in names:
            return {"status": "fail", "action": "idle",
                    "answer": "未物化外部工具 mcp_stub_square",
                    "tools": sorted(names)}
        sq = next(t for t in tools if getattr(t, "name", "") == "mcp_stub_square")
        out = sq.invoke({"kwargs_json": '{"n": 6}'})
        return {"status": "ok", "action": "external", "answer": str(out).strip(),
                "tools": sorted(names)}
    except Exception as e:
        return {"status": "fail", "action": "idle",
                "answer": f"外部工具调用异常: {e}", "tools": []}
    finally:
        # 恢复全局状态，防止污染同进程其它测试/套件
        mc._client = saved_client
        if saved_env is None:
            os.environ.pop("RAK_MCP_SERVERS", None)
        else:
            os.environ["RAK_MCP_SERVERS"] = saved_env


def build_suite() -> TaskSuite:
    """构建外部 MCP 工具套件。"""
    tasks = [
        BenchmarkTask(
            task_id="ext-01",
            description="配置外部 MCP 服务器后能物化并调用外部工具",
            input="调用外部 stub 工具的 square",
            expected="36",  # 期望 answer 子串命中
            category="external_tools",
            tags=["mcp", "external-tools"],
        ),
    ]
    return TaskSuite(
        name="external-tools-suite",
        tasks=tasks,
        description=_DESCRIPTION,
    )


if __name__ == "__main__":
    from src.harness.benchmark import run_suite, report
    result = run_suite(build_suite(), runner=external_tools_runner,
                       trace_prefix="ext")
    print(report(result))
