from mcp import Tool
from mcp.server.fastmcp import FastMCP

# 创建MCP服务器实例
mcp = FastMCP("Weather Service")

# 定义工具函数
@mcp.tool()
async def get_weather(location: str) -> str:
    """获取指定位置的天气信息。"""
    return f"{location}的天气是晴天"

# @mcp.tool()
# async def get_weather(location: str) -> str:
#     """获取指定位置的天气信息。"""
#     return f"{location}的天气是晴天"

if __name__ == "__main__":
    # 启动服务器，使用streamable-http传输
    mcp.run(transport="streamable-http")