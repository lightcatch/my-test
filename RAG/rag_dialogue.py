"""
RAG 对话触发条件 两路召回执行文件
===================================

目标
----
把 `RAG/data/全量对话触发内容库.doc`(15 条「场景触发条件 → 回复话术」)按
**一条一片**切片,**只把触发条件入库做索引**;给用户一句话,分别用
BM25(关键词) 和 向量(语义) **两路独立召回**,各自返回 Top-K 命中的
**触发条件** + 分数,并排对比(本期不做融合、不做触发→回复映射)。

为什么单独写一个模块
--------------------
- 世界观/记忆篇章是叙事检索,「匹配的内容」和「返回的内容」是同一段;
  这里是意图路由话术库,本来「匹配触发词、返回回复」是错位的两段。
- 本期需求简化:只切触发条件、检索也返回触发条件(方便对比召回准不准),
  且两路不融合、要看具体分数 —— EnsembleRetriever 的 RRF 只给名次拿不到分,
  所以这里**自己分别取两路分数**,不用 Ensemble。
- 向量库/BM25/嵌入这些通用基础件复用 rag_function,不改它。

整体流程
--------
1. extract_doc_text   —— win32com 提取 .doc 文本(逐段,保留换行)
2. _parse_pairs       —— 逐行拆成 (触发条件, 回复)
3. chunk_dialogue     —— 一条一片,page_content=触发条件,reply 存 metadata 备用
4. build_embeddings(复用) —— bge-m3
5. build_dialogue_vector_store —— Chroma(cosine 空间,独立 collection)
6. build_bm25_retriever(复用)  —— jieba 中文 BM25
7. query              —— BM25 / 向量 两路各自 Top-K + 分数,并排返回

常用命令(项目根 D:/PyCode/test/ 下,务必用 venv 的 python + -X utf8)
---------------------------------------------------------------------
重建索引:  .venv/Scripts/python.exe -X utf8 -m RAG.rag_dialogue build
单次查询:  .venv/Scripts/python.exe -X utf8 -m RAG.rag_dialogue query "外面下好大的雨"
交互检索:  .venv/Scripts/python.exe -X utf8 -m RAG.rag_dialogue chat
导出切片:  .venv/Scripts/python.exe -X utf8 -m RAG.rag_dialogue dump
"""
from __future__ import annotations

import os

# 离线模式:跳过 HuggingFace 联网检查。必须在 import langchain_huggingface 之前设。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pickle
import re
import shutil
import sys
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

# 复用 rag_function 的通用基础件(与数据格式无关)。
from RAG.rag_function import (
    EMBEDDING_MODEL,
    _jieba_preprocess,
    build_bm25_retriever,
    build_embeddings,
)

# ============== 模块常量 ==============

_THIS_DIR = Path(__file__).parent.resolve()

DG_SOURCE_DOC = _THIS_DIR / "data" / "全量对话触发内容库.doc"
DG_EXTRACTED_TXT = _THIS_DIR / "data" / "_dialogue_extracted.txt"
DG_PERSIST_DIR = _THIS_DIR / "data" / "chroma_dialogue"
DG_DOCS_CACHE = _THIS_DIR / "data" / "dialogue_docs.pkl"
DG_CHUNKS_TXT = _THIS_DIR / "data" / "dialogue_chunks.txt"
DG_COLLECTION = "rag_dialogue"

DG_TOP_K = 3

# 触发条件与回复之间的分隔标记:兼容全角"："和半角":"。
_REPLY_SEP_RE = re.compile(r"回复[：:]")

# 扩写覆盖表:键=场景 index,值=扩写后的入库文本。
# 背景:实测剥前缀/去引号对 bge-m3 是负优化(整句语义编码,短文本反而飘),
# 原始触发条件最好。只对几个语义单薄/易混的场景用扩写文本(加自然语言描述+口语例句),
# 给句向量更多语义锚点;未列出的场景仍用原始完整触发条件。
_EXPAND: dict[int, str] = {
    2: "当用户聊到朋友、同伴、同类,或提到和朋友相处、朋友不理我、感到孤单、羡慕别人有朋友、问起你有没有同伴",
    4: "当用户提及下雨、雨天、阴天、下雪、打雷、刮风、起雾、台风等天气,或说外面在下雨、听着雨声、没带伞淋湿了",
    5: "当用户在睡前、躺床上、卧室里聊天,或说要睡觉了、好困、晚安、睡不着、关灯睡了、陪我入睡",
    6: "当用户描述正在拥抱、贴贴、依偎、靠着你、抱着抱枕玩偶等亲密动作或状态(陈述当下,而非请求)",
    10: "当用户对你承诺会陪伴、会留下、不会离开、会守着你、会照顾你,主动给予安慰",
    14: "当用户主动请求抱抱、要你过来抱、想被抱、求一个拥抱、提出贴贴(祈使或请求语气,如抱抱我、过来抱一下)",
}


