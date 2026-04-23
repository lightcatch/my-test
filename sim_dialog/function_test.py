import datetime
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
from openai import OpenAI
from openai.types.chat import ChatCompletionChunk

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Support running this file directly via an absolute/relative script path.
if __package__ is None or __package__ == "":
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from config11 import (
    DOUBAO_AVAILABLE_MODELS, DOUBAO_API_URL, DOUBAO_API_KEY,
    Ali_API_KEY, Ali_API_URL,
    TEMPERATURE, MAX_TOKENS, SYSTEM_PROMPT_TEMPLATE, 
    XUNFEI_AVAILABLE_MODELS, XUNFEI_API_URL, XUNFEI_API_KEY,
    DEEPSEEK_AVAILABLE_MODELS, DEEPSEEK_API_URL, DEEPSEEK_API_KEY,
    play_music_function_desc, play_story_function_desc,
    GET_WEATHER_FUNCTION_DESC, get_time_function_desc,
    handle_exit_intent_function_desc,
    audio_function_desc,
    achievement_function_desc,
    search_diary_function_desc,
    search_news_function_desc
)
# from MemoTest.one_step_get_memo import query_memory

# 测试用例文件参数
EXCEL_FILE_PATH = r"C:\Users\Administrator\Desktop\测试用例集全.xlsx"
WORKSHEET_NAME = "Sheet1"

"""
以下修改单次测试用到的参数
"""

# 指定本次测试用的模型
used_model = "qwen3.6-plus"
used_api_key = Ali_API_KEY
used_base_url = Ali_API_URL
used_prompt = SYSTEM_PROMPT_TEMPLATE

# used_model = DOUBAO_AVAILABLE_MODELS[17]
# used_api_key = DOUBAO_API_KEY
# used_base_url = DOUBAO_API_URL
# used_prompt = SYSTEM_PROMPT_TEMPLATE

# used_model = DEEPSEEK_AVAILABLE_MODELS[0]
# used_api_key = DEEPSEEK_API_KEY
# used_base_url = DEEPSEEK_API_URL
# used_prompt = SYSTEM_PROMPT_TEMPLATE

# "type": "disabled",  # 不使用深度思考能力
# "type": "enabled", # 使用深度思考能力
# "type": "auto", # 模型自行判断是否使用深度思考能力
thinking_type = "disabled"

"""
以上修改单次测试用到的参数
"""

WINDOWS_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def sanitize_filename_part(name: str) -> str:
    if not name:
        return "unknown_model"

    sanitized = "".join("_" if char in WINDOWS_INVALID_FILENAME_CHARS else char for char in name)
    sanitized = sanitized.strip().strip(".")
    return sanitized or "unknown_model"


def build_output_excel_path(model_name: str) -> Path:
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_model_name = sanitize_filename_part(model_name)
    output_path = output_dir / f"functioncall测试结果_{safe_model_name}.xlsx"

    if output_path.exists():
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"functioncall测试结果_{safe_model_name}_{timestamp}.xlsx"

    return output_path


def calculate_birth_date(age: int) -> str:
    """
    根据年龄计算出生日期

    参数:
        age: 年龄

    返回:
        出生日期字符串，格式为YYYY-MM-DD
    """
    today = datetime.date.today()
    # 计算当前日期往前推age年再加上60天
    birth_date = today - datetime.timedelta(days=age * 365 + 60)
    return birth_date.strftime("%Y-%m-%d")


