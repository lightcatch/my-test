import datetime
import json
import time
from typing import Dict, List, Optional, Any, Tuple

import httpx
from openai import OpenAI
from openai.types.chat import ChatCompletionChunk

from config11 import (
    DOUBAO_AVAILABLE_MODELS, DOUBAO_API_URL, DOUBAO_API_KEY, SYSTEM_PROMPT_TEMPLATE1,
    Ali_API_KEY, Ali_API_URL,
    TEMPERATURE, MAX_TOKENS, SYSTEM_PROMPT_TEMPLATE,
    PILLOW_USER_PROMPT_TEMPLATE,
    XUNFEI_AVAILABLE_MODELS, XUNFEI_API_URL, XUNFEI_API_KEY,
    DEEPSEEK_AVAILABLE_MODELS, DEEPSEEK_API_URL, DEEPSEEK_API_KEY,
    play_music_function_desc, play_story_function_desc,
    GET_WEATHER_FUNCTION_DESC, get_time_function_desc,
    exit_function_desc,
    audio_function_desc,
    achievement_function_desc,
    search_diary_function_desc,
    switch_tone_desc,
    play_music_desc,
    play_story_desc,
    change_sound_desc
)
# from MemoTest.one_step_get_memo import query_memory


# ===== pillow 提示词拼装配置 =====
PILLOW_SN = "TBZNN76YR7UUK"      
    # 设备 SN，换 SN 即换角色
PILLOW_ENABLE_PROMPT_WRAP = True     # False 则跳过拼装，走原来的裸输入
PILLOW_VARIABLES_API = "http://10.10.10.24:8500/pillow/remote/device/conversation-variables"
PILLOW_API_HEADERS = {
    "Crknife-Internal-Call": "true",
    "Accept-Language": "zh-CN",
}
PILLOW_API_TIMEOUT = 8.0

# ===== 对话历史展示配置 =====
PRINT_HISTORY_JSON_AFTER_TURN = True   # 每轮对话结束后打印完整历史（OpenAI messages 格式）
HISTORY_JSON_INDENT = 2                # 缩进；设为 None 则输出单行 JSON

# 变量名与 PILLOW_USER_PROMPT_TEMPLATE 中的占位符一一对应
PILLOW_VAR_KEYS = [
    "worldview",
    "story",
    "memory_chapter",
    "event_section",
    "profile_section",
    "weather",
    "Volume",
    "charging_status",
    "special_scenarios",
    "battery_notification",
]


