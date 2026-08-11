"""
Rak 大脑 CLI — 交互式 TUI（Rich）。

像 Claude Code / openclaw 一样可交互使用：输入指令/问题，看大脑思考（工具轨迹）、
决策（动作+回复）、认知状态（情绪/需求）实时更新。可选端到端设备动作执行。

用法：
    python -m src.cli.main                 # 交互式 REPL（默认）
    python -m src.cli.main ask "把灯打开"   # 一次性决策
    python -m src.cli.main status           # 认知系统状态

REPL 斜杠命令：
    /status /emotion /needs /memory <q> /reflect /self /sessions /clear /help /exit
"""

import argparse
import json
import os
import sys
import time
from types import SimpleNamespace

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

console = Console()

AVAILABLE_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "dance", "nod", "light_on", "light_off",
    "emergency_stop", "idle",
]

BANNER = """
[bold cyan]╔══════════════════════════════════════════════╗
║        Rak 具身智能大脑 · 交互终端              ║
╚══════════════════════════════════════════════╝[/]
输入指令或问题开始对话。输入 [bold]/help[/] 查看命令，[/]Ctrl+C[/] 退出。
"""


def run_brain(text: str, trace_id: str = "") -> dict:
    """把用户输入交给大脑决策（与 gRPC/A2A 同路径）"""
    from src.core.decision_engine import DecisionEngine
    engine = DecisionEngine()
    req = SimpleNamespace(
        version="v0",
        trace_id=trace_id or f"cli-{int(time.time() * 1000)}",
        source="cli:user", target="runtime:default",
        action="", state=text, available_actions=AVAILABLE_ACTIONS,
        params_json="{}",
    )
    return engine.decide(req)


def render_decision(text: str, result: dict) -> str:
    """把决策渲染为富文本（测试友好，返回字符串）"""
    status = result.get("status", "error")
    action = result.get("action", "")
    answer = result.get("answer", "")

    lines = []
    if answer:
        lines.append(f"[bold green]Rak：[/]{answer}\n")

    lines.append(f"[dim]状态[/] {status}  [dim]动作[/] {action or '—'}")

    trace = result.get("trace")
    if trace:
        lines.append(f"[dim]工具轨迹[/] {' → '.join(str(t) for t in trace)}")

    reasoning = result.get("reasoning")
    if reasoning:
        lines.append(f"[dim]推理[/] {reasoning}")

    conf = result.get("confidence_hint")
    if conf:
        lines.append(f"[dim]{conf}[/]")

    if status == "confirm":
        lines.append(f"[yellow]需要确认：{result.get('message', '')}[/]")
    if status == "error":
        lines.append(f"[red]错误 {result.get('error_code', '')}: {result.get('error_message', '')}[/]")

    return "\n".join(lines)


def _cognitive_status() -> str:
    """认知状态摘要（情绪 + 需求 + 心跳）"""
    from src.core import decision_engine as de
    parts = []
    emo = de._get_emotion_engine()
    if emo:
        parts.append(f"情绪：{emo.state.describe()}")
    need = de._get_need_engine()
    if need:
        need.update()
        parts.append(f"需求：{need.needs.describe()}")
    inner = de._get_inner_loop()
    if inner:
        stats = inner.get_stats()
        parts.append(f"心跳：事件 {stats.get('total_events', 0)} · 想法 {stats.get('thoughts_count', 0)}")
    return "\n".join(parts) if parts else "（认知模块未初始化）"


def _status_table() -> Table:
    from src.core import decision_engine as de
    t = Table(title="认知系统状态")
    t.add_column("模块")
    t.add_column("状态")

    def row(name, obj, extra=""):
        t.add_row(name, "✓" if obj else "✗", extra)

    row("记忆引擎", de._get_memory_engine(), _mem_summary())
    row("世界模型", de._get_world_model())
    row("语义缓存", de._get_semantic_cache())
    row("元认知", de._get_meta_cognition())
    row("用户模型", de._get_user_model())
    row("活体图谱", de._get_living_graph())
    row("情绪引擎", de._get_emotion_engine())
    row("需求引擎", de._get_need_engine())
    row("内心循环", de._get_inner_loop())
    row("自我模型", de._get_self_model())
    return t


def _mem_summary() -> str:
    from src.core import decision_engine as de
    mem = de._get_memory_engine()
    if mem is None:
        return ""
    s = mem.stats()
    return f"长{ s.get('long_term_memory',0) } 短{ s.get('short_term_memory',0) } 访{ s.get('total_queries',0) }"


def handle_message(text: str) -> None:
    """处理一条用户消息：决策 + 渲染 + 可选设备动作执行"""
    with console.status("[cyan]Rak 正在思考..."):
        result = run_brain(text)
    console.print(Panel(
        render_decision(text, result),
        title="[bold cyan]Rak[/]", border_style="cyan",
    ))
    # 认知状态条
    status = _cognitive_status()
    if status:
        console.print(Text.from_markup(f"[dim]{status}[/]"), style="dim")
    # 端到端设备动作执行（RAK_OUTBOUND=1）
    _maybe_dispatch(result)


