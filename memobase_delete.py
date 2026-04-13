from memobase import MemoBaseClient, ChatBlob
from memobase.utils import string_to_uuid

## 9626775f-9697-4cf4-b150-9d58767ae686

# 本地Docker环境的默认配置

client = MemoBaseClient(

    project_url="http://localhost:8019",  # 根据API_EXPORT_PORT配置调整

    api_key="secret",  # 默认的ACCESS_TOKEN

)
# 测试连接是否成功
print(client.ping())
print(client.delete_user('46cb5654-6824-4932-94c9-557a2e9e9277'))