from memobase import MemoBaseClient, ChatBlob
from memobase.utils import string_to_uuid

## 9626775f-9697-4cf4-b150-9d58767ae686

# 本地Docker环境的默认配置  

client = MemoBaseClient(

    # project_url="http://192.168.112.192:8019",  # 根据API_EXPORT_PORT配置调整
    project_url="http://localhost:8019",

    api_key="secret",  # 默认的ACCESS_TOKEN

)
# user = client.get_user('9626775f-9697-4cf4-b150-9d58767ae686')

user = client.get_user('c81094f2-e951-4f6f-b032-d90e8712e03c')
user_input = input("请输入:")
# 将用户输入转换为OpenAICompatibleMessage要求的格式：包含role和content字段的字典列表
chat = [{"role": "user", "content": user_input}]

results = user.context(
    max_token_size=1024, 
    chats=chat, 
    profile_event_ratio=0.6, 
    # allow profile matches as well (previously forced only-search-event which hid profile data)
    full_profile_and_only_search_event=True,
    # 0.0 is falsy in the client query builder and will be omitted; use a tiny positive value
    event_similarity_threshold=0.5,
    # time_range_in_days=3650,
    require_event_summary=False,
    customize_context_prompt="## 用户经历的事件:[{event_section}]",
    fill_window_with_events=True
    )
print(results)
# print(user.search_event("养猫"))


# results = user.search_event_gist(query=user_input,similarity_threshold=0.2)
# for item in results:  
#     # 提取核心字段
#     score = item.similarity
#     content = item.gist_data.content

#     # 格式化输出：保留6位小数的相似度，并打印内容
#     print(f"[相似度: {score:.6f}] {content}")
# # print(client.add_user(id="normal_user"))