# ============== 1. 提取 .doc 文本 ==============

def extract_doc_text(
    doc_path: Path = DG_SOURCE_DOC,
    out_path: Path = DG_EXTRACTED_TXT,
) -> str:
    """
    用 win32com(Word COM 自动化)提取 .doc 文本,逐段读取保留段落换行。

    几个坑(都已处理):
      - doc.Paragraphs 的 Range.Text 带尾随 \\r 和表格标记 \\x07,需清洗;
      - 必须在 word.Quit() 之前就把文本存好——Quit() 即使成功也常抛
        com_error -2147023170,所以包 try/except。
    """
    import win32com.client  # 延迟 import:非 Windows/无 Word 环境跑其他命令不受影响

    if not doc_path.exists():
        raise FileNotFoundError(f"源文档不存在: {doc_path}")

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    paragraphs: list[str] = []
    try:
        doc = word.Documents.Open(str(doc_path), ReadOnly=True)
        try:
            for para in doc.Paragraphs:
                raw = para.Range.Text or ""
                cleaned = raw.replace("\x07", "").replace("\r", "").strip()
                if cleaned:
                    paragraphs.append(cleaned)
        finally:
            doc.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass  # Quit 即使成功也常抛 com_error,忽略

    full_text = "\n".join(paragraphs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_text, encoding="utf-8")
    return full_text


def _load_extracted_text() -> str:
    """优先读已提取的纯文本;没有则现场提取。"""
    if DG_EXTRACTED_TXT.exists():
        text = DG_EXTRACTED_TXT.read_text(encoding="utf-8").strip()
        if text:
            return text
    return extract_doc_text()


# ============== 2. 解析 + 切片(一条一片) ==============

def _parse_pairs(full_text: str) -> list[tuple[str, str]]:
    """
    逐行拆成 (触发条件, 回复)。每行形如 `当用户……,回复：……`。
      - 用 `回复[：:]` 切开,兼容全角/半角冒号;
      - 触发条件去掉尾部的逗号(，/,);
      - 回复清理末尾游离的反斜杠 `\\`(源文档第 1 条带)。
    无法识别分隔符的行跳过。
    """
    pairs: list[tuple[str, str]] = []
    for line in full_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _REPLY_SEP_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            continue  # 没有"回复"分隔符的行,跳过
        trigger = parts[0].strip().rstrip("，,").strip()
        reply = parts[1].strip().rstrip("\\").strip()
        if trigger:
            pairs.append((trigger, reply))
    return pairs


def chunk_dialogue(full_text: str) -> list[Document]:
    """
    一条一片:page_content = 入库文本(默认=原始触发条件;_EXPAND 里列出的场景用扩写文本)。
    原始触发条件存 metadata['trigger_raw'],回复存 metadata['reply'](本期不参与检索/返回)。
    """
    docs: list[Document] = []
    for idx, (trigger, reply) in enumerate(_parse_pairs(full_text)):
        indexed = _EXPAND.get(idx, trigger)
        docs.append(
            Document(
                page_content=indexed,
                metadata={
                    "scenario_index": idx,
                    "trigger_raw": trigger,
                    "expanded": idx in _EXPAND,
                    "reply": reply,
                    "source": DG_SOURCE_DOC.name,
                },
            )
        )
    return docs


# ============== 3. dialogue 专属存储封装 ==============

def build_dialogue_vector_store(docs: list[Document], embeddings) -> Chroma:
    """重建 dialogue 向量索引(cosine 空间)并持久化,同时 pickle 切片供 BM25 复用。"""
    if DG_PERSIST_DIR.exists():
        shutil.rmtree(DG_PERSIST_DIR)
    DG_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    vector_store = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory=str(DG_PERSIST_DIR),
        collection_name=DG_COLLECTION,
        # 必须显式 cosine:否则默认 L2,vec_sim = 1 - 距离 就不是余弦相似度
        collection_metadata={"hnsw:space": "cosine"},
    )
    if hasattr(vector_store, "persist"):
        vector_store.persist()

    DG_DOCS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with DG_DOCS_CACHE.open("wb") as f:
        pickle.dump(docs, f)
    return vector_store


