"""
RAG Function 多路召回执行文件
=============================

目标
----
把 `functions.py` 中的 OpenAI tools 格式 function 切片入库,
基于用户输入做"向量(语义) + BM25(关键词)"多路召回,
返回 Top-K 最相关的 function(原始 OpenAI tools dict),
直接可作为 LLM 的 `tools=` 参数。

整体流程
--------
1. load_functions      —— 从 functions.py 读取 function 列表
2. functions_to_documents —— 切片:每个 function 作为一个 chunk
3. build_embeddings    —— 构造 bge-m3 HuggingFace embedding
4. build_vector_store  —— 用 Chroma 做向量索引并持久化
5. build_bm25_retriever —— 基于 jieba 中文分词的 BM25 关键词召回
6. build_vector_retriever —— Chroma 语义召回
7. build_ensemble_retriever —— LangChain EnsembleRetriever 多路加权合并
8. retrieve_tools      —— 检索后从 metadata 反序列化回原始 OpenAI tools dict
9. interactive_chat    —— 终端聊天栏,循环输入 -> Top-K 输出

常用命令(在项目根目录 D:/PyCode/test/ 下,直接复制运行)
----------------------------------------------------------
首次/functions.py 改了之后重建索引:
    python -m RAG.rag_function build

进入交互式聊天栏(三路并排展示 BM25 / 向量 / Ensemble 排名):
    python -m RAG.rag_function chat

单次查询(快速试探用):
    python -m RAG.rag_function query "拜拜"

把所有切片文本导出成可读 .txt(放在 RAG/data/functions_docs.txt):
    python -m RAG.rag_function dump

【评测】生成 50 条用例的 Excel 模板(RAG/data/eval_cases.xlsx,可手动增删):
    python -m RAG.rag_function init-eval

【评测】跑评测,把目标 function 在三路 Top-K 中的排名写到结果 Excel:
    python -m RAG.rag_function eval

【评测】指定输入/输出/top-k 跑评测:
    python -m RAG.rag_function eval --input RAG/data/eval_cases.xlsx --output RAG/data/my_results.xlsx --top-k 4

【评测】常见用法:同一份用例跑两次对比权重影响,先改 DEFAULT_WEIGHTS 再跑:
    python -m RAG.rag_function eval --output RAG/data/results_weights_0.4_0.6.xlsx
    # (改 DEFAULT_WEIGHTS = (0.0, 1.0) 后)
    python -m RAG.rag_function eval --output RAG/data/results_weights_0.0_1.0.xlsx
"""
from __future__ import annotations

import os

# 离线模式:跳过 HuggingFace 联网检查,直接用本地缓存,避免每次启动卡在
# huggingface.co 的 HEAD 请求超时。代价是模型不会自动更新——想升级 bge-m3
# 时,临时把这两个变量删掉、联网跑一次即可。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import datetime
import importlib
import json
import pickle
import shutil
import sys
from pathlib import Path

import jieba
import openpyxl

# EnsembleRetriever 在 langchain 1.x 中迁移到了 langchain_classic;defence

# 这里做一层兼容,新旧版本都能跑。
try:
    from langchain_classic.retrievers import EnsembleRetriever  # type: ignore
except ImportError:  # pragma: no cover
    from langchain.retrievers import EnsembleRetriever  # type: ignore
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings


# ============== 模块常量 ==============

# 当前文件所在目录(D:/PyCode/test/RAG)
_THIS_DIR = Path(__file__).parent.resolve()

# Chroma 持久化目录,数据落盘到 RAG/data/chroma_functions
PERSIST_DIR = _THIS_DIR / "data" / "chroma_functions"

# 切片结果缓存(pickle),BM25 启动时复用,避免每次启动重新切片
DOCS_CACHE = _THIS_DIR / "data" / "functions_docs.pkl"

# 评测用例 / 评测结果 Excel 默认路径
EVAL_CASES_XLSX = _THIS_DIR / "data" / "eval_cases.xlsx"
EVAL_RESULTS_DIR = _THIS_DIR / "data"

# 负向用例的目标 function 占位符:出现这个值表示"应不召回任何 function"
# evaluator 看到此值会跳过排名校验,在结果列填 "N/A"
NO_TARGET_SENTINEL = "__none__"

