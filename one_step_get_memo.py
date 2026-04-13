# from rich import print
from memobase import MemoBaseClient
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from MemoTest.yuxiaomeng_memo_config import (
#                 YXM_LOCAL_PROJECT_URL, YXM_LOCAL_PROJECT_TOKEN, YXM_USER_ID, PROMPT_TEMPLATE_YUXIAOMENG, 
#                 )

# from MemoTest.yibao_memo_config import (
#                 YIBAO_LOCAL_PROJECT_URL, YIBAO_LOCAL_PROJECT_TOKEN, YIBAO_LOCAL_USER_ID, PROMPT_TEMPLATE_YIBAO, YIBAO_EXT_PROJECT_URL, YIBAO_EXT_PROJECT_TOKEN, YIBAO_EXT_USER_ID,
#                 )


# 以下为测试参数
# -----------------------------------------------------------------------------

# project_url = YIBAO_LOCAL_PROJECT_URL
# api_key = YIBAO_LOCAL_PROJECT_TOKEN

# test_user_id = YIBAO_LOCAL_USER_ID


max_token_size = 1000
event_similarity_threshold = '0.2'
# memo_prompt_template = PROMPT_TEMPLATE_YIBAO

# -----------------------------------------------------------------------------
# 测试参数完

def query_memory(user_query: str) -> str:

    context_pramas = {
        "max_token_size": max_token_size,
        "prefer_topics": '',
        "only_topics": '',
        "max_subtopic_size": '',
        "topic_limits": '',
        "profile_event_ratio": '',


        "require_event_summary": '',
        "event_similarity_threshold": event_similarity_threshold,
        "time_range_in_days": '',
        "customize_context_prompt": '## 用户经历的事件:[{event_section}]',
        "full_profile_and_only_search_event": '',
        "fill_window_with_events": '',
    }
    context_pramas = {k: v for k, v in context_pramas.items() if v is not None and v != ''}

    client = MemoBaseClient(

    project_url="http://localhost:8019",  # 根据API_EXPORT_PORT配置调整

    api_key="secret",  # 默认的ACCESS_TOKEN
    )

    # assert client.ping(), "Your Memobase server is not running"
    # print(f"Current Memobase Config：{client.get_config()}")

    try:
        chats_str = [{"role": "user", "content": user_query}]
        u = client.get_user("c81094f2-e951-4f6f-b032-d90e8712e03c")

        # print("\n--------------\nBelow is your blobdata:")
        # print(u.get_all(BlobType.chat))

        # print("\n--------------\nBelow is your profile:")
        # print(u.profile(need_json=False))

        # return_content = u.profile(need_json=True)

        # print("\n--------------\nBelow is your recent events:")
        # print(u.event(topk=100, max_token_size=1000, need_summary=True))

        # print("\n--------------\nBelow is your events by search:")
        # print(u.search_event(user_query))

        # return_content = u.search_event(query=user_query)

        # print("\n--------------\nBelow is your events gists by search:")
        # print(u.search_event_gist(user_query))

        # print("\n--------------\nBelow is your events by tags:")
        # print(u.search_event_by_tags(tags=["美食"]))

        # return_content = u.search_event_gist(query=user_query, similarity_threshold=0.55)

        return_content = u.context(chats=chats_str, **context_pramas)

        return return_content
    except Exception as e:
        print(f"查询记忆失败: {e}")


# 测试代码
if __name__ == "__main__":
    query = input("你想聊什么：")

    # 记录调用记忆体开始时间
    start_time = time.time()

    result = query_memory(query)

    # 计算调用记忆体时间
    end_time = time.time()

    print("\n--------------\nBelow is your context:")
    print(f"""```\n{result}\n```
    """)

    print(f"调用记忆体执行完成，耗时: {end_time - start_time:.6f} 秒")
