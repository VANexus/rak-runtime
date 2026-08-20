"""外部 MCP stub 服务器（测试/基准复用）— 离线、零网络、纯 stdio。

被三个消费者引用，工具集必须满足它们的并集契约：
- benchmarks/external_tools_suite.py           要求 square（返回 36 for n=6）
- tests/test_workflow.py                       要求 square（材质化 mcp_stub_square）
- tests/test_mcp_client.py                     要求 square("n":7)=="49" 且
                                               hello({"name": x}) 含 x
- tests/test_agent_loop.py                     要求 square + hello 均被材质化

配置（任一消费者）：
  RAK_MCP_SERVERS=[{"name":"stub","command":<python>,"args":["-u","/tmp/rak_stub_mcp.py"]}]
把本仓库文件复制到 /tmp 以满足硬编码路径：
  cp tools_stubs/rak_stub_mcp.py /tmp/rak_stub_mcp.py
"""

from fastmcp import FastMCP

mcp = FastMCP("stub")


@mcp.tool
def hello(name: str) -> str:
    """返回问候语（外部 stub 工具，验证外部 MCP 链路参数透传）。"""
    return f"你好，{name}"


@mcp.tool
def square(n: int) -> int:
    """返回 n 的平方（外部 stub 工具，验证外部 MCP 链路返回值）。"""
    return n * n


if __name__ == "__main__":
    mcp.run(transport="stdio")
