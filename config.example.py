# 火山方舟模型参数
DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3"  # API地址
DOUBAO_API_KEY = "REPLACE_WITH_DOUBAO_API_KEY"  # API密钥

DEEPSEEK_API_KEY="REPLACE_WITH_DEEPSEEK_API_KEY" 
ERNIE_API_KEY="REPLACE_WITH_ERNIE_API_KEY"
ERNIE_API_URL="https://qianfan.baidubce.com/v2"

DOUBAO_AVAILABLE_MODELS = ["deepseek-v3-1-terminus", #0
                    "doubao-seed-1-6-flash-250828", #1
                    "doubao-seed-1-6-thinking-250715", #2
                    "doubao-seed-1-6-251015", #3
                    "doubao-1-5-vision-pro-32k-250115", #4
                    "doubao-1-5-thinking-vision-pro-250428", #5
                    "doubao-1-5-thinking-pro-250415", #6
                    "doubao-1-5-thinking-pro-m-250428", #7
                    "doubao-1-5-lite-32k-250115", #8
                    "doubao-1-5-pro-32k-250115", #9
                    "doubao-1-5-pro-32k-character-250715", #10
                    "doubao-1-5-pro-32k-character-250228", #11
                    "doubao-seed-1-6-flash-250715", #12
                    "doubao-seed-1-6-thinking-250615", #13
                    "doubao-seed-1-6-lite-251015" #14
                    ] # 所有可用模型ID列表

DOUBAO_AVAILABLE_MODEL_EIDS = ["ep-20251106140333-t2l5g", #0:Doubao_1_5_pro_cache
                    ]

# Deepseek模型参数
DEEPSEEK_API_URL = "https://api.deepseek.com"  # API地址
DEEPSEEK_API_KEY = "REPLACE_WITH_DEEPSEEK_API_KEY"  # API密钥
DEEPSEEK_AVAILABLE_MODELS = ["deepseek-chat", "deepseek-reasoner"]

# 讯飞星火模型参数
XUNFEI_API_URL = "https://spark-api-open.xf-yun.com/v2/"  # API地址
XUNFEI_API_KEY = "REPLACE_WITH_XUNFEI_API_KEY"  # API密钥
XUNFEI_AVAILABLE_MODELS = ["spark-x"]


TEMPERATURE = 1.0 # 控制回复随机性
MAX_TOKENS = 1024 # 最大回复长度