def load_dialogue_vector_store(embeddings) -> Chroma:
    """只读加载已持久化的 dialogue Chroma 向量库。"""
    if not DG_PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"向量库目录不存在: {DG_PERSIST_DIR}。"
            f"请先运行: python -m RAG.rag_dialogue build"
        )
    return Chroma(
        persist_directory=str(DG_PERSIST_DIR),
        embedding_function=embeddings,
        collection_name=DG_COLLECTION,
        collection_metadata={"hnsw:space": "cosine"},
    )


def load_dialogue_docs() -> list[Document]:
    """从 DG_DOCS_CACHE 反序列化切片结果(供 BM25 复用)。"""
    if not DG_DOCS_CACHE.exists():
        raise FileNotFoundError(
            f"切片缓存不存在: {DG_DOCS_CACHE}。"
            f"请先运行: python -m RAG.rag_dialogue build"
        )
    with DG_DOCS_CACHE.open("rb") as f:
        return pickle.load(f)


# ============== 4. 对外入口 ==============

def build_index() -> dict:
    """一站式重建 dialogue 索引(提取 → 切片 → 向量库 → dump)。"""
    full_text = _load_extracted_text()
    docs = chunk_dialogue(full_text)
    if not docs:
        raise RuntimeError("切片结果为空,请检查 .doc 提取/解析是否成功。")
    embeddings = build_embeddings()
    build_dialogue_vector_store(docs, embeddings)
    dump_chunks(docs)
    return {
        "char_count": len(full_text),
        "chunk_count": len(docs),
        "persist_dir": str(DG_PERSIST_DIR),
        "docs_cache": str(DG_DOCS_CACHE),
        "embedding_model": EMBEDDING_MODEL,
    }


def _build_retrievers(top_k: int = DG_TOP_K):
    """构建 BM25 + 加载向量库 + 切片列表,query/chat 共用。返回 (bm25, vector_store, docs)。"""
    embeddings = build_embeddings()
    vector_store = load_dialogue_vector_store(embeddings)
    docs = load_dialogue_docs()
    bm25 = build_bm25_retriever(docs, k=top_k)
    return bm25, vector_store, docs


def _bm25_topk(bm25, text: str, top_k: int) -> list[dict]:
    """
    BM25 一路:取全量原始分,按分降序取 Top-K。
    分词复用 _jieba_preprocess(与建库一致),分数来自底层 rank_bm25.BM25Okapi。
    """
    tokens = _jieba_preprocess(text)
    scores = bm25.vectorizer.get_scores(tokens)  # 长度=文档数,顺序对应 bm25.docs
    ranked = sorted(zip(scores, bm25.docs), key=lambda x: x[0], reverse=True)[:top_k]
    return [
        {
            "rank": i,
            "scenario": doc.page_content,
            "bm25_score": float(score),
        }
        for i, (score, doc) in enumerate(ranked, start=1)
    ]


def _vector_topk(vector_store: Chroma, text: str, top_k: int) -> list[dict]:
    """向量一路:cosine 距离 → vec_sim = 1 - 距离,取 Top-K。"""
    pairs = vector_store.similarity_search_with_score(text, k=top_k)
    return [
        {
            "rank": i,
            "scenario": doc.page_content,
            "vec_sim": float(1.0 - dist),
        }
        for i, (doc, dist) in enumerate(pairs, start=1)
    ]


def query(text: str, top_k: int = DG_TOP_K, retrievers=None) -> dict:
    """
    两路独立召回(不融合),各返回 Top-K 命中的触发条件 + 分数,并排对比。
    返回: {"bm25": [{rank, scenario, bm25_score}], "vector": [{rank, scenario, vec_sim}]}
    """
    if retrievers is None:
        bm25, vector_store, _ = _build_retrievers(top_k=top_k)
    else:
        bm25, vector_store, _ = retrievers
    return {
        "bm25": _bm25_topk(bm25, text, top_k),
        "vector": _vector_topk(vector_store, text, top_k),
    }


# ============== 5. dump / 交互式检索 ==============