# embedding 模型名,首次运行会从 HuggingFace 下载(~2.3GB)
EMBEDDING_MODEL = "BAAI/bge-m3"

# Chroma collection 名
COLLECTION_NAME = "rag_functions"

# 默认召回数量
DEFAULT_TOP_K = 5

# EnsembleRetriever 权重 (BM25, 向量),向量略高,语义为主、关键词兜底
DEFAULT_WEIGHTS = (0.4, 0.6)

# functions.py 的 import 路径(相对 D:/PyCode/test 项目根)
DEFAULT_FUNCTIONS_MODULE = "RAG.functions"


# ============== 1. 加载 function ==============

def load_functions(module_path: str = DEFAULT_FUNCTIONS_MODULE) -> list[dict]:
    """
    动态 import functions.py 并取出 function 列表。

    优先读取模块中的 ALL_FUNCTIONS;若不存在则扫描所有以 `_desc`
    结尾的模块属性作为兜底。每个 function 都会做结构校验,
    不符合 OpenAI tools 格式时抛出明确错误,提示具体变量名。

    参数:
        module_path: functions.py 的 import 路径。默认 "RAG.functions",
                     运行时需保证当前工作目录是项目根 D:/PyCode/test。
    返回:
        list[dict]: 经过结构校验的 OpenAI tools dict 列表。
    """
    # 强制重新导入,避免长会话中文件被修改后拿到旧缓存
    if module_path in sys.modules:
        module = importlib.reload(sys.modules[module_path])
    else:
        module = importlib.import_module(module_path)

    # 优先用显式汇总,健壮性最好
    funcs: list[dict] = list(getattr(module, "ALL_FUNCTIONS", []) or [])

    # 兜底:扫描以 _desc 结尾的属性
    if not funcs:
        for name in dir(module):
            if name.endswith("_desc"):
                value = getattr(module, name)
                if isinstance(value, dict):
                    funcs.append(value)

    if not funcs:
        raise ValueError(
            f"在模块 {module_path} 中没有找到任何 function。"
            f"请在 ALL_FUNCTIONS 中显式列出,或使用以 _desc 结尾的变量名。"
        )

    # 逐个校验结构
    for idx, func in enumerate(funcs):
        _validate_function_dict(func, idx)

    return funcs


def _validate_function_dict(func: dict, idx: int) -> None:
    """
    校验单个 function dict 是否符合 OpenAI tools 结构。
    不合法时抛出 ValueError,错误消息中带上下标方便定位。
    """
    if not isinstance(func, dict) or func.get("type") != "function":
        raise ValueError(f"第 {idx} 个 function 缺少 type='function' 顶层字段")
    inner = func.get("function")
    if not isinstance(inner, dict):
        raise ValueError(f"第 {idx} 个 function 缺少 function 子字典")
    for key in ("name", "description", "parameters"):
        if key not in inner:
            raise ValueError(f"第 {idx} 个 function 缺少必填字段: {key}")
    if not isinstance(inner["name"], str) or not inner["name"].strip():
        raise ValueError(f"第 {idx} 个 function 的 name 必须是非空字符串")


# ============== 2. 切片:function -> Document ==============

def function_to_text(func: dict) -> str:
    """
    把单个 function dict 拼成一段适合 embedding 的中文检索文本。

    拼接策略:整个 function 作为一个 chunk,内容包括 name、description、
    每个参数的 name/type/description/enum。这样无论用户 query 命中
    function 名、function 描述还是某个参数说明,都能召回。

    参数:
        func: OpenAI tools 格式的单个 function dict。
    返回:
        str: 拼接好的检索文本。
    """
    inner = func["function"]
    name: str = inner["name"]
    description: str = (inner.get("description") or "").strip()

    # 头部:名称 + 总体描述,权重最高
    parts: list[str] = [f"函数名: {name}", f"功能描述: {description}"]

    # 参数:逐个展开
    params = inner.get("parameters") or {}
    properties: dict = params.get("properties") or {}
    if properties:
        parts.append("参数:")
        for p_name, p_schema in properties.items():
            parts.append(_format_param(p_name, p_schema))

    return "\n".join(parts)