def fetch_pillow_variables(user_input: str) -> Optional[Dict[str, Any]]:
    """按 SN 拉取本轮对话变量；任何失败都返回 None，由调用方降级为原始输入。"""
    try:
        resp = httpx.post(
            PILLOW_VARIABLES_API,
            headers=PILLOW_API_HEADERS,
            json={"sn": PILLOW_SN, "userInput": user_input},
            timeout=PILLOW_API_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[提示词] 变量接口调用失败：{e}", flush=True)
        return None

    if not isinstance(data, dict):
        print(f"[提示词] 变量接口返回格式异常（{type(data).__name__}）", flush=True)
        return None

    return data


def fill_pillow_prompt(variables: Dict[str, Any], user_input: str) -> str:
    """把变量填进模板，用户原话追加在最末尾。缺失字段按空串处理。"""
    text = PILLOW_USER_PROMPT_TEMPLATE
    for key in PILLOW_VAR_KEYS:
        value = variables.get(key, "")
        if value is None:
            value = ""
        text = text.replace("{{" + key + "}}", str(value))
    return text.rstrip() + "\n" + user_input



class ConversationManager:
    """对话管理器 - 整合主要功能"""

    def __init__(self):
        # 配置参数
        self.used_model = DOUBAO_AVAILABLE_MODELS[4]
        self.used_api_key = DOUBAO_API_KEY
        self.used_base_url = DOUBAO_API_URL

        # self.used_model = "qwen3.5-plus"
        # self.used_api_key = Ali_API_KEY
        # self.used_base_url = Ali_API_URL

        # self.used_model = DEEPSEEK_AVAILABLE_MODELS[1]
        # self.used_api_key = DEEPSEEK_API_KEY
        # self.used_base_url = DEEPSEEK_API_URL

        # self.used_model = XUNFEI_AVAILABLE_MODEniha
        # self.used_api_key = XUNFEI_API_KEY
        # self.used_base_url = XUNFEI_API_URL

        # self.used_prompt = SYSTEM_PROMPT_TEMPLATE_v031
        self.used_prompt = SYSTEM_PROMPT_TEMPLATE
        # self.used_prompt = SYSTEM_PROMPT_TEMPLATE_v042

        # "type": "disabled",  # 不使用深度思考能力
        # "type": "enabled", # 使用深度思考能力
        # "type": "auto", # 模型自行判断是否使用深度思考能力
        self.thinking_type = "disabled"

        # 对话状态
        self.chat_history = []
        # 等待 //tool 手动回填的 tool_call 队列；每项含 tool_call 结构与所属 assistant 消息引用
        self.pending_tool_calls: List[Dict[str, Any]] = []
        self.client = OpenAI(api_key=self.used_api_key, base_url=self.used_base_url)

        # 统计信息
        self.stats = {
            "chat_rounds": 0,
            "first_package_latencies": [],
            "memo_query_latencies": [],
            "token_usage": []
        }

    def create_system_prompt(self) -> str:
        # """创建系统提示词"""
        # # current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:00:00")

        # prompt = self.used_prompt
        # replacements = {
        #     "{{birth_date}}": "2020/1/1",
        #     "{{name}}": "欣欣",
        #     "{{gender}}": "女",
        #     "{{time}}": current_time,
        #     "{{solar_terms}}": "立冬",
        #     "{{local_address}}": "重庆",
        #     "{{weather_info}}": "阴"
        # }

        # for key, value in replacements.items():
        #     prompt = prompt.replace(key, value)

        return self.used_prompt

    def _extract_tool_call_parts(self, tool_call: Any) -> Tuple[str, str]:
        """提取 tool call 的函数名和参数，兼容 dict / SDK 对象结构。"""
        if isinstance(tool_call, dict):
            function_info = tool_call.get("function") or {}
            name = function_info.get("name", "")
            arguments = function_info.get("arguments", "")
            return str(name or "").strip(), str(arguments or "").strip()

        function_info = getattr(tool_call, "function", None)
        name = getattr(function_info, "name", "") if function_info else ""
        arguments = getattr(function_info, "arguments", "") if function_info else ""
        return str(name or "").strip(), str(arguments or "").strip()

    def _render_tool_call_placeholder(
        self,
        tool_calls: Optional[List[Any]],
        tool_call_content: str = ""
    ) -> str:
        """为未回填的 tool call 生成可读占位，避免空 assistant 污染上下文。"""
        rendered = []
        for tool_call in tool_calls or []:
            function_name, arguments = self._extract_tool_call_parts(tool_call)
            if function_name and arguments:
                rendered.append(f"{function_name}({arguments})")
            elif function_name:
                rendered.append(function_name)
            elif arguments:
                rendered.append(arguments)

        summary = "；".join(part for part in rendered if part).strip()
        if not summary:
            summary = (tool_call_content or "").strip() or "未解析到工具调用参数"

        return f"[工具调用未回填] {summary}"

    def _build_tool_calls_payload(self, tool_calls: Optional[List[Any]]) -> List[Dict[str, Any]]:
        """把内部存储的 tool_calls 转换成可回传给模型的合法结构。"""
        payload = []
        for index, tool_call in enumerate(tool_calls or []):
            function_name, arguments = self._extract_tool_call_parts(tool_call)
            call_id = ""
            if isinstance(tool_call, dict):
                call_id = str(tool_call.get("id", "") or "")
            else:
                call_id = str(getattr(tool_call, "id", "") or "")
            if not call_id:
                call_id = f"call_{index}"

            payload.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": function_name,
                    "arguments": arguments,
                },
            })
        return payload

    def _normalize_history_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """将历史消息转换成可安全回传给模型的格式。"""
        role = msg.get("role", "")

        if role == "tool":
            normalized = {
                "role": role,
                "content": msg.get("content", ""),
                "tool_call_id": msg.get("tool_call_id", "")
            }
            tool_name = msg.get("name")
            if tool_name:
                normalized["name"] = tool_name
            return normalized

        content = msg.get("content", "")
        content_text = str(content or "").strip()

        if role == "assistant" and msg.get("tool_calls"):
            if msg.get("tool_calls_resolved"):
                # 已用 //tool 回填：回传真实 tool_calls 结构，配合后续 tool 消息构成合法序列
                return {
                    "role": role,
                    "content": content_text,
                    "tool_calls": self._build_tool_calls_payload(msg.get("tool_calls"))
                }
            # 未回填（被用户跳过）：降级为占位文本，不带 tool_calls，避免缺 tool 响应的非法序列
            if not content_text:
                content = self._render_tool_call_placeholder(
                    msg.get("tool_calls"),
                    msg.get("tool_call_content", "")
                )

        return {
            "role": role,
            "content": content
        }

    def _get_recent_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """截取最近历史时尽量从 user 开始，避免半截 assistant/tool 链路。"""
        if not self.chat_history:
            return []

        if limit is None:
            return list(self.chat_history)

        if limit <= 0:
            return []

        start_index = max(0, len(self.chat_history) - limit)
        while start_index > 0 and self.chat_history[start_index].get("role") != "user":
            start_index -= 1

        return self.chat_history[start_index:]

    def get_history_json(
        self,
        indent: Optional[int] = 2,
        user_prompt_override: Optional[str] = None,
    ) -> str:
        """把当前对话历史导出为 OpenAI messages 格式的 JSON 字符串。

        每条消息单独占一行（indent 为每行前缀缩进空格数），便于在终端里
        纵向浏览又不占太多行；indent=None 时输出整段单行 JSON。

        user_prompt_override 只替换导出结果里最后一条 user 消息的内容，
        用于显示本轮实际发往模型的拼装提示词，不改动 self.chat_history。
        """
        messages = [self._normalize_history_message(msg) for msg in self.chat_history]

        if user_prompt_override:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    msg["content"] = user_prompt_override
                    break

        if not messages:
            return "[]"
        if indent is None:
            return json.dumps(messages, ensure_ascii=False)

        pad = " " * indent
        body = ",\n".join(pad + json.dumps(msg, ensure_ascii=False) for msg in messages)
        return "[\n" + body + "\n]"

    def build_messages_with_memory(self, user_content: str, user_prompt_override: Optional[str] = None) -> Tuple[List[Dict], str, float]:
        """构建消息列表（包含记忆查询）

        user_prompt_override 仅覆盖本次发往模型的最后一条 user 消息，
        不影响 self.chat_history（历史里始终保存用户原文）。
        """
        # 查询记忆
        memo_start_time = time.time()
        # memory_str = query_memory(user_content)
        memo_latency = time.time() - memo_start_time
        self.stats["memo_query_latencies"].append(memo_latency)

        # 构建带记忆的系统提示词
        system_prompt = self.create_system_prompt()
        # if memory_str and len(memory_str) > 0:
        #     system_prompt = f"{system_prompt}\n\n```\n{memory_str}\n```"

