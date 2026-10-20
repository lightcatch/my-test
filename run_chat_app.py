# -*- coding: utf-8 -*-
"""
可打包的对话程序入口。

在不修改原始对话实现的前提下，于启动时提供：
  1. 模型选择：deepseek-v4-flash / doubao-seed-2-0-lite-260215 / doubao-seed-2-0-lite-260428
  2. 系统提示词自定义

复用原文件中的 ConversationManager 与各处理函数，通过子类注入配置。
"""

from openai import OpenAI

from config11 import (
    DOUBAO_API_URL, DOUBAO_API_KEY,
    DEEPSEEK_API_URL, DEEPSEEK_API_KEY,
    SYSTEM_PROMPT_TEMPLATE,
    TEMPERATURE, MAX_TOKENS,
    get_time_function_desc, exit_function_desc,
    play_music_desc, play_story_desc, change_sound_desc,
)
import LLM_call_test_stream_pillow as chat


# 可供选择的模型清单：序号 -> 连接配置
MODEL_CHOICES = {
    "1": {
        "label": "deepseek-v4-flash",
        "model": "deepseek-v4-flash",
        "api_key": DEEPSEEK_API_KEY,
        "base_url": DEEPSEEK_API_URL,
    },
    "2": {
        "label": "doubao-seed-2-0-lite-260215",
        "model": "doubao-seed-2-0-lite-260215",
        "api_key": DOUBAO_API_KEY,
        "base_url": DOUBAO_API_URL,
    },
    "3": {
        "label": "doubao-seed-2-0-lite-260428",
        "model": "doubao-seed-2-0-lite-260428",
        "api_key": DOUBAO_API_KEY,
        "base_url": DOUBAO_API_URL,
    },
}


class ChatManager(chat.ConversationManager):
    """在原 ConversationManager 基础上支持外部配置，并按模型来源条件化 extra_body。"""

    def __init__(self, model, api_key, base_url, prompt):
        super().__init__()
        self.used_model = model
        self.used_api_key = api_key
        self.used_base_url = base_url
        self.used_prompt = prompt
        # 仅火山方舟(豆包)支持 extra_body 的 thinking 参数
        self.is_doubao = base_url == DOUBAO_API_URL
        # 用选定配置重建 client
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def call_llm(self, messages):
        """调用 LLM API；豆包附带 thinking 参数，其余模型不附带。"""
        print(f"【本轮调用LLM消息体，共{len(messages)}条】")
        print(self._format_messages_for_log(messages))
        print()

        request_kwargs = dict(
            model=self.used_model,
            messages=messages,
            tools=[
                get_time_function_desc,
                exit_function_desc,
                play_music_desc,
                play_story_desc,
                change_sound_desc,
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
        )

        if self.is_doubao:
            request_kwargs["extra_body"] = {"thinking": {"type": self.thinking_type}}

        return self.client.chat.completions.create(**request_kwargs)


def select_model():
    """让用户选择使用的模型，返回对应配置字典。"""
    print("=" * 60)
    print("请选择要使用的模型：")
    for key in sorted(MODEL_CHOICES.keys()):
        print(f"  {key}. {MODEL_CHOICES[key]['label']}")
    print("=" * 60)

    valid_choices = "/".join(sorted(MODEL_CHOICES))
    while True:
        choice = input(f"请输入序号（{valid_choices}）：").strip()
        if choice in MODEL_CHOICES:
            selected = MODEL_CHOICES[choice]
            print(f"\n已选择模型：{selected['label']}\n")
            return selected
        print(f"输入无效，请输入 {valid_choices}。")


def select_prompt():
    """让用户选择系统提示词：使用默认或自定义输入。"""
    print("=" * 60)
    print("系统提示词设置：")
    print("  1. 使用默认提示词")
    print("  2. 自定义提示词（手动输入）")
    print("=" * 60)

    while True:
        choice = input("请输入序号（1/2）：").strip()
        if choice == "1":
            print("\n已使用默认提示词。\n")
            return SYSTEM_PROMPT_TEMPLATE
        if choice == "2":
            print("\n请输入自定义提示词，输入完成后另起一行输入 //end 结束：")
            lines = []
            while True:
                line = input()
                if line.strip() == "//end":
                    break
                lines.append(line)
            custom = "\n".join(lines).strip()
            if not custom:
                print("未输入任何内容，将使用默认提示词。\n")
                return SYSTEM_PROMPT_TEMPLATE
            print("\n已使用自定义提示词。\n")
            return custom
        print("输入无效，请输入 1 或 2。")


def main():
    """带模型/提示词选择的主流程，其余逻辑复用原文件。"""
    model_conf = select_model()
    prompt = select_prompt()

    manager = ChatManager(
        model=model_conf["model"],
        api_key=model_conf["api_key"],
        base_url=model_conf["base_url"],
        prompt=prompt,
    )

    print(f"当前使用模型：{manager.used_model}\n")

    try:
        while True:
            user_content = input("你想聊什么（输入//quit结束对话）：")

            if user_content.strip() == "//quit":
                manager.discard_pending_tool_calls()
                last_messages = manager.build_messages_without_memory()
                chat.print_conversation_summary(manager, last_messages)
                break

            stripped = user_content.lstrip('/\\').strip()
            is_tool_cmd = (
                stripped == "tool"
                or stripped.startswith("tool ")
                or stripped.startswith("tool\t")
            )

            if is_tool_cmd:
                if not manager.pending_tool_calls:
                    print("当前没有待回填的工具调用，请先正常对话触发 function call。")
                    continue

                tool_result = stripped[len("tool"):].strip()

                pending = manager.pending_tool_calls.pop(0)
                tool_call = pending["tool_call"]
                function_name, _ = manager._extract_tool_call_parts(tool_call)
                manager.append_tool_response(tool_call, tool_result)

                remaining = len(manager.pending_tool_calls)
                print(f"已回填工具调用 [{function_name}]，剩余 {remaining} 个待回填。")

                if remaining > 0:
                    continue

                pending["assistant_message"]["tool_calls_resolved"] = True
                chat.process_followup_turn(manager)
                continue

            if manager.pending_tool_calls:
                print("已跳过工具回填，继续对话。")
                manager.discard_pending_tool_calls()

            chat.process_single_turn(user_content, manager)

    except KeyboardInterrupt:
        print("\n\n对话被用户中断")
    except Exception as e:
        print(f"\n发生错误：{str(e)}")


if __name__ == "__main__":
    main()
