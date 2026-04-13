from time import sleep
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
print(client.add_user())
# # print(client.delete_user("399a319a-5f82-4783-8199-fd5f49661c91"))
# user_id = "399a319a-5f82-4783-8199-fd5f49661c91"
# # add_user first positional argument is `data`, not `user_id`.
# # get_or_create_user keeps this script idempotent across repeated runs.

# # print(client.delete_user(user_id))
# print(client.get_or_create_user(user_id))

# user=client.get_user('c81094f2-e951-4f6f-b032-d90e8712e03c')

# chatB=ChatBlob(messages=[
# {"role": "user", "content": "我叫王佳，今年 27 岁啦"},{"role": "assistant", "content": "王佳这个名字真好听，27 岁正是意气风发的阶段呢"},{"role": "user", "content": "我的生日是 1997-09-03，农历是丁丑年七月三十"},{"role": "assistant", "content": "农历生日记得这么清楚，七月底的生日刚好快到秋天了"},{"role": "user", "content": "平时下班会去瑜伽馆，练完感觉整个人都放松了"},{"role": "assistant", "content": "瑜伽确实能缓解工作压力，坚持下来效果肯定特别好"},{"role": "user", "content": "周末喜欢去周边的古镇逛逛，人不多还能感受慢生活"},{"role": "assistant", "content": "古镇的氛围确实舒服，比起热闹的景区，这种地方更治愈"},{"role": "user", "content": "我做饭偏爱清淡口，比如清炒时蔬、冬瓜丸子汤这些"},{"role": "assistant", "content": "清淡饮食很健康呀，冬瓜丸子汤听着就鲜美好喝"},{"role": "user", "content": "不太能接受太辣的食物，吃一点就容易上火"},{"role": "assistant", "content": "确实，每个人的肠胃耐受度不一样，清淡口也有很多美味"},{"role": "user", "content": "休息的时候喜欢看纪录片，尤其是自然和历史题材的"},{"role": "assistant", "content": "自然和历史纪录片特别涨知识，我也经常看这类内容"},{"role": "user", "content": "平时和朋友聚会，更爱去咖啡馆聊聊天，不太喜欢吵闹的地方"},{"role": "assistant", "content": "咖啡馆的氛围确实适合聊天，安安静静的很惬意"},{"role": "user", "content": "我养了一只布偶猫，叫糯米，每天下班回家它都会蹭我"},{"role": "assistant", "content": "布偶猫也太可爱了吧，糯米这个名字和它很配呀"},{"role": "user", "content": "最近在学插花，虽然刚开始练，但是觉得很有意思"},{"role": "assistant", "content": "插花是很雅致的爱好呢，慢慢练肯定能插出好看的作品"},{"role": "user", "content": "我平时出门优先选地铁，不用堵车，还能顺便刷会儿手机"},{"role": "assistant", "content": "地铁确实是城市里最省心的出行方式，不堵车还准时"},{"role": "user", "content": "喜欢喝手冲咖啡，觉得比速溶的香味更浓郁"},{"role": "assistant", "content": "手冲咖啡的仪式感和香气确实不一样，很懂生活呀"},{"role": "user", "content": "正在研究数据分析，用 Python 处理数据还挺有成就感的"},{"role": "assistant", "content": "Python 做数据分析确实高效，能感受到解决问题的快乐"},{"role": "user", "content": "我特别喜欢读科幻小说，尤其是刘慈欣的作品"},{"role": "assistant", "content": "刘慈欣的科幻小说格局太大了，读起来特别震撼"},{"role": "user", "content": "不太喜欢熬夜，就算周末也会尽量在 11 点前睡觉"},{"role": "assistant", "content": "规律作息太重要了，这样第二天精神状态肯定特别好"},{"role": "user", "content": "家里种了几盆薄荷，偶尔会摘几片泡水泡茶喝"},{"role": "assistant", "content": "薄荷泡茶清凉解腻，自己种的还能随时取用，太方便了"},{"role": "user", "content": "平时喜欢玩拼图，上千片的那种，拼完特别有满足感"},{"role": "assistant", "content": "上千片的拼图很考验耐心呢，完成后的成就感肯定爆棚"}
# ])

# # print(user.get("ff78edf4-6c73-438c-b694-1ad2b9cc49e8"))

# print(user.insert(chatB))
# print(user.flush())