def _maybe_dispatch(result: dict) -> None:
    """若决策为设备动作且出站启用，实际派发（端到端设备动作执行链路）"""
    action = result.get("action", "")
    if action in ("", "idle") or result.get("status") != "ok":
        return
    if os.getenv("RAK_OUTBOUND", "0") != "1":
        console.print(f"[dim]（动作 {action}：RAK_OUTBOUND=1 才真实派发到设备）[/]")
        return
    from src.core.outbound import get_outbound
    ob = get_outbound()
    ok = ob.publish_action("default-device", action, result.get("params_json", "{}"))
    console.print(f"[{'green' if ok else 'red'}]{'✓ 已派发' if ok else '✗ 派发失败'} 动作 {action}[/]")


def handle_slash(cmd: str) -> bool:
    """处理斜杠命令，返回是否应退出"""
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name in ("/exit", "/quit", "/q"):
        console.print("[dim]再见 👋[/]")
        return True
    elif name == "/clear":
        console.clear()
    elif name == "/help":
        _help()
    elif name == "/status":
        console.print(_status_table())
        console.print(_cognitive_status())
    elif name == "/emotion":
        from src.core import decision_engine as de
        emo = de._get_emotion_engine()
        console.print(json.dumps(emo.get_stats(), ensure_ascii=False, indent=2) if emo else "未初始化")
    elif name == "/needs":
        from src.core import decision_engine as de
        need = de._get_need_engine()
        if need:
            need.update()
            console.print(need.needs.to_dict())
    elif name == "/memory":
        from src.core import decision_engine as de
        mem = de._get_memory_engine()
        if mem and arg:
            results = mem.recall(arg, top_k=5)
            for r in results:
                console.print(f"[dim][{r.entry.memory_type}]({r.score:.2f})[/] {r.entry.content[:100]}")
        else:
            console.print("用法：/memory <查询词>")
    elif name == "/reflect":
        from src.core import decision_engine as de
        meta = de._get_meta_cognition()
        console.print(json.dumps(meta.reflect() if meta else {}, ensure_ascii=False, indent=2))
    elif name == "/self":
        from src.core import decision_engine as de
        sm = de._get_self_model()
        console.print(sm.who_am_i() if sm else "未初始化")
    elif name == "/sessions":
        from src.core.agent_session import get_session_store
        for s in get_session_store().list_recent(10):
            console.print(f"[dim]{s['session_id']}[/] {s['status']} action={s['action']} tools={s['tools_used']}")
    elif name == "/device":
        console.print("设备 registry（开发中）— 后续接入 device_registry")
    else:
        console.print(f"[red]未知命令 {name}，/help 查看[/]")
    return False


def _help():
    commands = [
        ("普通输入", "让大脑决策：返回动作 + 自然回复 + 工具轨迹 + 认知状态"),
        ("/status", "认知系统状态总览"),
        ("/emotion", "当前六维情绪"),
        ("/needs", "内部需求向量"),
        ("/memory <q>", "检索长期记忆"),
        ("/reflect", "元认知自我反思"),
        ("/self", "自我认知（我是谁）"),
        ("/sessions", "最近的 agent 会话"),
        ("/clear", "清屏"),
        ("/exit", "退出"),
    ]
    t = Table(title="命令帮助")
    t.add_column("命令")
    t.add_column("说明")
    for c, d in commands:
        t.add_row(c, d)
    console.print(t)


def repl() -> None:
    console.print(Panel(BANNER, border_style="cyan"))
    console.print("[dim]启动认知模块...[/]")
    from src.core import decision_engine as de
    de.DecisionEngine()
    console.print(f"[green]✓ 就绪[/] 可用动作：{', '.join(AVAILABLE_ACTIONS[:6])}...\n")
    while True:
        try:
            text = Prompt.ask("[bold cyan]Rak[/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见 👋[/]")
            break
        text = (text or "").strip()
        if not text:
            continue
        if text.startswith("/"):
            if handle_slash(text):
                break
        else:
            handle_message(text)


def cmd_ask(text: str) -> None:
    result = run_brain(text)
    console.print(render_decision(text, result))
    _maybe_dispatch(result)


def cmd_status() -> None:
    from src.core import decision_engine as de
    de.DecisionEngine()
    console.print(_status_table())


def main() -> None:
    parser = argparse.ArgumentParser(description="Rak 具身智能大脑 CLI")
    sub = parser.add_subparsers(dest="command")
    p_ask = sub.add_parser("ask", help="一次性决策")
    p_ask.add_argument("text", help="指令或问题")
    sub.add_parser("status", help="认知系统状态")
    args = parser.parse_args()

    if args.command == "ask":
        cmd_ask(args.text)
    elif args.command == "status":
        cmd_status()
    else:
        repl()


if __name__ == "__main__":
    main()
