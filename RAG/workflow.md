# RAG Function 召回系统全流程

## 一、整体目标

把 `functions.py` 里所有 OpenAI tools 格式的 function 入库,运行时根据用户的一句话,从全部 function 里**召回最相关的 Top-K 个**,再把这 K 个交给 LLM。这样 LLM 不用面对全量 tools,token 省、选得也更准。

整个系统分两个阶段:**索引构建(离线,一次性)** 和 **检索查询(在线,每次提问触发)**。

---

## 二、文件结构

```
RAG/
├── functions.py        # 用户手动维护的 function 字典 + ALL_FUNCTIONS 汇总
├── rag_function.py     # 全部逻辑:加载 → 切片 → 向量化 → 多路召回 → 检索 → 交互
├── workflow.md         # 本文件
└── data/               # 运行时自动生成
    ├── chroma_functions/    # Chroma 向量库(持久化)
    └── functions_docs.pkl   # Document 切片缓存(BM25 复用)
```

---

## 三、阶段 1:索引构建(`build`)

入口命令:`uv run python -m RAG.rag_function build`

调用链:`build_index()` → 串起下面 4 步

### 1) `load_functions()` —— 读取 function

- 动态 `import RAG.functions`,优先取 `ALL_FUNCTIONS`,缺失则扫描 `*_desc` 兜底
- 对每个 dict 做结构校验(必须有 `type=function`、`function.name`、`function.description`、`function.parameters`),不合法立刻报错并指出第几个

### 2) `functions_to_documents()` —— 切片

每个 function 整体作为**一个 chunk**(因为 function 描述都不长,拆开反而割裂语义)。

`function_to_text()` 把一个 function 拼成检索文本:

```
函数名: play_music
功能描述: 播放歌曲
参数:
- song_name(string): 可供播放的音乐名单...
- reply(string): 如果用户想听的音乐没有...
- double_check(boolean): 当向用户进行二次确认...
```

包成 `Document(page_content=上述文本, metadata={"function_name": "play_music", "tool_json": <原始 dict 的 JSON>})`。

**关键设计**:`tool_json` 里冗余存了原始 OpenAI tools dict —— 召回回来直接 `json.loads` 还原,完全不用在向量库外维护第二份索引。

### 3) `build_embeddings()` —— 准备 embedding 模型

加载 `BAAI/bge-m3`(本地 HuggingFace,首次下载 ~2.3GB),开启向量归一化。

### 4) `build_vector_store()` —— 写入 Chroma

- 先 `shutil.rmtree(PERSIST_DIR)`,保证旧索引不残留
- `Chroma.from_documents(...)` 把所有 Document 全部 embedding 后写入 `data/chroma_functions/`
- 同时把 docs `pickle.dump` 到 `functions_docs.pkl` —— BM25 不需要向量,启动时直接加载这个文件就够了,**避免每次启动重切片**

构建完毕,磁盘上留下两份产物:**Chroma 向量库** + **切片 pickle**。

## 四、阶段 2:检索查询(`chat` 或 `query`)

入口命令:`uv run python -m RAG.rag_function chat`

### 1) `interactive_chat()` —— 交互聊天栏

启动时**只加载一次** retriever,后续每轮 query 复用,避免重复读盘:

```
[初始化] 正在加载向量库与 BM25 索引,请稍候 ...
[就绪]
你> _
```

支持指令:`:quit` / `:exit` 退出、`:k 3` 调整 top_k、`:help` 帮助、`Ctrl+C` 安全退出。

### 2) `get_retriever()` —— 组装多路召回器(只跑一次)

```
build_embeddings()        # 加载 bge-m3 模型(常驻内存)
        ↓
load_vector_store()       # 只读打开 Chroma 向量库
        ↓
load_cached_docs()        # 反序列化 functions_docs.pkl
        ↓
build_bm25_retriever(docs)        build_vector_retriever(vector_store)
        ↓                                ↓
        └────  build_ensemble_retriever  ────┘
                          ↓
                   EnsembleRetriever
```

