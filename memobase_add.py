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
# print(client.add_user())

user=client.get_user('8e954119-d466-4e8b-9c94-46f81bb6347e')

# chatB=ChatBlob(messages=[
# ])

#{"role": "user", "content": "我叫王佳，今年 27 岁啦"},{"role": "assistant", "content": "王佳这个名字真好听，27 岁正是意气风发的阶段呢"},{"role": "user", "content": "我的生日是 1997-09-03，农历是丁丑年七月三十"},{"role": "assistant", "content": "农历生日记得这么清楚，七月底的生日刚好快到秋天了"},{"role": "user", "content": "平时下班会去瑜伽馆，练完感觉整个人都放松了"},{"role": "assistant", "content": "瑜伽确实能缓解工作压力，坚持下来效果肯定特别好"},{"role": "user", "content": "周末喜欢去周边的古镇逛逛，人不多还能感受慢生活"},{"role": "assistant", "content": "古镇的氛围确实舒服，比起热闹的景区，这种地方更治愈"},{"role": "user", "content": "我做饭偏爱清淡口，比如清炒时蔬、冬瓜丸子汤这些"},{"role": "assistant", "content": "清淡饮食很健康呀，冬瓜丸子汤听着就鲜美好喝"},{"role": "user", "content": "不太能接受太辣的食物，吃一点就容易上火"},{"role": "assistant", "content": "确实，每个人的肠胃耐受度不一样，清淡口也有很多美味"},{"role": "user", "content": "休息的时候喜欢看纪录片，尤其是自然和历史题材的"},{"role": "assistant", "content": "自然和历史纪录片特别涨知识，我也经常看这类内容"},{"role": "user", "content": "平时和朋友聚会，更爱去咖啡馆聊聊天，不太喜欢吵闹的地方"},{"role": "assistant", "content": "咖啡馆的氛围确实适合聊天，安安静静的很惬意"},{"role": "user", "content": "我养了一只布偶猫，叫糯米，每天下班回家它都会蹭我"},{"role": "assistant", "content": "布偶猫也太可爱了吧，糯米这个名字和它很配呀"},{"role": "user", "content": "最近在学插花，虽然刚开始练，但是觉得很有意思"},{"role": "assistant", "content": "插花是很雅致的爱好呢，慢慢练肯定能插出好看的作品"},{"role": "user", "content": "我平时出门优先选地铁，不用堵车，还能顺便刷会儿手机"},{"role": "assistant", "content": "地铁确实是城市里最省心的出行方式，不堵车还准时"},{"role": "user", "content": "喜欢喝手冲咖啡，觉得比速溶的香味更浓郁"},{"role": "assistant", "content": "手冲咖啡的仪式感和香气确实不一样，很懂生活呀"},{"role": "user", "content": "正在研究数据分析，用 Python 处理数据还挺有成就感的"},{"role": "assistant", "content": "Python 做数据分析确实高效，能感受到解决问题的快乐"},{"role": "user", "content": "我特别喜欢读科幻小说，尤其是刘慈欣的作品"},{"role": "assistant", "content": "刘慈欣的科幻小说格局太大了，读起来特别震撼"},{"role": "user", "content": "不太喜欢熬夜，就算周末也会尽量在 11 点前睡觉"},{"role": "assistant", "content": "规律作息太重要了，这样第二天精神状态肯定特别好"},{"role": "user", "content": "家里种了几盆薄荷，偶尔会摘几片泡水泡茶喝"},{"role": "assistant", "content": "薄荷泡茶清凉解腻，自己种的还能随时取用，太方便了"},{"role": "user", "content": "平时喜欢玩拼图，上千片的那种，拼完特别有满足感"},{"role": "assistant", "content": "上千片的拼图很考验耐心呢，完成后的成就感肯定爆棚"}


chatB=ChatBlob(messages=[
{"role": "user", "content": "我叫林悦，今年 26 岁，是一名室内设计师"},
{"role": "assistant", "content": "悦目的悦，名字和职业很搭呢，26 岁正是审美和创意最活跃的时候"},
{"role": "user", "content": "我的生日是 1998-10-12，典型的天秤座，有点选择困难症"},
{"role": "assistant", "content": "天秤座的审美通常都很在线，至于选择困难，大概是因为优秀的选择太多啦"},
{"role": "user", "content": "平时下班喜欢去攀岩馆，向上爬的过程能让我暂时忘掉方案压力"},
{"role": "assistant", "content": "攀岩可是很硬核的解压方式，这种挑战自我的感觉一定非常热血"},
{"role": "user", "content": "周末喜欢去逛各种艺术展，或者是钻进旧书店待一下午"},
{"role": "assistant", "content": "在艺术和文字里寻找灵感，这确实是设计师汲取能量的最好方式"},
{"role": "user", "content": "我吃饭口味偏重，特别喜欢川菜，觉得生活没点辣就没滋味"},
{"role": "assistant", "content": "川菜的香辣确实让人欲罢不能，吃出一身汗的感觉真的爽快"},
{"role": "user", "content": "不太喜欢甜食，甜品对我来说有点过于腻了"},
{"role": "assistant", "content": "理解，咸口党和辣口党通常对甜食的防御力都很高"},
{"role": "user", "content": "休息时爱看烧脑的悬疑剧，尤其是那种多重反转的剧情"},
{"role": "assistant", "content": "跟着导演的思路玩智力游戏确实过瘾，最后揭开真相的那一刻最燃"},
{"role": "user", "content": "社交方面比较被动，更愿意和三五知己在露营地围炉煮茶"},
{"role": "assistant", "content": "露营和煮茶的氛围感拉满了，这种深度的交流比无意义的社交质量高多了"},
{"role": "user", "content": "我养了一只小柯基，叫‘奶酪’，它的小短腿跑起来特别治愈"},
{"role": "assistant", "content": "柯基可是治愈系大师，看到奶酪摇着尾巴接你回家，一天的疲惫都散了"},
{"role": "user", "content": "最近在自学尤克里里，虽然指尖有点疼，但能弹成一首小曲很开心"},
{"role": "assistant", "content": "尤克里里的声音清脆欢快，这种小小的技能增长也是生活里的高光时刻"},
{"role": "user", "content": "出门喜欢骑共享单车，那种穿梭在街道风里的感觉自由自在"},
{"role": "assistant", "content": "骑行是感受城市温度的最佳速度，不快不慢，刚刚好"},
{"role": "user", "content": "比起咖啡更爱喝浓茶，家里常备普洱，觉得回甘的味道很醇厚"},
{"role": "assistant", "content": "年纪轻轻就爱品茶，看来你的内心住着一个通透的老灵魂呀"},
{"role": "user", "content": "正在钻研 AI 绘图，尝试用 Midjourney 来辅助设计构思"},
{"role": "assistant", "content": "紧跟科技前沿呀！AI 工具确实能帮设计师打开很多意想不到的视觉维度"},
{"role": "user", "content": "不喜欢热闹的聚会，更喜欢独处的时候戴上耳机听播客"},
{"role": "assistant", "content": "播客就像是一个人的精神电台，在独处的时间里也能和世界保持连接"},
{"role": "assistant", "content": "这个自律程度太让人佩服了，早起的人确实能比别人多拥有一段清晨的宁静"},
{"role": "user", "content": "家里摆满了各种乐高模型，尤其是建筑系列的，拼起来很有成就感"},
{"role": "assistant", "content": "从零件到宏伟建筑，拼乐高和做设计其实异曲同工，都是从无到有的创造"},
])




# # print(user.get("ff78edf4-6c73-438c-b694-1ad2b9cc49e8"))

print(user.insert(chatB))
print(user.flush())