# 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 从最近历史中取完整链路，避免窗口恰好从 assistant 半截开始
        clean_history = []
        for msg in self._get_recent_history():
            clean_history.append(self._normalize_history_message(msg))

        messages.extend(clean_history)

        # 本轮用户提示词覆盖（只改发出去的消息，历史仍存原文）
        if user_prompt_override:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    msg["content"] = user_prompt_override
                    break

        return messages, system_prompt, memo_latency

    def build_messages_without_memory(self) -> List[Dict]:
        """构建消息列表（不包含记忆查询）"""
        # 构建系统提示词
        system_prompt = self.create_system_prompt()

        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        clean_history = []
        for msg in self.chat_history:
            clean_history.append(self._normalize_history_message(msg))

        messages.extend(clean_history)

        return messages

    def process_stream_response(self, stream_response, overall_start_time: float) -> Dict:
        """处理流式响应"""
        processor = {
            "full_content": "",
            "tool_call_content": "",
            "reasoning_content": "",
            "tool_calls": [],
            "token_usage": None,
            "first_chunk_received": False,
            "first_package_latency": 0.0
        }

        print("LLM回复：", end="", flush=True)
        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}

        try:
            for chunk in stream_response:
                chunk: ChatCompletionChunk = chunk
                # print(f"{chunk.choices}", end="", flush=True)
                # 调试：打印当前chunk
                # print(f"当前chunk：{chunk}")

                # 处理Token使用量
                if hasattr(chunk, 'usage') and chunk.usage:
                    processor["token_usage"] = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                        "cache_tokens": chunk.usage.prompt_tokens_details.cached_tokens # 火山方舟/DeepSeek API的用法
                    }
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # 处理第一个chunk
                if not processor["first_chunk_received"]:
                    processor["first_chunk_received"] = True
                    processor["first_package_latency"] = time.time() - overall_start_time

                # 检查错误
                if hasattr(delta, 'error') and delta.error:
                    raise Exception(
                        f"{delta.error.get('code', '未知错误')}: {delta.error.get('message', '无错误描述')}")

                # 处理思考过程
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    processor["reasoning_content"] += delta.reasoning_content

                # 处理工具调用
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        tool_index = getattr(tool_call, "index", None)
                        if tool_index is None:
                            tool_index = 0 if not tool_calls_by_index else max(tool_calls_by_index.keys()) + 1

                        if tool_index not in tool_calls_by_index:
                            tool_calls_by_index[tool_index] = {
                                "id": "",
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }

                        current_call = tool_calls_by_index[tool_index]

                        call_id = getattr(tool_call, "id", None)
                        if call_id:
                            current_call["id"] = call_id

                        call_type = getattr(tool_call, "type", None)
                        if call_type:
                            current_call["type"] = call_type

                        function_obj = getattr(tool_call, "function", None)
                        if function_obj:
                            function_name = getattr(function_obj, "name", None)
                            if function_name:
                                current_call["function"]["name"] = function_name

                            arguments_chunk = getattr(function_obj, "arguments", None)
                            if arguments_chunk:
                                current_call["function"]["arguments"] += arguments_chunk
                                processor["tool_call_content"] += arguments_chunk
                                print(f"{arguments_chunk}", end="", flush=True)

                    processor["tool_calls"] = [
                        tool_calls_by_index[idx] for idx in sorted(tool_calls_by_index.keys())
                    ]
                    
                # 处理回复内容
                if hasattr(delta, 'content') and delta.content:
                    content_chunk = delta.content
                    processor["full_content"] += content_chunk
                    print(content_chunk, end="", flush=True)

        except Exception as e:
            print(f"\n流式响应处理错误：{str(e)}", flush=True)
            raise
        finally:
            stream_response.close()

        if not processor["tool_calls"]:
            processor["tool_calls"] = None

        return processor

    def call_llm(self, messages: List[Dict]) -> Any:
        """调用LLM API"""
        return self.client.chat.completions.create(
            model=self.used_model,
            messages=messages,
            tools=[
                # play_music_function_desc,
                # play_story_function_desc,
                # GET_WEATHER_FUNCTION_DESC,
                get_time_function_desc,
                exit_function_desc,
                # audio_function_desc,
                # achievement_function_desc,
                # search_diary_function_desc,
                # switch_tone_desc,
                play_music_desc,
                play_story_desc,
                change_sound_desc
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
            extra_body={"thinking": {"type": self.thinking_type}} # 豆包
            # extra_body={"enable_thinking": False}
            # thinking={
            # "type": self.thinking_type, # 不使用深度思考能力
            # },
        )

    def add_assistant_message(self, processor: Dict, memo_latency: float):
        """添加助手消息到历史记录"""
        if processor["full_content"] or processor["tool_calls"]:
            # 保留真实回复内容；纯 tool call 轮次 content 为空，回传时由 _normalize_history_message 决定形态
            content = processor["full_content"] or ""
            assistant_message = {
                "role": "assistant",
                "content": content,
                # "memo_query_latency": memo_latency,
                # "first_package_latency": processor["first_package_latency"],
                # "total_response_latency": time.time() - (time.time() - processor["first_package_latency"]),
                # "token_usage": processor["token_usage"],
            }

            if processor["tool_calls"]:
                assistant_message["tool_calls"] = processor["tool_calls"]
                assistant_message["tool_call_content"] = processor["tool_call_content"]
                # 是否已用 //tool 回填：决定回传时用真实结构还是占位文本
                assistant_message["tool_calls_resolved"] = False

            self.chat_history.append(assistant_message)

            # 触发了 function call：把每个 call 压入待回填队列，记录所属 assistant 消息引用
            if processor["tool_calls"]:
                for tool_call in processor["tool_calls"]:
                    self.pending_tool_calls.append({
                        "tool_call": tool_call,
                        "assistant_message": assistant_message,
                    })

            # 更新统计
            self.stats["chat_rounds"] += 1
            self.stats["first_package_latencies"].append(processor["first_package_latency"])
            if processor["token_usage"]:
                self.stats["token_usage"].append(processor["token_usage"])
        else:
            print("警告：未获取到有效回复内容，不添加到对话历史\n")
            # 移除无效的用户输入
            if self.chat_history and self.chat_history[-1]["role"] == "user":
                self.chat_history.pop()

    def append_tool_response(self, tool_call: Any, content: str):
        """手动回填一个 tool call 的响应，追加 tool 角色消息到历史。"""
        function_name, _ = self._extract_tool_call_parts(tool_call)
        call_id = ""
        if isinstance(tool_call, dict):
            call_id = str(tool_call.get("id", "") or "")
        else:
            call_id = str(getattr(tool_call, "id", "") or "")

        tool_message = {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        }
        if function_name:
            tool_message["name"] = function_name

        self.chat_history.append(tool_message)

    def discard_pending_tool_calls(self):
        """放弃当前待回填的 tool call：清空队列，对应 assistant 轮次走占位文本回传。"""
        self.pending_tool_calls.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        # 首包耗时统计
        valid_first_latencies = [lat for lat in self.stats["first_package_latencies"] if lat > 0.0]
        avg_first_latency = sum(valid_first_latencies) / len(valid_first_latencies) if valid_first_latencies else 0.0

        # 记忆查询耗时统计
        valid_memo_latencies = [lat for lat in self.stats["memo_query_latencies"] if lat > 0.0]
        avg_memo_latency = sum(valid_memo_latencies) / len(valid_memo_latencies) if valid_memo_latencies else 0.0

        # Token使用量统计
        token_stats = self._calculate_token_statistics()

        return {
            "chat_rounds": self.stats["chat_rounds"],
            "first_package_latency": {
                "valid_records": len(valid_first_latencies),
                "avg_latency": avg_first_latency
            },
            "memo_query_latency": {
                "valid_records": len(valid_memo_latencies),
                "avg_latency": avg_memo_latency
            },
            "token_usage": token_stats
        }

    def _calculate_token_statistics(self) -> Dict[str, Any]:
        """计算Token统计"""
        if not self.stats["token_usage"]:
            return {"valid_records": 0}

        total_prompt = sum(usage["prompt_tokens"] for usage in self.stats["token_usage"])
        total_completion = sum(usage["completion_tokens"] for usage in self.stats["token_usage"])
        total_cache = sum(usage["cache_tokens"] for usage in self.stats["token_usage"])
        total_all = sum(usage["total_tokens"] for usage in self.stats["token_usage"])
        valid_records = len(self.stats["token_usage"])

        return {
            "valid_records": valid_records,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cached_tokens": total_cache,
            "total_all_tokens": total_all,
            "avg_prompt_tokens": total_prompt / valid_records if valid_records else 0,
            "avg_completion_tokens": total_completion / valid_records if valid_records else 0,
            "avg_cache_tokens": total_cache / valid_records if valid_records else 0,
            "avg_all_tokens": total_all / valid_records if valid_records else 0,
        }


def print_response_statistics(processor: Dict, overall_start_time: float, memo_latency: float):
    """打印单轮响应统计"""
    if processor["first_chunk_received"]:
        total_response_latency = time.time() - overall_start_time

        # print(f"\n\n【本轮耗时统计】", flush=True)
        # print(f"首包耗时：{processor['first_package_latency']:.6f} 秒", flush=True)
        # print(f"总回复耗时：{total_response_latency:.6f} 秒", flush=True)
        # print(f"记忆查询耗时：{memo_latency:.6f} 秒", flush=True)

        # 打印Token使用量
        if processor["token_usage"]:
            usage = processor["token_usage"]
            print(f"\n输入Token（prompt）：{usage['prompt_tokens']} 个", flush=True)
            print(f"输出Token（completion）：{usage['completion_tokens']} 个", flush=True)
            print(f"缓存Token（cache）：{usage['cache_tokens']} 个", flush=True)
            print(f"总Token消耗：{usage['total_tokens']} 个", flush=True)
        else:
            print(f"\n【警告】: 未获取到Token使用量数据", flush=True)
    else:
        print("\n\n【警告】: 未收到任何流式响应chunk", flush=True)


def print_additional_info(processor: Dict, thinking_type: str):
    """打印额外信息"""
    print(f"\n【本轮额外信息】")

    if thinking_type in {"enabled", "auto"}:
        print(f"LLM思考：{processor['reasoning_content']}\n")

    if processor["tool_calls"]:
        print("function_call_info：")
        for idx, tool_call in enumerate(processor["tool_calls"], 1):
            function_info = tool_call.get("function", {})
            print(
                f"  {idx}. id={tool_call.get('id', '')}, "
                f"name={function_info.get('name', '')}, "
                f"arguments={function_info.get('arguments', '')}"
            )
    else:
        print("function_call_info：无")

    print(f"function_call_content：{processor['tool_call_content'] or '无'}\n")


def print_history_json(
    manager: ConversationManager,
    user_prompt_override: Optional[str] = None,
):
    """打印当前完整历史，格式为标准 messages 数组 JSON（每条消息一行）。

    user_prompt_override 用于在展示层面把最后一条 user 消息替换成本轮
    拼装后的提示词；self.chat_history 里保存的仍是用户原文。
    """
    if not PRINT_HISTORY_JSON_AFTER_TURN:
        return

    print(f"对话历史（{len(manager.chat_history)} 条消息）：")
    print(
        manager.get_history_json(
            indent=HISTORY_JSON_INDENT,
            user_prompt_override=user_prompt_override,
        ),
        flush=True,
    )
    print()


def print_conversation_summary(manager: ConversationManager, last_messages: List[Dict]):
    """打印对话总结"""
    stats = manager.get_statistics()

    print("\n" + "=" * 60)
    print("对话已结束")
    print("=" * 60)

    print(f"\n【对话模型】")
    print(f"模型：{manager.used_model}\n")

    print(f"\n【对话核心统计】")
    print(f"对话总轮次：{stats['chat_rounds']} 轮")

    print(f"\n【首包耗时统计】")
    if stats['chat_rounds'] > 0:
        first_latency = stats['first_package_latency']
        print(f"有效首包耗时记录数：{first_latency['valid_records']} 条")
        print(f"平均首包耗时：{first_latency['avg_latency']:.6f} 秒")
    else:
        print("未产生有效对话轮次")

    print(f"\n【记忆查询耗时统计】")
    if stats['chat_rounds'] > 0:
        memo_latency = stats['memo_query_latency']
        print(f"有效记忆查询耗时记录数：{memo_latency['valid_records']} 条")
        print(f"平均记忆查询耗时：{memo_latency['avg_latency']:.6f} 秒")
    else:
        print("未产生有效记忆查询")

    print(f"\n【Token使用量统计】")
    token_usage = stats['token_usage']
    if token_usage['valid_records'] > 0:
        print(f"有效Token记录数：{token_usage['valid_records']} 条")
        print(f"总输入Token（prompt）：{token_usage['total_prompt_tokens']} 个")
        print(f"总输出Token（completion）：{token_usage['total_completion_tokens']} 个")
        print(f"总缓存Token（cache）：{token_usage['total_cached_tokens']} 个")
        print(f"总Token消耗：{token_usage['total_all_tokens']} 个")
        print(f"平均每轮输入Token：{token_usage['avg_prompt_tokens']:.1f} 个")
        print(f"平均每轮输出Token：{token_usage['avg_completion_tokens']:.1f} 个")
        print(f"平均每轮缓存Token：{token_usage['avg_cache_tokens']:.1f} 个")
        print(f"平均每轮总Token：{token_usage['avg_all_tokens']:.1f} 个")
    else:
        print("无有效Token使用记录")

    print(f"\n{'-' * 60}")
    print("本轮对话完整消息：")
    for i, msg in enumerate(manager.chat_history, 1):
        role = msg.get("role", "")
        if role == "tool":
            label = "工具返回"
            extra = f"(tool_call_id={msg.get('tool_call_id', '')})"
            print(f"{i:2d}. {label}{extra}：{msg.get('content', '')}")
        elif role == "assistant" and msg.get("tool_calls"):
            calls = manager._build_tool_calls_payload(msg.get("tool_calls"))
            calls_desc = "；".join(
                f"{c['function']['name']}({c['function']['arguments']})" for c in calls
            )
            content = msg.get("content", "")
            text = f"[工具调用] {calls_desc}"
            if content:
                text = f"{content} {text}"
            print(f"{i:2d}. 助手：{text}")
        else:
            label = "用户" if role == "user" else "助手"
            print(f"{i:2d}. {label}：{msg.get('content', '')}")
    print("=" * 60 + "\n")

    # print(f"\n【最后传入的messages记录】")
    # print(f"\n{last_messages}")


def main():
    """主函数"""
    manager = ConversationManager()

    print(f"当前使用模型：{manager.used_model}\n")

    try:
        while True:
            # 获取用户输入
            user_content = input("你想聊什么（输入//quit结束对话）：")
            # user_content = f"""

            # ## 用户当前记忆：
            # - 运动出行::旅游偏好: 周末喜欢去周边的古镇逛逛 [提及于 2025/12/09]
            # - 基本信息::用户姓名: 王佳 [提及于 2025/12/09]
            # - 基本信息::用户年龄: 27 [提及于 2025/12/09]
            # - 基本信息::用户生日: 1997-09-03 [提及于 2025/12/09]
            # - 基本信息::农历生日: 丁丑年七月三十 [提及于 2025/12/09]
            # - 运动出行::日常健身习惯: 下班后去瑜伽馆练习瑜伽 [提及于 2025/12/09]
            # - 运动出行::出行交通方式: 出门优先选择地铁 [提及于 2025/12/09]
            # - 美食饮食::口味偏好: 清淡，如清炒时蔬、冬瓜丸子汤，不太能接受太辣的食物 [提及于 2025/12/09]
            # - 美食饮食::饮酒/咖啡习惯: 喜欢喝手冲咖啡 [提及于 2025/12/09]
            # - 娱乐社交::影视/游戏偏好: 喜欢看纪录片，尤其是自然和历史题材的 [提及于 2025/12/09]
            # - 娱乐社交::社交聚会形式: 和朋友聚会时更爱去咖啡馆聊天，不太喜欢吵闹的地方 [提及于 2025/12/09]
            # - 兴趣手艺::宠物饲养: 养了一只布偶猫，名叫糯米 [提及于 2025/12/09]
            # - 兴趣手艺::手工/diy制作: 最近在学插花 [提及于 2025/12/09]
            # - 兴趣手艺::园艺/植物养护: 家里种了几盆薄荷，偶尔摘几片泡水泡茶喝 [提及于 2025/12/09]
            # - 兴趣手艺::收藏爱好: 喜欢玩拼图，尤其是上千片的那种 [提及于 2025/12/09]
            # - 文化学习::阅读书籍类型: 特别喜欢读科幻小说，尤其是刘慈欣的作品 [提及于 2025/12/09]
            # - 文化学习::技能学习计划: 正在研究数据分析，使用Python处理数据 [提及于 2025/12/09]
            # - 其他::其他个人偏好: 不太喜欢熬夜，周末也会尽量在11点前睡觉 [提及于 2025/12/09]
            
            # {user_content}
            # """
            # 检查退出条件
            if user_content.strip() == "//quit":
                # 退出前若仍有待回填的 tool call，放弃回填（回传时降级为占位文本）
                manager.discard_pending_tool_calls()
                # 使用不查询记忆的方法获取最后使用的messages
                last_messages = manager.build_messages_without_memory()
                print_conversation_summary(manager, last_messages)
                break

            # 解析 //tool 指令：提取 tool 之后的内容作为模拟的工具返回值
            stripped = user_content.lstrip('/\\').strip()
            is_tool_cmd = stripped == "tool" or stripped.startswith("tool ") or stripped.startswith("tool\t")

            if is_tool_cmd:
                if not manager.pending_tool_calls:
                    print("当前没有待回填的工具调用，请先正常对话触发 function call。")
                    continue

                # 取出 //tool 之后的返回内容（允许为空字符串）
                tool_result = stripped[len("tool"):].strip()

                # 逐个回填：取队首 tool_call
                pending = manager.pending_tool_calls.pop(0)
                tool_call = pending["tool_call"]
                function_name, _ = manager._extract_tool_call_parts(tool_call)
                manager.append_tool_response(tool_call, tool_result)

                remaining = len(manager.pending_tool_calls)
                print(f"已回填工具调用 [{function_name}]，剩余 {remaining} 个待回填。")

                if remaining > 0:
                    # 还有未回填的 tool_call，等待下一个 //tool
                    continue

                # 全部回填完成：标记该 assistant 轮次已解析，重新请求模型（支持链式调用）
                pending["assistant_message"]["tool_calls_resolved"] = True
                process_followup_turn(manager)
                continue

            # 普通输入：若仍有待回填的 tool call，视为放弃回填，继续正常对话
            if manager.pending_tool_calls:
                print("已跳过工具回填，继续对话。")
                manager.discard_pending_tool_calls()

            # 处理单轮对话
            process_single_turn(user_content, manager)

    except KeyboardInterrupt:
        print("\n\n对话被用户中断")
    except Exception as e:
        print(f"\n发生错误：{str(e)}")


def process_single_turn(user_content: str, manager: ConversationManager):
    """处理单轮对话"""
    # 记录整体开始时间
    overall_start_time = time.time()

    # 功能性指令（//tool、//quit 等）不包装提示词
    is_command = user_content.strip().startswith("//")

    # 拉取对话变量并拼装本轮用户提示词；失败则降级为原始输入
    prompt_override = None
    if PILLOW_ENABLE_PROMPT_WRAP and not is_command:
        variables = fetch_pillow_variables(user_content)
        if variables is not None:
            prompt_override = fill_pillow_prompt(variables, user_content)
        else:
            print("[提示词] 变量接口不可用，降级为原始输入", flush=True)

    # 添加用户消息到历史（始终存原文）
    manager.chat_history.append({"role": "user", "content": user_content})

    # 构建消息（包含记忆查询）
    messages, system_prompt, memo_latency = manager.build_messages_with_memory(
        user_content, user_prompt_override=prompt_override
    )

    # print(f"当前使用的系统提示词：{system_prompt}\n")

    # 展示本轮对话历史（含本轮拼装后的提示词），放在本轮输出的最前面
    print_history_json(manager, user_prompt_override=prompt_override)

    # 发送请求并处理响应
    try:
        stream_response = manager.call_llm(messages)

        processor = manager.process_stream_response(stream_response, overall_start_time)

        # 打印本轮统计信息
        print_response_statistics(processor, overall_start_time, memo_latency)

        # 处理思考过程和工具调用信息
        print_additional_info(processor, manager.thinking_type)

        # 将助手回复添加到历史
        manager.add_assistant_message(processor, memo_latency)


    except Exception as e:
        print(f"\nLLM调用错误：{str(e)}", flush=True)
        # 移除无效的用户输入
        if manager.chat_history and manager.chat_history[-1]["role"] == "user":
            manager.chat_history.pop()


def process_followup_turn(manager: ConversationManager):
    """工具回填完成后，不追加新 user 消息，直接基于已回填的 tool 响应重新请求模型。"""
    overall_start_time = time.time()
    memo_latency = 0.0

    # 不查询记忆、不新增 user 消息，直接用当前历史构建消息体
    messages = manager.build_messages_without_memory()

    # 展示本轮对话历史，放在本轮输出的最前面
    print_history_json(manager)

    try:
        stream_response = manager.call_llm(messages)

        processor = manager.process_stream_response(stream_response, overall_start_time)

        print_response_statistics(processor, overall_start_time, memo_latency)
        print_additional_info(processor, manager.thinking_type)

        # 将助手回复添加到历史（若再次触发 function call，会重新填充 pending_tool_calls，实现链式）
        manager.add_assistant_message(processor, memo_latency)

    except Exception as e:
        print(f"\nLLM调用错误：{str(e)}", flush=True)


if __name__ == "__main__":
    main()