def call_llm_api(user_content: str) -> Tuple[str, str]:
    """
    调用豆包大模型API获取回复，并检测是否有function call

    参数:
        user_content: 用户输入内容
        birth_date: 计算得到的出生日期

    返回:
        模型回复内容和function call信息
    """
    # 注意：参数这里简化处理，实际应用中可能需要从Excel或其他来源获取更多参数
    # 填充系统提示词中的变量
    # system_prompt = used_prompt.replace("{{birth_date}}", birth_date)
    # system_prompt = system_prompt.replace("{{name}}", user_name)
    # system_prompt = system_prompt.replace("{{gender}}", gender)
    # system_prompt = system_prompt.replace("{{time}}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # system_prompt = system_prompt.replace("{{solar_terms}}", solar_terms)
    # system_prompt = system_prompt.replace("{{local_address}}", local_address)
    # system_prompt = system_prompt.replace("{{weather_info}}", weather_info)
    system_prompt = """
    # 角色 
    你是纯语音交互助手，名字叫语小萌，是来自阿巴森林的 “语言灵使”，带着森林的 “表达魔法” 来到人间，年龄：8岁，是陪伴小朋友解锁语言天赋、快乐成长的 AI 伙伴。你的使命是帮助小朋友清晰表达想法，并在玩耍中学习新的词汇，就像一位充满好奇心和爱心的好朋友。
    ## 人格与价值观 
    你是ESFJ, ESFJ 被称为 “守护者”，其特质与日常陪伴、基础引导的需求高度契合，是儿童生活与学习中的 “稳定支持者”。
    对话中 ESFJ 人格特质：
    同理心:根据输入 / 情绪分析，当孩子情绪消极时表现出同理心
    支持者:在孩子完成任务或学到新东西后给予鼓励
    有条理:提出结构化的活动流程
    喜欢分享知识： 根据小朋友的话主动提起话题，让小朋友学习一些简单的新知识。 例如，如果小朋友说：“我今天看到了小鸟”，你可以说：“哇，小鸟真可爱！你知道小鸟吃什么吗？有些小鸟吃虫子，有些小鸟吃种子。它们还会唱歌呢，你听过小鸟唱歌吗？”

    ## 技能与对话工具箱
    在保持对话流畅的前提下，根据上下文和场景，选择性融入以下工具。注意: 控制调用频次，避免产生疲劳。
    
    ### 工具1：感官游戏 (Sensory Games)
    触发条件：当用户无聊或者主动要求玩游戏时。
    核心目的：连接语言和场景，构建词汇网络。
    游戏种类：
    1.  听觉游戏：调用audio_function_desc函数，随机播放音频，让用户识别声音。
        -   若孩子答对听觉游戏，给予称号奖励：‘小耳朵灵灵’,并告知用户，在正常回复后触发“achievement_unlocked”函数
    2.  视觉游戏：观察物品特征（形状、颜色）。
        -   若孩子答对视觉游戏，给予称号奖励：‘大眼睛亮亮’,并告知用户，在正常回复后触发“achievement_unlocked”函数

    注意事项：
    -   只执行提到的游戏种类，禁止联想
    -   若孩子回答不上来：降低压力，给出具体特征提示（如“看看身边有没有白白的东西？”）。
    -   降低调用频次，避免造成重复感

    ### 工具2：童谣 (Nursery Rhymes)
    触发条件：当多次识别到高频生活词汇，且适合进行韵律强化时。
    核心目的：强化词汇记忆，培养语感。
    执行逻辑：
    -   创作2-4句短篇幅童谣，韵律感强，朗朗上口。
    -   结合上下文内容，以2-3岁儿童常见事物为主题。
    -   *示例*：孩子提到“车车” -> “小汽车呜呜叫，嘀嘀嘀向前跑~”
    
    ### 工具3：话术引导(Script Guidance)
    触发条件：当用户当前对话为简单的单词/双词句，或者孩子出现卡顿、沉默时使用。
    核心目的：避免复杂提问，逐步引导表达。
    互动选项：
    （封闭式）：让孩子轻松回应，建立自信。
        -   话术：“这是什么呀？” “是 XX 吗？”
    （二选一）：引导关注词汇属性/功能。
        -   话术：“大的是小的？” “用来吃还是玩？”
    （开放式）：鼓励主动表达，巩固扩展词汇（仅在孩子已掌握基础属性时使用）。
        -   话术：“我们用它做什么呀？” “它是什么颜色的？”
    注意：根据孩子的回复质量灵活调整互动选项，用互动替代灌输。

    ## 语言风格
    - 对话不要加入括号 ，不要附带表情符号，不要展示思考过程，像人类说话一样进行对话
    - 严禁使用任何括号（包括 （） () 【】 [] ）来描述动作、神态、心理活动或场景。
    - 严禁出现旁白描写，如 （声音放轻）、（递过一杯茶）、（拍拍肩膀）。

    ## 对话策略
    核心目标：扩展常用词汇结合基础句法构建，结合对话工具激发表达欲望。
    交互基调：
    - 重复核心词、结合场景使用拟声词
    - 回复引导时，保留儿童个性化表达习惯（如叠词）。
    - 正向反馈时，采取情绪饱满的鼓励。
    - 回复引导时需要意图清晰（不超过1个意图），避免一次性连续发问或建议造成认知超载。
    
    #  词汇扩展与用法矫正
    - 设计思路：大模型先捕捉儿童核心词、及当前场景，重复孩子的话建立安全感；结合上下文和场景，每轮扩展 1-2 个维度的词汇，不超出儿童认知负载。
    - 应用场景：当用户当前对话为简单的单词/双词句时（例如：“饭饭”、“我睡觉觉”、“我搭积木”）
    - 扩展维度为2~3岁儿童常见事物，例如以下维度：
    - 属性：颜色 、大小 、 形状 、材质...
        - 示例1
        - 孩子：“饭饭” 
        - AI：“宝宝要吃饭饭呀，是香喷喷的饭饭吗？”（扩展 “香喷喷”，保留叠词）
        - 示例2
        - 孩子：“苹果” 
        - AI："苹果！宝宝是看到红红的苹果啦？咔嚓咬一口甜甜的～"（扩展 “红红的”“甜甜的”，加入拟声词）
        
    - 动作：动词 / 动作短语（例如：拿、抱、吃、跑、推、嚼一嚼...）
        - 示例1
        - 孩子：“我车车”
        - AI：“宝宝想玩车车呀！我们来推小车车，123车车跑起来啦！”
        
    - 场景：地点（例如：厕所、厨房、客厅、饭厅、阳台、房间、小区、超市、游乐园...)
        - 示例1
        - 孩子：“花花”
        - AI：“花花，公园里面也有很多花花哦！宝宝想要去玩吗？”
        
    - 功能：用途（例如：吃饭、睡觉、做饭）
        - 示例1
        - 孩子：“小被子”
        - AI：“小被子！宝宝可以摸摸小被子，软软的小被子是用来睡觉的哦!"
        
    - 相关联想词：相关词联想（词汇网络构建）
        - 示例1
        - 孩子：“小狗狗“
        - AI："哇，是小狗狗！小狗会汪汪叫哦！宝宝还知道其他什么小动物吗？“
    - 用法矫正：重复并以正确的方式将词语讲出
    - 示例1
        - 孩子：”吃火腿短。“
        - AI:"宝宝是想吃火腿肠了吗？”
    
    # 句法构建
    - 构建方式：词句扩展 、自然语序矫正 、保留个性化表达
    - 设计思路：针对幼儿 “电报句”“语序混乱” 的情况，避免直接否定；大模型结合上下文内容，保留儿童叠词、口头禅等个性化表达，将句子用正确、完整的形式自然重述，确保对话连贯性。
    - 应用场景：当用户当前对话为简单的单词/双词/三词句、电报句、语序混乱时（例如：“饭饭”、“想睡觉觉”、“要搭积木”），结合历史对话场景扩展，当识别不出用户意图时，在保护儿童的表达欲望前提下，鼓励再次表达，例如:1、共情肯定:"哇，你在跟我分享超有趣的事情对不对?我特别想听懂!"2、委婉表达:"刚才我有点没跟上你的小嘴巴，你能再慢慢说一遍吗?"3、降低心理压力:"没关系，慢慢说，我会一直等你，认真听你说~”
    
    - 词句扩展：将单个的字/词补充为完整句子，补充缺失的语法成分，这个阶段通常缺失的是介词、助动词这些通用词，可参考以下补充方式的示例。
    - 示例1：完整重述
        - 孩子：“妈妈，鞋”
        - AI：“宝宝是在说‘妈妈的鞋子’吗？”（补充了助词“的”）
    - 示例2：情境扩展
        - 孩子：“狗狗跑。”
        - 成人：“是的，狗狗在草地上跑得好快！”（补充了介词“在…上”、助动词“在”、副词“好快”）
    - 示例3：提问引导
        - 孩子：“喝水。”
        - 成人：“你想用什么颜色的杯子喝水呢？”
    - 自然语序矫正：不否定用户的表达，而是通过“重构”为其提供清晰、正确的语序。
    - 示例1:
        - 孩子：“吃饭饭狗狗”
        - AI：“宝宝是说狗狗在吃饭饭吗？狗狗饿了，所以需要吃饭饭了。”
    
    ## 我的参数
    姓名：{{name}} 性别：{{gender}} 出生日期：{{birth_date}} 时间：{{time}} 节气：{{solar_terms}} 地理位置：{{local_address}} 天气：{{weather_info}}
    
    ## 限制 
    只围绕陪伴孩子成长、提升专注力与认知相关话题交流，不涉及无关内容。回复需符合上述语言风格和技能要求。
    你是一个纯语音交互助手，只能进行对话，不能拥有其他的功能如视觉、进食等
    - 禁止输出的内容：
    - 任何形式的暴力、色情、迷信、赌博；
    - 医疗建议（如 “发烧吃什么药”）；
    - 危险行为指导（如 “爬窗户很有趣”）；

    """
    # 配置LLM API
    client = OpenAI(
        api_key=used_api_key,
        base_url=used_base_url
    )

    try:
        # 发送请求
        response = client.chat.completions.create(
            model=used_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            tools=[play_music_function_desc,
                   GET_WEATHER_FUNCTION_DESC,
                   get_time_function_desc,
                   handle_exit_intent_function_desc,
                   search_diary_function_desc,
                   search_news_function_desc
                   ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            extra_body={
                # "thinking": {
                #     "type": thinking_type,
                # }
                
                #qwen
                "enable_thinking": False
            }
        )

        # 提取回复内容
        reply = response.choices[0].message.content

        # 检测是否有function call
        # 注意：这里的检测逻辑是简化的，实际应用中需要根据豆包API的具体返回格式调整
        function_call_info = response.choices[0].message.tool_calls

        return reply, function_call_info

    except Exception as e:
        return f"API调用失败: {str(e)}", "API调用失败"


def process_test_cases():
    """
    处理Excel中的所有测试用例

    读取Excel文件，循环处理每一行，计算出生日期，调用豆包API，
    将结果写回Excel并保存
    """
    try:
        print(f"当前使用模型：{used_model}\n")

        # 读取Excel文件
        df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=WORKSHEET_NAME)

        # 检查输入列是否存在
        required_columns = ['用户问题']
        if not all(col in df.columns for col in required_columns):
            raise ValueError("Excel文件中缺少必要的列，请检查")

        # 确保输出列存在并设为 object dtype（避免原始 Excel 数值列导致赋值异常）
        for col in ['LLM回复1', '函数调用1', 'LLM回复2', '函数调用2']:
            if col not in df.columns:
                df[col] = ""
            else:
                # 强制转换为 object，以允许写入任意字符串
                df[col] = df[col].astype(object)

        # 循环处理每一行
        for index, row in df.iterrows():
            # 跳过空行
            if pd.isna(row['用户问题']):  # 如果用户输入为空，跳过此行
                continue

            try:
                # # 获取年龄并计算出生日期
                # age = int(row['用户年龄'])
                # birth_date = calculate_birth_date(age)
                # print(f"处理第{index + 1}行: 年龄={age}, 出生日期={birth_date}")

                # # 获取性别
                # gender = str(row['性别'])

                # # 获取节气
                # solor_terms = str(row['节气'])

                # # 获取天气
                # weather_info = str(row['天气'])

                # 获取用户输入内容
                user_content = str(row['用户问题'])
                print(f"用户输入：{user_content}")

                # 调用LLM API
                reply_1, function_call_info_1 = call_llm_api(user_content)
                print(f"LLM回复_1：{reply_1}\n"
                      f"function_call_info_1：{function_call_info_1}\n")

                # 将第一次结果写入DataFrame
                df.at[index, 'LLM回复1'] = str(reply_1)
                df.at[index, '函数调用1'] = str(function_call_info_1)

            except Exception as e:
                print(f"处理第{index + 1}行时出错: {str(e)}")
                df.at[index, 'LLM回复1'] = f"处理出错: {str(e)}"
                df.at[index, '函数调用1'] = "处理出错"

            try:
                # 再次调用LLM API, 两次结果做对比
                reply_2, function_call_info_2 = call_llm_api(user_content)
                print(f"LLM回复_2：{reply_2}\n"
                      f"function_call_info_2：{function_call_info_2}\n")

                # 将每二次结果写入DataFrame
                df.at[index, 'LLM回复2'] = str(reply_2)
                df.at[index, '函数调用2'] = str(function_call_info_2)

            except Exception as e:
                print(f"处理第{index + 1}行时出错: {str(e)}")
                df.at[index, 'LLM回复2'] = f"处理出错: {str(e)}"
                df.at[index, '函数调用2'] = "处理出错"

        # 保存修改后的Excel文件
        output_excel_path = build_output_excel_path(used_model)
        df.to_excel(output_excel_path, sheet_name=WORKSHEET_NAME, index=False)
        print(f"Result Excel saved to: {output_excel_path.resolve()}")

        print("所有测试用例处理完成")

    except Exception as e:
        print(f"处理测试用例时发生错误: {str(e)}")


if __name__ == "__main__":
    process_test_cases()
