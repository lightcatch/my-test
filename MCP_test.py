from langchain_mcp_adapters.client import MultiServerMCPClient  
from langchain.agents import create_agent
import asyncio
from langchain_openai import ChatOpenAI
import config
import os
import time
from config11 import (
    DOUBAO_AVAILABLE_MODELS, DOUBAO_API_URL, DOUBAO_API_KEY,
    TEMPERATURE, MAX_TOKENS, SYSTEM_PROMPT_TEMPLATE, 
    XUNFEI_AVAILABLE_MODELS, XUNFEI_API_URL, XUNFEI_API_KEY,
    DEEPSEEK_AVAILABLE_MODELS, DEEPSEEK_API_URL, DEEPSEEK_API_KEY,
    play_music_function_desc, play_story_function_desc,
    GET_WEATHER_FUNCTION_DESC, get_time_function_desc,
    handle_exit_intent_function_desc,
    audio_function_desc,
    achievement_function_desc,
)
async def main():
    # 设置API基础URL
    os.environ["OPENAI_BASE_URL"] = config.DOUBAO_API_URL
    
    # 计时开始 - 总体耗时
    total_start_time = time.time()
    
    # 1. 创建客户端并连接到MCP服务
    print("正在初始化MCP客户端...")
    client_start_time = time.time()
    client = MultiServerMCPClient(  
        {
            "weather": {
                "transport": "streamable_http",
                "url": "http://127.0.0.1:8000/mcp",
            }
        }
    )
    print(f"客户端初始化耗时: {time.time() - client_start_time:.4f} 秒")
    
    # 2. 获取工具列表
    print("\n正在获取工具列表...")
    tools_start_time = time.time()
    try:
        tools = await client.get_tools()  
        tools_time = time.time() - tools_start_time
        print(f"获取工具列表耗时: {tools_time:.4f} 秒")
        print(f"成功获取 {len(tools)} 个工具")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
    except Exception as e:
        print(f"获取工具列表失败: {e}")
        print(f"获取工具列表耗时: {time.time() - tools_start_time:.4f} 秒")
        return
    
    # 3. 初始化模型
    print("\n正在初始化模型...")
    model_start_time = time.time()
    model = ChatOpenAI(
        model="doubao-seed-1-8-251228",
        api_key=config.DOUBAO_API_KEY,
        temperature=0.8,
        max_tokens=config.MAX_TOKENS,
        extra_body={
            "thinking": {"type":"disabled"}
        }
    )
    print(f"模型初始化耗时: {time.time() - model_start_time:.4f} 秒")
    
    # 4. 创建agent
    print("\n正在创建Agent...")
    agent_start_time = time.time()
    agent = create_agent(model, tools=tools)
    print(f"Agent创建耗时: {time.time() - agent_start_time:.4f} 秒")
    
    # 5. 调用agent获取天气信息
    print("\n正在调用Agent获取天气信息...")
    invoke_time = 0  # 初始化invoke_time变量
    try:
        while True:
            user_content = input("你想聊什么：")
            
            # 记录整个调用过程的开始时间
            invoke_start_time = time.time()
            
            # 记录工具调用开始时间
            tool_call_start_time = None
            
            weather_response = await agent.ainvoke(
                {"messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE},
                    {"role": "user", "content": user_content}
                ]}
            )
            
            # 计算整个调用过程的耗时
            invoke_time = time.time() - invoke_start_time
            print(f"\nAgent总调用耗时: {invoke_time:.4f} 秒")
            
            # 提取AI回复内容
            ai_message = weather_response['messages'][-1]
            ai_content = ai_message.content
            print(f"\nAI回复: {ai_content}\n")
            
            # 检查并显示工具调用详情
            tool_calls_found = False
            tool_call_time = 0
            
            for message in weather_response['messages']:
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    tool_calls_found = True
                    print("工具调用详情:")
                    
                    # 计算工具调用时间
                    if hasattr(message, 'response_metadata') and 'token_usage' in message.response_metadata:
                        # 尝试从token使用情况估算时间
                        completion_tokens = message.response_metadata['token_usage'].get('completion_tokens', 0)
                        # 假设每个token大约需要0.1秒处理（这是一个粗略估计）
                        estimated_tool_time = completion_tokens * 0.1
                        tool_call_time = max(tool_call_time, estimated_tool_time)
                    
                    for tool_call in message.tool_calls:
                        print(f"  - 工具名称: {tool_call['name']}")
                        print(f"  - 参数: {tool_call['args']}")
                        print(f"  - 调用ID: {tool_call['id']}")
            
            if tool_calls_found:
                print(f"\n工具调用耗时估算: {tool_call_time:.4f} 秒")
                print(f"其他处理耗时: {invoke_time - tool_call_time:.4f} 秒")
            else:
                print("本次回复未使用工具调用")
            
            # 重置下一次调用的计时起始点
            invoke_start_time = time.time()

    except Exception as e:
        print(f"Agent调用失败: {e}")
        if 'invoke_start_time' in locals():
            print(f"Agent调用耗时: {time.time() - invoke_start_time:.4f} 秒")
    
    # 总体耗时
    total_time = time.time() - total_start_time
    print(f"\n总耗时: {total_time:.4f} 秒")
    
    # 性能分析
    print("\n性能分析:")
    print(f"- MCP服务连接和工具获取: {tools_time:.4f} 秒")
    print(f"- LLM调用和Agent处理: {invoke_time:.4f} 秒")
    print(f"- 其他初始化操作: {total_time - tools_time - invoke_time:.4f} 秒")

if __name__ == "__main__":
    asyncio.run(main())