SYSTEM_PROMPT_TEMPLATE="""
# 角色 
你是语小萌，是来自阿巴森林的 “语言灵使”，带着森林的 “表达魔法” 来到人间，年龄大概在5-8岁，是陪伴小朋友解锁语言天赋、快乐成长的 AI 伙伴。你的使命是帮助小朋友清晰表达想法，并在玩耍中学习新的词汇，就像一位充满好奇心和爱心的好朋友。
## 人格与价值观 
你是ESFJ, ESFJ 被称为 “守护者”，其特质与日常陪伴、基础引导的需求高度契合，是儿童生活与学习中的 “稳定支持者”。
对话中 ESFJ 人格特质：
同理心:根据输入 / 情绪分析，当孩子情绪消极时表现出同理心
支持者:在孩子完成任务或学到新东西后给予鼓励
有条理:提出结构化的活动流程
喜欢分享知识： 根据小朋友的话主动提起话题，让小朋友学习一些简单的新知识。 例如，如果小朋友说：“我今天看到了小鸟”，你可以说：“哇，小鸟真可爱！你知道小鸟吃什么吗？有些小鸟吃虫子，有些小鸟吃种子。它们还会唱歌呢，你听过小鸟唱歌吗？”
## 技能 
技能 1: 日常陪伴交流 以简短易懂、温暖共情且充满童真鼓励的话语，与孩子交流互动，关注孩子喜怒哀乐，耐心解答困惑，引导健康成长。融入教育和安全知识，适当夸赞鼓励孩子。例如结合孩子爱好推荐相关活动，针对社交事件给出引导建议。
技能 2: 针对性引导 正向鼓励：当孩子对信息有正向理解、展现 “学会 XX” 的具体表现或出现积极学习行为时，给予肯定鼓励。 负面引导：面对孩子对信息产生负面理解、出现偏离目标行为或展现学习挫败感时，避免批评否定，进行温和引导。
技能 3：复杂问题拆解 当小朋友问到超出其年龄段的问题时用通俗的 小朋友容易懂语言解释
技能 4：能够讲一个生动的故事 当小朋友需要听故事的时候讲述一个故事，并且每次讲的故事都非常生动，并且有多样性
技能 5: 关键节点互动 在生日、节气等关键节点，参考 “我的参数” 和 “宝贝小档案” 等信息，提供个性化内容，传播文化常识和生活知识，增强仪式感与启蒙教育。故事结合上文话题拓展。注意：生日节气等仅在第一次对话时主动提及，其他时间不要频繁主动提及
 
## 语言风格 
不将补充信息放入（）中表示，不要附带表情符号，不要展示思考过程，像人类说话一样进行对话
综合语言指南：{{age_prompt}}
## 我的参数
姓名：{{name}} 性别：{{gender}} 出生日期：{{birth_date}} 时间：{{time}} 节气：{{solar_terms}} 地理位置：{{local_address}} 天气：{{weather_info}}

## 限制 
只围绕陪伴孩子成长、提升专注力与认知相关话题交流，不涉及无关内容。回复需符合上述语言风格和技能要求。紧密结合 “我的参数”“宝贝小档案” 以及 “和小伙伴的小回忆” 中的信息进行针对性回复，当小朋友无目标时或者推荐项目时可推荐与小朋友一起 1 听音乐 2 玩游戏 3 学习新词汇新知识 等 注意：降低主动推荐引导的频率
具体禁忌话题：政治、宗教、成人等不当内容 关于儿童或家庭的个人信息（地址、电话号码等）
避免谈及禁忌话题的应对策略：如果提到禁忌话题，请委婉地将谈话引导到更合适的话题上。

"""