def _format_param(name: str, schema: dict) -> str:
    """把单个参数的 schema 格式化成一行检索文本。"""
    p_type = schema.get("type", "")
    p_desc = (schema.get("description") or "").strip().replace("\n", " ")
    enum = schema.get("enum")
    enum_part = f" 可选值: {enum}" if enum else ""
    return f"- {name}({p_type}): {p_desc}{enum_part}"


def functions_to_documents(funcs: list[dict]) -> list[Document]:
    """
    把 function 列表转成 LangChain Document 列表(切片)。

    metadata 中冗余存原始 OpenAI tools dict 的 JSON 字符串
    (key="tool_json"),召回后零成本反序列化还原,
    避免在向量库外再维护一份索引。

    参数:
        funcs: 经过校验的 function dict 列表。
    返回:
        list[Document]: 每个 function 对应一个 Document。
    """
    docs: list[Document] = []
    for func in funcs:
        text = function_to_text(func)
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "function_name": func["function"]["name"],
                    # 原始 tool 直接 JSON 序列化存进 metadata,
                    # Chroma 的 metadata value 必须是基础类型,
                    # 所以用字符串而不是嵌套 dict
                    "tool_json": json.dumps(func, ensure_ascii=False),
                },
            )
        )
    return docs


# ============== 3. embedding ==============

def build_embeddings(model_name: str = EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    """
    构造 HuggingFace embedding 模型(默认 bge-m3)。

    - device="cpu":不依赖 GPU,任何机器都能跑。如机器有 CUDA,
      可改为 "cuda" 提速。
    - normalize_embeddings=True:输出向量归一化,
      Chroma 默认用余弦相似度,归一化后效果更稳。
    """
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


# ============== 4. 向量库 ==============

def build_vector_store(docs: list[Document], embeddings: HuggingFaceEmbeddings) -> Chroma:
    """
    用 Chroma 重建向量索引并持久化。

    步骤:
      1. 清空旧的 PERSIST_DIR,保证索引和当前 functions.py 一致
      2. Chroma.from_documents 写入 docs
      3. 同步把 docs pickle 到 DOCS_CACHE,供 BM25 启动时复用
         (避免每次启动都要重新切片)

    参数:
        docs: 切片好的 Document 列表。
        embeddings: 已构造的 embedding 模型。
    返回:
        Chroma: 持久化好的向量库实例。
    """
    # 重建模式:先清空,确保不会和旧数据混在一起
    if PERSIST_DIR.exists():
        shutil.rmtree(PERSIST_DIR)
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    vector_store = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory=str(PERSIST_DIR),
        collection_name=COLLECTION_NAME,
    )
    # 新版 langchain-chroma 自动持久化,旧版需要显式 persist
    if hasattr(vector_store, "persist"):
        vector_store.persist()

    # 缓存切片结果,BM25 复用
    DOCS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with DOCS_CACHE.open("wb") as f:
        pickle.dump(docs, f)

    return vector_store