两路召回的差异:

| 路 | 实现 | 长处 | 短处 |
|----|------|------|------|
| **向量(语义)** | bge-m3 把 query 和 doc 都转成向量,Chroma 取余弦相似 Top-K | 同义/换说法也能命中(例:"放首歌" → `play_music`) | 命中专有名词的能力一般 |
| **BM25(关键词)** | jieba 分词后做 TF-IDF 类计分 | 字面命中强(例:用户原话出现"天气"直接命中 `get_weather`) | 不会语义泛化 |

**注意**:中文 BM25 必须传 `preprocess_func=jieba.lcut`,否则默认按空格分词,中文几乎全失效 —— 这点在 `_jieba_preprocess` 里已经处理。

EnsembleRetriever 把两路结果用 RRF(Reciprocal Rank Fusion)加权合并,默认权重 `(0.4, 0.6)` —— 向量略高,语义为主,BM25 兜底。

### 3) `retrieve_tools()` —— 实际调用

每轮用户输入触发:

```python
docs = retriever.invoke(query)     # 多路召回,合并去重排序
                ↓
遍历 docs,按 function_name 去重(同名只保留首个)
                ↓
json.loads(doc.metadata["tool_json"]) 还原原始 OpenAI tools dict
                ↓
截断到 top_k,返回 list[dict]
```

返回的 list 可以**直接**塞给 OpenAI / 豆包 / 千问 等 SDK 的 `tools=` 参数,无需再加工。

### 4) 终端输出格式

```
你> 我想退出
召回 4 个 function:
  [1] exit_function — 当用户有明确退出此对话的意图的时候调用此函数
  [2] change_sound — 调整音量的大小
  [3] ...
```

---

## 五、典型一次提问的内部时间线

用户输入 `"放首歌听听"` 后发生的事:

1. `interactive_chat` 拿到字符串
2. `retrieve_tools(query, retriever, top_k=4)` 被调
3. EnsembleRetriever 内部并行触发两路:
   - **BM25 路**:`jieba.lcut("放首歌听听")` → `["放", "首歌", "听听"]` → BM25 在所有 docs 上算分 → 取 Top-4
   - **向量路**:bge-m3 把 query 编码成 1024 维向量 → Chroma 余弦相似度 → 取 Top-4
4. 两路结果做 RRF 加权融合,排序合并
5. 遍历融合后的 docs,按 `function_name` 去重,从 `tool_json` 反序列化
6. 截到 4 个,返回给 `_run_query_and_print` 打印

整个过程在已加载的情况下毫秒级完成。第一次 query 会稍慢(jieba 首次 build 词典)。

---

## 六、何时重建索引

**只要 `functions.py` 改动**(新增、删除、修改 description/参数),就需要重新跑一次:

```bash
uv run python -m RAG.rag_function build
```

否则向量库还是旧版本,会查不到新 function 或返回过时描述。`build` 是幂等的,会清空旧库重建。

---

## 七、对外 API(代码集成用)

如果要在主聊天程序里集成,只需要两行:

```python
from RAG.rag_function import get_retriever, retrieve_tools

retriever = get_retriever(top_k=4)            # 进程启动时加载一次
# ...每次用户消息到达:
tools = retrieve_tools(user_msg, retriever=retriever)
# 然后传给 LLM:
client.chat.completions.create(model=..., messages=..., tools=tools, ...)
```

---

## 八、命令速查

| 场景 | 命令(在 `D:\PyCode\test` 项目根执行) |
|------|------|
| 安装依赖 | `uv sync --group rag` |
| 首次/更新索引 | `uv run python -m RAG.rag_function build` |
| 启动交互式聊天栏 | `uv run python -m RAG.rag_function chat` |
| 单次查询(脚本化) | `uv run python -m RAG.rag_function query "我想听歌"` |