def dump_chunks(docs: list[Document] | None = None) -> Path:
    """把切片导出成可读 txt,人工核对触发条件/回复。"""
    if docs is None:
        docs = load_dialogue_docs()
    DG_CHUNKS_TXT.parent.mkdir(parents=True, exist_ok=True)
    with DG_CHUNKS_TXT.open("w", encoding="utf-8") as f:
        for doc in docs:
            idx = doc.metadata.get("scenario_index", "?")
            raw = doc.metadata.get("trigger_raw", "")
            exp = doc.metadata.get("expanded", False)
            reply = doc.metadata.get("reply", "")
            tag = " [扩写]" if exp else ""
            f.write(f"===== [{idx}]{tag} 入库文本 (len={len(doc.page_content)}) =====\n")
            f.write(f"入库文本: {doc.page_content}\n")
            f.write(f"原始触发: {raw}\n")
            f.write(f"回复(备用): {reply}\n\n")
    print(f"已导出 {len(docs)} 个切片到: {DG_CHUNKS_TXT}")
    return DG_CHUNKS_TXT


def _print_two_routes(text: str, result: dict) -> None:
    """并排打印 BM25 / 向量 两路 Top-K + 分数。"""
    bm25_rows = result["bm25"]
    vec_rows = result["vector"]
    print(f"\n查询: {text}")
    print(f"{'排名':<5}{'BM25 (分数)  触发条件':<46}{'向量 (相似度)  触发条件'}")
    print("-" * 100)
    rows = max(len(bm25_rows), len(vec_rows))
    for i in range(rows):
        if i < len(bm25_rows):
            b = bm25_rows[i]
            bcell = f"{b['bm25_score']:.3f}  {b['scenario']}"
        else:
            bcell = ""
        if i < len(vec_rows):
            v = vec_rows[i]
            vcell = f"{v['vec_sim']:.3f}  {v['scenario']}"
        else:
            vcell = ""
        # 触发条件较长,各占一行更清晰
        print(f"#{i + 1:<4}[BM25 ] {bcell}")
        print(f"     [向量 ] {vcell}")
    print()


def interactive_chat(top_k: int = DG_TOP_K) -> None:
    """
    交互式两路检索:每句**独立**检索(话术库无状态,不拼历史),
    并排展示 BM25 / 向量 两路 Top-K 命中的触发条件 + 分数。

    命令:
      :quit / :q / exit  退出
      :k N               修改 top_k
      :debug             对当前输入打印全部切片的两路打分(不截断)
    """
    print("正在加载 dialogue 索引(首次加载 bge-m3 约数秒)...")
    bm25, vector_store, docs = _build_retrievers(top_k=top_k)
    print(f"就绪。共 {len(docs)} 条触发条件,top_k={top_k}。")
    print("直接说话即可检索。命令: :quit 退出 | :k N 改top_k | :debug 全量打分\n")

    while True:
        try:
            line = input("你 >>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (":quit", ":q", "exit"):
            break
        if line.startswith(":k"):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
                top_k = int(parts[1])
                bm25.k = top_k
                print(f"top_k 已改为 {top_k}\n")
            else:
                print("用法: :k 5\n")
            continue
        if line == ":debug":
            print("(暂无独立输入,请在 :debug 前先打一句)\n")
            continue

        result = query(line, top_k=top_k, retrievers=(bm25, vector_store, docs))
        _print_two_routes(line, result)


# ============== 6. CLI 入口 ==============

def _print_index_summary(summary: dict) -> None:
    print("dialogue 索引构建完成:")
    print(f"  原文字数:   {summary['char_count']}")
    print(f"  切片数量:   {summary['chunk_count']}")
    print(f"  embedding:  {summary['embedding_model']}")
    print(f"  向量库目录: {summary['persist_dir']}")
    print(f"  切片缓存:   {summary['docs_cache']}")


def _main(argv: list[str]) -> int:
    """命令分发: build | extract | chat | query "<text>" | dump"""
    cmd = argv[0] if argv else "chat"

    if cmd == "build":
        _print_index_summary(build_index())
        return 0
    if cmd == "extract":
        text = extract_doc_text()
        print(f"已提取 {len(text)} 字到: {DG_EXTRACTED_TXT}")
        return 0
    if cmd == "chat":
        interactive_chat()
        return 0
    if cmd == "query":
        if len(argv) < 2:
            print('用法: python -m RAG.rag_dialogue query "你的输入"')
            return 2
        result = query(" ".join(argv[1:]))
        _print_two_routes(" ".join(argv[1:]), result)
        return 0
    if cmd == "dump":
        dump_chunks()
        return 0

    print(f"未知命令: {cmd}")
    print('可用命令: build | extract | chat | query "<text>" | dump')
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