def load_vector_store(embeddings: HuggingFaceEmbeddings) -> Chroma:
    """
    只读加载已经持久化的 Chroma 向量库。

    若 PERSIST_DIR 不存在,提示用户先运行 build。
    """
    if not PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"向量库目录不存在: {PERSIST_DIR}。"
            f"请先运行: python -m RAG.rag_function build"
        )
    return Chroma(
        persist_directory=str(PERSIST_DIR),
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def load_cached_docs() -> list[Document]:
    """
    从 DOCS_CACHE 反序列化切片结果(供 BM25 复用)。
    若缓存不存在,提示先 build。
    """
    if not DOCS_CACHE.exists():
        raise FileNotFoundError(
            f"切片缓存不存在: {DOCS_CACHE}。"
            f"请先运行: python -m RAG.rag_function build"
        )
    with DOCS_CACHE.open("rb") as f:
        return pickle.load(f)


# ============== 5. 多路召回器 ==============

def _jieba_preprocess(text: str) -> list[str]:
    """
    中文分词预处理函数,供 BM25Retriever 使用。
    BM25 默认按空格分词,对中文几乎无效;改用 jieba 分词后,
    "播放音乐"才能切成 ["播放","音乐"],BM25 才能命中相应 token。
    """
    return [tok for tok in jieba.lcut(text) if tok.strip()]


def build_bm25_retriever(docs: list[Document], k: int = DEFAULT_TOP_K) -> BM25Retriever:
    """
    构造基于 jieba 分词的 BM25 关键词召回器。

    参数:
        docs: Document 列表(通常来自 load_cached_docs)。
        k: 单路召回数量。
    返回:
        BM25Retriever: 已配置好分词器的关键词召回器。
    """
    retriever = BM25Retriever.from_documents(
        docs,
        # 必传:中文 BM25 必须用 jieba,否则等同失效
        preprocess_func=_jieba_preprocess,
    )
    retriever.k = k
    return retriever


def build_vector_retriever(vector_store: Chroma, k: int = DEFAULT_TOP_K):
    """
    把 Chroma 向量库包装成 LangChain Retriever,用于 EnsembleRetriever。
    搜索类型默认 similarity,若需要多样性可改为 "mmr"。
    """
    return vector_store.as_retriever(search_kwargs={"k": k})


def build_ensemble_retriever(
    bm25: BM25Retriever,
    vector,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> EnsembleRetriever:
    """
    用 LangChain 的 EnsembleRetriever 把 BM25 与向量召回加权合并。

    weights 含义: (BM25 权重, 向量权重)。默认 (0.4, 0.6)——
    向量略高,语义为主、关键词兜底。可在调用方按数据情况微调。
    """
    return EnsembleRetriever(
        retrievers=[bm25, vector],
        weights=list(weights),
    )


# ============== 6. 对外入口 ==============

def build_index(functions_module: str = DEFAULT_FUNCTIONS_MODULE) -> dict:
    """
    一站式重建 function 索引(向量 + 切片缓存)。

    在以下时机调用:
      - 首次使用
      - functions.py 内容(增/删/改)有更新

    参数:
        functions_module: functions.py 的 import 路径,默认 "RAG.functions"。
    返回:
        dict: 索引统计信息(function 数量、持久化目录等)。
    """
    funcs = load_functions(functions_module)
    docs = functions_to_documents(funcs)
    embeddings = build_embeddings()
    build_vector_store(docs, embeddings)
    return {
        "function_count": len(funcs),
        "function_names": [f["function"]["name"] for f in funcs],
        "persist_dir": str(PERSIST_DIR),
        "docs_cache": str(DOCS_CACHE),
        "embedding_model": EMBEDDING_MODEL,
    }


def get_retriever(
    top_k: int = DEFAULT_TOP_K,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> EnsembleRetriever:
    """
    加载已构建的索引,返回组装好的 EnsembleRetriever(向量 + BM25)。

    交互式聊天/批量调用都建议先用 get_retriever 拿到一个
    retriever 复用,避免每次查询都重新加载向量库与 BM25。
    """
    embeddings = build_embeddings()
    vector_store = load_vector_store(embeddings)
    docs = load_cached_docs()

    # 单路召回数量与最终 top_k 一致;Ensemble 会做合并去重后再裁剪
    bm25 = build_bm25_retriever(docs, k=top_k)
    vector = build_vector_retriever(vector_store, k=top_k)
    return build_ensemble_retriever(bm25, vector, weights=weights)


def retrieve_tools(
    query: str,
    retriever: EnsembleRetriever | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """
    根据 query 多路召回,返回原始 OpenAI tools dict 列表。

    参数:
        query: 用户输入(自然语言)。
        retriever: 复用已构建的 retriever;为 None 时内部 get_retriever 一次。
        top_k: 最终返回的 function 数量上限。
    返回:
        list[dict]: 直接可作为 OpenAI SDK / 兼容 SDK 的 `tools=` 参数。
    """
    if retriever is None:
        retriever = get_retriever(top_k=top_k)

    docs: list[Document] = retriever.invoke(query)

    # 多路合并后可能出现同名 function,按出现顺序去重保留首个
    seen: set[str] = set()
    tools: list[dict] = []
    for doc in docs:
        name = doc.metadata.get("function_name", "")
        if name in seen:
            continue
        seen.add(name)
        # 从 metadata 反序列化拿回原始 OpenAI tools dict
        tool = json.loads(doc.metadata["tool_json"])
        tools.append(tool)
        if len(tools) >= top_k:
            break
    return tools


# ============== 7. 交互式聊天栏 ==============

def interactive_chat(
    top_k: int = DEFAULT_TOP_K,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> None:
    """
    在终端启动一个交互式聊天栏,循环读取输入并打印 Top-K function。

    内置指令:
      :quit / :exit / Ctrl+C / Ctrl+D —— 退出
      :k <int>                        —— 调整本次会话的 top_k
      :help                           —— 打印帮助
    """
    print("=" * 60)
    print("RAG Function 多路召回 - 交互式聊天栏")
    print(f"embedding: {EMBEDDING_MODEL}  |  top_k={top_k}  |  weights(BM25,向量)={weights}")
    print("输入自然语言查询,我会返回最相关的 function。")
    print("指令: :quit 退出 | :k <数字> 调整 top_k | :help 帮助")
    print("=" * 60)

    # 在循环外构建一次,避免每轮重复加载向量库与 BM25
    print("[初始化] 正在加载向量库与 BM25 索引,请稍候 ...")
    # BM25 / 向量单路用更大的 k,确保三路对比里能看到更全的排名
    breakdown_k = max(top_k, 10)
    bm25, vector_store, ensemble = _build_three_retrievers(
        top_k=breakdown_k, weights=weights
    )
    print("[就绪] 可以开始提问了。\n")

    current_top_k = top_k
    while True:
        try:
            query = input("你> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见")
            return

        if not query:
            continue

        # 内置指令处理
        if query in (":quit", ":exit"):
            print("再见")
            return
        if query == ":help":
            print(":quit / :exit 退出 | :k <数字> 调整 top_k | :help 帮助")
            continue
        if query.startswith(":k"):
            current_top_k = _handle_topk_command(query, current_top_k)
            continue

        # 正常查询:三路并排展示
        _run_query_with_breakdown(
            query, ensemble, bm25, vector_store, current_top_k
        )


def _handle_topk_command(cmd: str, current: int) -> int:
    """解析 ':k <数字>' 指令,返回新的 top_k(失败则保持原值)。"""
    parts = cmd.split(maxsplit=1)
    if len(parts) != 2:
        print("用法: :k <正整数>")
        return current
    try:
        new_k = int(parts[1])
        if new_k <= 0:
            raise ValueError
    except ValueError:
        print("top_k 必须是正整数")
        return current
    print(f"已将 top_k 调整为 {new_k}")
    return new_k


def _run_query_and_print(query: str, retriever: EnsembleRetriever, top_k: int) -> None:
    """执行单次召回并按统一格式打印结果。"""
    try:
        tools = retrieve_tools(query, retriever=retriever, top_k=top_k)
    except Exception as exc:  # 用户交互场景下捕获,避免一次报错导致退出
        print(f"[错误] 检索失败: {exc}")
        return

    if not tools:
        print("(未召回任何 function)\n")
        return

    print(f"召回 {len(tools)} 个 function:")
    for i, tool in enumerate(tools, start=1):
        inner = tool["function"]
        name = inner["name"]
        desc = (inner.get("description") or "").strip().replace("\n", " ")
        # 描述截断到 80 个字符,完整 dict 用户可自取 tools 列表
        if len(desc) > 80:
            desc = desc[:80] + "..."
        print(f"  [{i}] {name} — {desc}")
    print()


def _run_query_with_breakdown(
    query: str,
    ensemble: EnsembleRetriever,
    bm25: BM25Retriever,
    vector_store: Chroma,
    top_k: int,
) -> None:
    """执行单次召回并并排展示 BM25 / 向量 / Ensemble 三路 Top-K 排名。"""
    try:
        bm25_docs = bm25.invoke(query)[:top_k]
        vec_pairs = vector_store.similarity_search_with_score(query, k=top_k)
        ens_docs = ensemble.invoke(query)[:top_k]
    except Exception as exc:
        print(f"[错误] 检索失败: {exc}")
        return

    bm25_names = [d.metadata.get("function_name", "") for d in bm25_docs]
    vec_names = [d.metadata.get("function_name", "") for d, _ in vec_pairs]
    vec_scores = [s for _, s in vec_pairs]
    ens_names = [d.metadata.get("function_name", "") for d in ens_docs]

    # 三列并排,便于眼看哪一路把对的答案推上去/挤下去
    name_w = 22
    print(f"\n{'排名':<4}{'BM25':<{name_w}}{'向量(距离)':<{name_w + 4}}{'Ensemble (最终)':<{name_w}}")
    print("-" * (4 + name_w * 3 + 4))
    rows = max(len(bm25_names), len(vec_names), len(ens_names))
    for i in range(rows):
        bm = bm25_names[i] if i < len(bm25_names) else ""
        vc = vec_names[i] if i < len(vec_names) else ""
        sc = f"{vec_scores[i]:.3f}" if i < len(vec_scores) else ""
        en = ens_names[i] if i < len(ens_names) else ""
        vc_cell = f"{vc} ({sc})" if vc else ""
        print(f"#{i + 1:<3}{bm:<{name_w}}{vc_cell:<{name_w + 4}}{en:<{name_w}}")
    print()


# ============== 8. 评测(Excel I/O) ==============

# 50 条评测用例,覆盖 10 个 function 的正向/边缘/负向场景。
# 负向用例的目标 function 填 NO_TARGET_SENTINEL,表示"应不召回任何 function"。
EVAL_CASES: list[tuple[str, str]] = [
    # get_weather × 4
    ("杭州天气怎么样", "get_weather"),
    ("今天热不热", "get_weather"),
    ("深圳明天有雨吗", "get_weather"),
    ("现在外面温度多少", "get_weather"),
    # get_time × 3
    ("现在几点了", "get_time"),
    ("今天几号", "get_time"),
    ("今天星期几", "get_time"),
    # exit_function × 4
    ("再见", "exit_function"),
    ("拜拜", "exit_function"),
    ("我要退出", "exit_function"),
    ("不聊了我睡觉去", "exit_function"),
    # search_news × 4
    ("我想听新闻", "search_news"),
    ("今天美国发生了什么", "search_news"),
    ("最近有啥大事", "search_news"),
    ("给我读条头条", "search_news"),
    # audio_game × 4
    ("玩个听觉游戏", "audio_game"),
    ("给我练练耳朵", "audio_game"),
    ("来个声音游戏", "audio_game"),
    ("上次那个声音再播一遍", "audio_game"),
    # achievement_unlocked × 4
    ("我得到小耳朵灵灵的称号", "achievement_unlocked"),
    ("解锁了大眼睛亮亮", "achievement_unlocked"),
    ("我成超级辩手了", "achievement_unlocked"),
    ("触发故事小作家成就", "achievement_unlocked"),
    # search_diary × 4
    ("那篇日记讲的啥", "search_diary"),
    ("上周写的那首诗", "search_diary"),
    ("上个月的日记给我听一下", "search_diary"),
    ("那封信再念一遍", "search_diary"),
    # play_music × 4
    ("放首歌", "play_music"),
    ("我想听音乐", "play_music"),
    ("来点流行的", "play_music"),
    ("播放落花流水", "play_music"),
    # play_story × 4
    ("讲讲你EHCO经历过的故事", "play_story"),
    ("说说你的亲身经历", "play_story"),
    ("你以前发生过什么", "play_story"),
    ("给我讲个你的故事", "play_story"),
    # change_sound × 4
    ("大点声", "change_sound"),
    ("太吵了调小一点", "change_sound"),
    ("调到最大", "change_sound"),
    ("音量50", "change_sound"),
    # 边缘 / 负向 × 11
    ("音乐", "play_music"),                          # 单词模糊
    ("调一下", "change_sound"),                      # 省略宾语
    ("今天", "get_time"),                            # 极短歧义,易和 get_weather 混
    ("讲个童话故事", NO_TARGET_SENTINEL),            # 不是 EHCO 亲身经历,应不召 play_story
    ("我饿了", NO_TARGET_SENTINEL),                  # 任何 function 都不该命中
    ("你好", NO_TARGET_SENTINEL),                    # 闲聊
    ("我累了想睡觉", "play_music"),                  # 哄睡场景
    ("天气怎么样然后给我点新闻", "search_news"),     # 双意图,主意图取后者
    ("再放一首", "play_music"),                      # 省略上下文
    ("烦死了不想说了", "exit_function"),             # 情绪化表达
    ("play music please", "play_music"),             # 英文表达
]


def _build_three_retrievers(
    top_k: int = DEFAULT_TOP_K,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> tuple[BM25Retriever, Chroma, EnsembleRetriever]:
    """加载并构建 BM25 / 向量库 / Ensemble 三路对象,interactive_chat 与 eval 共用。"""
    embeddings = build_embeddings()
    vector_store = load_vector_store(embeddings)
    docs = load_cached_docs()
    bm25 = build_bm25_retriever(docs, k=top_k)
    vector = build_vector_retriever(vector_store, k=top_k)
    ensemble = build_ensemble_retriever(bm25, vector, weights=weights)
    return bm25, vector_store, ensemble


def _timestamp() -> str:
    """生成文件名后缀用的时间戳。"""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def init_eval_cases(output_path: Path = EVAL_CASES_XLSX) -> Path:
    """
    把硬编码的 50 条评测用例写到 Excel 模板,2 列:用例内容 / 目标function。

    目标路径已存在时不覆盖,自动追加时间戳后缀,避免误删用户改过的版本。
    """
    if output_path.exists():
        output_path = output_path.with_name(
            f"{output_path.stem}_{_timestamp()}{output_path.suffix}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "cases"
    ws.append(["用例内容", "目标function"])
    for query, target in EVAL_CASES:
        ws.append([query, target])
    wb.save(output_path)
    return output_path


def _read_eval_cases(input_path: Path) -> list[tuple[str, str]]:
    """从 Excel 读取用例,返回 (query, target) 列表。空行跳过。"""
    if not input_path.exists():
        raise FileNotFoundError(
            f"评测用例 Excel 不存在: {input_path}。"
            f"请先运行: python -m RAG.rag_function init-eval"
        )
    wb = openpyxl.load_workbook(input_path, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(min_row=2, values_only=True)
    cases: list[tuple[str, str]] = []
    for row in rows:
        if not row or row[0] is None:
            continue
        query = str(row[0]).strip()
        target = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        if not query:
            continue
        cases.append((query, target))
    wb.close()
    return cases


def _rank_of(target: str, names: list[str]) -> int | str:
    """目标 function 在召回列表里的 1-based 排名;不在则返回字符串 '未召回'。"""
    if target == NO_TARGET_SENTINEL:
        return "N/A"
    try:
        return names.index(target) + 1
    except ValueError:
        return "未召回"


def run_eval(
    input_path: Path = EVAL_CASES_XLSX,
    output_path: Path | None = None,
    top_k: int = DEFAULT_TOP_K,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> Path:
    """
    读评测用例 → 跑 BM25/向量/Ensemble 三路 → 把目标 function 在各路 Top-K 中
    的排名写回新 Excel。
    """
    cases = _read_eval_cases(input_path)
    print(f"[eval] 加载用例: {len(cases)} 条 ({input_path})")

    print("[eval] 初始化三路 retriever ...")
    bm25, vector_store, ensemble = _build_three_retrievers(top_k=top_k, weights=weights)

    if output_path is None:
        output_path = EVAL_RESULTS_DIR / f"eval_results_{_timestamp()}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(["用例内容", "目标function", "BM25排名", "向量排名", "Ensemble排名"])

    # 简易统计:正向用例的命中情况,用于尾部汇总
    bm25_hits = vec_hits = ens_hits = 0
    positive_cnt = 0

    for i, (query, target) in enumerate(cases, start=1):
        try:
            bm25_names = [d.metadata.get("function_name", "") for d in bm25.invoke(query)[:top_k]]
            vec_names = [d.metadata.get("function_name", "")
                         for d in vector_store.similarity_search(query, k=top_k)]
            ens_names = [d.metadata.get("function_name", "") for d in ensemble.invoke(query)[:top_k]]
        except Exception as exc:
            print(f"  [{i}/{len(cases)}] 检索失败: {query!r} -> {exc}")
            ws.append([query, target, "ERROR", "ERROR", "ERROR"])
            continue

        bm25_rank = _rank_of(target, bm25_names)
        vec_rank = _rank_of(target, vec_names)
        ens_rank = _rank_of(target, ens_names)
        ws.append([query, target, bm25_rank, vec_rank, ens_rank])

        if target != NO_TARGET_SENTINEL:
            positive_cnt += 1
            if bm25_rank == 1:
                bm25_hits += 1
            if vec_rank == 1:
                vec_hits += 1
            if ens_rank == 1:
                ens_hits += 1

        print(f"  [{i}/{len(cases)}] {query} -> 目标={target} | "
              f"BM25={bm25_rank} 向量={vec_rank} Ensemble={ens_rank}")

    wb.save(output_path)
    print(f"\n[eval] 结果已写入: {output_path}")
    if positive_cnt:
        print(f"[eval] Top1 命中率(正向 {positive_cnt} 条): "
              f"BM25={bm25_hits}/{positive_cnt}={bm25_hits / positive_cnt:.0%}  "
              f"向量={vec_hits}/{positive_cnt}={vec_hits / positive_cnt:.0%}  "
              f"Ensemble={ens_hits}/{positive_cnt}={ens_hits / positive_cnt:.0%}")
    return output_path


# ============== 9. CLI 入口 ==============

def _print_index_summary(summary: dict) -> None:
    """构建索引后打印摘要。"""
    print("索引构建完成:")
    print(f"  function 数量: {summary['function_count']}")
    print(f"  function 列表: {summary['function_names']}")
    print(f"  embedding:     {summary['embedding_model']}")
    print(f"  向量库目录:    {summary['persist_dir']}")
    print(f"  切片缓存:      {summary['docs_cache']}")


def _main(argv: list[str]) -> int:
    """
    命令行入口分发:
      build                 —— 重建索引
      chat                  —— 进入交互式聊天栏(默认)
      query "<text>"        —— 单次查询并打印
      dump                  —— 把切片好的文本写到 RAG/data/functions_docs.txt
      init-eval             —— 生成 50 条评测用例的 Excel 模板
      eval [--input PATH] [--output PATH] [--top-k N]
                            —— 读评测用例 Excel,把三路排名写到结果 Excel
    """
    cmd = argv[0] if argv else "chat"

    if cmd == "build":
        summary = build_index()
        _print_index_summary(summary)
        return 0

    if cmd == "chat":
        interactive_chat()
        return 0

    if cmd == "query":
        if len(argv) < 2:
            print('用法: python -m RAG.rag_function query "你的问题"')
            return 2
        query = " ".join(argv[1:])
        retriever = get_retriever()
        _run_query_and_print(query, retriever, DEFAULT_TOP_K)
        return 0

    if cmd == "dump":
        return _dump_docs()

    if cmd == "init-eval":
        out = init_eval_cases()
        print(f"已写入评测用例模板: {out}")
        print(f"共 {len(EVAL_CASES)} 条用例。可手动编辑后运行: python -m RAG.rag_function eval")
        return 0

    if cmd == "eval":
        return _run_eval_cli(argv[1:])

    print(f"未知命令: {cmd}")
    print('可用命令: build | chat | query "<text>" | dump | init-eval | eval')
    return 2


def _run_eval_cli(args: list[str]) -> int:
    """解析 eval 子命令的参数 --input / --output / --top-k 并调用 run_eval。"""
    input_path = EVAL_CASES_XLSX
    output_path: Path | None = None
    top_k = DEFAULT_TOP_K

    i = 0
    while i < len(args):
        flag = args[i]
        if flag in ("--input", "-i") and i + 1 < len(args):
            input_path = Path(args[i + 1])
            i += 2
        elif flag in ("--output", "-o") and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif flag == "--top-k" and i + 1 < len(args):
            try:
                top_k = int(args[i + 1])
                if top_k <= 0:
                    raise ValueError
            except ValueError:
                print("--top-k 必须是正整数")
                return 2
            i += 2
        else:
            print(f"未知 eval 参数: {flag}")
            print("用法: python -m RAG.rag_function eval [--input xxx.xlsx] [--output yyy.xlsx] [--top-k 4]")
            return 2

    run_eval(input_path=input_path, output_path=output_path, top_k=top_k)
    return 0


def _dump_docs() -> int:
    """把 functions_docs.pkl 里的切片文本导出成可读 .txt,方便人工检查。"""
    docs = load_cached_docs()
    out_path = DOCS_CACHE.with_suffix(".txt")
    with out_path.open("w", encoding="utf-8") as f:
        for i, doc in enumerate(docs, start=1):
            f.write(f"===== [{i}] {doc.metadata.get('function_name', '')} =====\n")
            f.write(doc.page_content)
            f.write("\n\n")
    print(f"已导出 {len(docs)} 个切片到: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

