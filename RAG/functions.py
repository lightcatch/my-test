"""
function 定义文件(用户手动维护)
================================

请在本文件中以 OpenAI tools 格式的 Python dict 定义你的 function,
每个变量名建议以 `_desc` 结尾(便于在没有 ALL_FUNCTIONS 时被自动扫描发现)。

格式约定(必须):
    {
        "type": "function",
        "function": {
            "name": "<函数名>",
            "description": "<函数用途的中文说明,RAG 检索的主要依据>",
            "parameters": { ... JSON Schema ... },
        },
    }

文件末尾必须用 ALL_FUNCTIONS 列表显式汇总所有 function,例如:
    ALL_FUNCTIONS = [play_music_desc, get_weather_desc, ...]

下面给出两个示例,你可以删除/替换它们,然后填入自己的 function。
"""

# ---------------- 示例 function ----------------
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
        "description": "获取今天日期或者当前时间信息",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

exit_function_desc = {
    "type": "function",
    "function": {
        "name": "exit_function",
        "description": """
        "当用户表达出明确的退出、终止、告别或结束当前完整对话会话的意图时，必须调用此函数。触发示例：'退下吧'、'不聊了'、'结束对话'、'再见'、'你可以休息了'、'关闭'。注意拦截误触：如果用户只是要求停止当前正在执行的某个具体小任务（如：'别画了'、'取消这个操作'、'换个话题'），而不是要完全离开，则【不要】调用此函数。"

        """,
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


audio_function_desc = {
    "type": "function",
    "function": {
        "name": "audio_game",
        "description": (
            "当需要进行听觉游戏或者当用户想要进行听觉游戏时，向用户确认后再触发此功能，默认不传入声音名称"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "trigger": {
                    "type": "boolean",
                    "description": "是否随机触发听觉游戏",
                },
                "audio_name": {
                    "type": "string",
                    "description": "当用户没听清或者想要重复播放的时候，传入上次播放的音频名称",
                }
            },
            "required": ["trigger"],
        },
    },
}

achievement_function_desc = {
    "type": "function",
    "function": {
        "name": "achievement_unlocked",
        "description": (
            "当用户完成了游戏且触发了称号奖励时，在进行正常的回复后触发此函数，限制：用户主动需要成就时不触发"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["小耳朵灵灵", "大眼睛亮亮","小小表演家","故事小作家","分类小达人","童谣传唱家","推理大师","接龙高手","超级辩手"],
                    "description": "称号名称",
                }
            },
            "required": ["name"],
        },
    },
}

# 日记查询
search_diary_function_desc = {
    "type": "function",
    "function": {
        "name": "search_diary",
        "description": (
            """
            用户想回忆、重温、复述存储的日记内容，表现为：
                - 对话中提到以下相关内容：‘那篇XXX’‘XXX文章’‘XXX日记’‘那封信’‘那首诗’
                - 助手回复了用户相关的文章、日记后，用户想要重温、复述完整日记内容
            如果用户要查询的具体日期不明确，再次向用户确认
            """
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search_date": {
                    "type": "string",
                    "description": "查询的日记的具体日期。仅当完全确定用户想要查询的具体日期时才填写此属性，否则为空。",
                },
                "search_start_date": {
                    "type": "string",
                    "description": "用户想要查询的起始日期（北京时间）。如用户提到要查询的范围为上周，则为上周一的时间。如用户提到要查询的范围为上个月，则为上个月的第一天",
                },
                "search_end_date": {
                    "type": "string",
                    "description": "用户想要查询的结束日期（北京时间）。如用户提到要查询的范围为上周，则为上周日的时间。如用户提到要查询的范围为上个月，则为上个月的最后一天",
                }
            },
        },
    },
}





##ai抱枕



#播放音乐
play_music_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": (
            """
            播放歌曲
            """
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": 
                    """
                        可供播放的音乐名单(如果有多个对应歌曲,随机选取一个):
                        | 类型 | 意图 | 歌曲名 |
                        | **流行** | 哄睡 / 当用户说xx的时候 | *落花流水* |
                        | **爵士** | 激昂 / 营造氛围 | *任我行* |
                    """
                },
                "reply":{
                    "type": "string",
                    "description": 
                    """
                    如果用户想听的音乐没有在音乐名单里,则向用户推荐其他类型的歌曲进行二次确认.
                    如果已经播放,则告诉用户播放了什么歌，回复要拟人化，符合自身人设
                    """
                },
                "double_check":{
                    "type":"boolean",
                     "description":
                        """
                        当向用户进行二次确认的时候置为true.若否,则为false
                        """
                }

                
            },
        },
    },
}

#讲故事
play_story_desc = {
    "type": "function",
    "function": {
        "name": "play_story",
        "description": (
            """
            播放EHCO亲身经历的故事，当用户表达想听EHCO亲身经历的故事的时候，调用此函数播放故事库故事。
            注意：只限定于用户表达想听EHCO亲身经历的故事时触发此函数，其他讲故事场景不触发
            """
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "story": {
                    "type": "boolean",
                    "description": "触发此函数时置为true"
                },

            },
        },
    },
}



#调整音量
change_sound_desc = {
    "type": "function",
    "function": {
        "name": "change_sound",
        "description": (
            """
           调整音量的大小
            """
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": """
                    正负的数值：
                    当用户需要调大时为：+20%
                    当用户需要调小时为：-20%
                    当用户需要设定特定数值时为: x%
                    当用户需要调整为最大时：100%
                    当用户需要调整为最小时：0%
                    """
                },
                "reply":{
                    "type": "string",
                    "description": 
                    """
                    ai回复的内容
                    """
                }                
                
            },
        },
    },
}


# ---------------- 汇总(必填) ----------------
# 在这里把上面定义的所有 function 变量加入列表,RAG 索引会基于此列表构建。
# 同名 function(function.name 相同)会被 retrieve_tools 自动去重,
# 只保留下方列表中"靠前"出现的那个。
ALL_FUNCTIONS = [
    GET_WEATHER_FUNCTION_DESC,
    get_time_function_desc,
    exit_function_desc,
    search_news_function_desc,
    audio_function_desc,
    achievement_function_desc,
    search_diary_function_desc,
    # —— AI 抱枕版本 ——
    play_music_desc,
    play_story_desc,
    change_sound_desc,
]