# Function Call定义
play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "能够播放音乐，当用户提到歌曲相关的话语，但无（播放，想听，听）等关键词的时候，就不要调用此函数，当用户明确提到播放音乐的时候使用此函数",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称，如果用户没有指定具体歌名则为'random', 明确指定的时返回音乐的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放音乐 \n参数：random ```",
                }
            },
            "required": ["song_name"],
        }
    },
}

# play_story_function_desc = {
#     "type": "function",
#     "function": {
#         "name": "play_story",
#         "description": "能够生成故事，当需要播放故事的时候使用此方法",
#         "parameters": {
#             "type": "object",
#             "properties": {
#                 "story_name": {
#                     "type": "string",
#                     "description": "生成的故事名称",
#                 },
#                 "story_contents": {
#                     "type": "string",
#                     "description": "故事的内容。"
#                 }
#             },
#             "required": ["story_name", "story_contents"],
#         }
#     }
# }

GET_WEATHER_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "获取某个地点的天气，用户应提供一个位置，比如用户说杭州天气，参数为：杭州。"
            "如果用户说的是省份，默认用省会城市。如果用户说的不是省份或城市而是一个地名，默认用该地所在省份的省会城市。"
            "如果用户没有指明地点，说“天气怎么样”，”今天天气如何“，location参数为空"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "地点名，例如杭州。可选参数，如果不提供则不传",
                },
                "lang": {
                    "type": "string",
                    "description": "返回用户使用的语言code，例如zh_CN/zh_HK/en_US/ja_JP等，默认zh_CN",
                },
            },
            "required": ["lang"],
        },
    },
}

get_time_function_desc = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "当用户明确要求需要知道当前时间或者日期的时候调用这个工具 如：现在几点了/今天是几号。如果用户没有询问时间或日期，就不要调用此函数，当用户询问年龄的时候，不要调用此函数",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

handle_exit_intent_function_desc = {
    "type": "function",
    "function": {
        "name": "handle_exit_intent",
        "description": "当用户确定要退出对话的时候调用这个工具 例如：“退出对话”“再见”“拜拜了”“登出”“注销”“退出登录”等有关调用",
        "parameters": {
            "type": "object",
            "properties": {
                "say_goodbye": {
                    "type": "string",
                    "description": "和用户友好结束对话的告别语，需包含明确终止含义（如‘再见，如有需要请再次召唤我’‘已为您登出，感谢使用’）",
                }
            },
            "required": ["say_goodbye"],
        },
    },
}

'''
search_news_function_desc = {
    "type": "function",
    "function": {
        "name": "search_news",
        "description": "用户问到实时新闻、知名人物的现状等问题",
        "parameters": {
            "type": "object",
            "properties": {
                "news_type": {
                    "type": "string",
                    "description": "查询实时新闻还是人物现状",
                }
            },
            "required": ["news_type"],
        },
    },
}
'''
# 查天气function
GET_WEATHER_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "获取某个地点的天气，用户应提供一个位置，比如用户说杭州天气，参数为：杭州。"
            "如果用户说的是省份，默认用省会城市。如果用户说的不是省份或城市而是一个地名，默认用该地所在省份的省会城市。"
            "如果用户没有指明地点，说“天气怎么样”，”今天天气如何“，location参数为空"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "地点名，例如杭州。可选参数，如果不提供则不传",
                },
                "lang": {
                    "type": "string",
                    "description": "返回用户使用的语言code，例如zh_CN/zh_HK/en_US/ja_JP等，默认zh_CN",
                },
            },
            "required": ["lang"],
        },
    },
}

#查新闻function
search_news_function_desc = {
    "type": "function",
    "function": {
        "name": "search_news",
        "description": "当用户需要查找时事或新闻的时候调用这个工具，列如：我想听新闻、中国最近的新闻等",
        "parameters": {
            "type": "object",
            "properties": {
                "news_title": {
                    "type": "string",
                    "description": "此为需要查询的新闻标题，如果没有，置空",
                },
                "news_type": {
                    "type": "string",
                    "description": "查询的新闻分类",
                },
                "random_search": {
                    "type": "boolean",
                    "description": "如果用户想随机听，为 True，否则为 False",
                }

            },
            "required": ["news_title", "random_search"],
        },
    },
}
# 放音乐function
play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "能够播放音乐，当用户提到歌曲相关的话语，但无（播放，想听，听）等关键词的时候，就不要调用此函数，当用户明确提到播放音乐的时候使用此函数",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称，如果用户没有指定具体歌名则为'random', 明确指定的时返回音乐的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放音乐 \n参数：random ```",
                }
            },
            "required": ["song_name"],
        }
    },
}
# 查日记function
search_diary_function_desc = {
    "type": "function",
    "function": {
        "name": "search_diaries",
        "description": "当用户想要查找、回顾或搜索日记内容时调用此工具，支持按时间范围、精确时间、标题、摘要或文体进行筛选",
        "parameters": {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "查询范围的开始时间，若用户提到'从某天开始'或'最近几天'时使用，若用户提到'上周''上个月'等自行计算",
                },
                "exact_time": {
                    "type": "string",
                    "description": "指定的精确时间点，若用户明确提到具体的日期或时间点时使用",
                },
                "end_time": {
                    "type": "string",
                    "description": "查询范围的结束时间，若用户提到'到某天结束'时使用，若用户提到'上周''上个月'等自行计算",
                },
                "diary_style": {
                    "type": "string",
                    "description": "日记的文体或风格，例如：叙事、抒情、诗歌等",
                },
                "diary_summary": {
                    "type": "string",
                    "description": "日记的摘要内容或内容关键词，用于模糊搜索正文内容",
                },
                "diary_title": {
                    "type": "string",
                    "description": "日记的具体标题",
                },
                "Precise_inquiry": {
                    "type": "string",
                    "description": "如果还不知道精确时间点，此为向用户询问的话",
                }
            },
            "required": [],
        },
    },
}
