"""
RAG 世界观(剧情设定)多路召回执行文件
=====================================

目标
----
把 `RAG/data/世界观.doc`(科幻设定文档)按"章节 + 递归子切"的混合策略切片入库,
基于用户输入做"向量(语义) + BM25(关键词)"多路召回,
返回 Top-K 最相关的世界观片段。

为什么单独写一个模块
--------------------
`rag_function.py` 是针对 OpenAI tools 格式的"函数定义"做检索的,
一函数一切片。世界观是结构化散文,需要不同的切片方式。
但向量库/BM25/Ensemble 这些"通用基础件"完全可复用,
所以本模块直接 import 它们,只新写"提取 + 切片 + worldview 专属存储封装"。

整体流程
--------
1. extract_doc_text        —— win32com 提取 .doc 文本(保留段落换行)
2. chunk_worldview         —— 章节切分 + 章内递归子切 + 短片合并
3. build_embeddings(复用)  —— 构造 bge-m3 HuggingFace embedding
4. build_worldview_vector_store —— Chroma 向量索引(独立 collection/目录)
5. build_bm25_retriever(复用)   —— jieba 中文 BM25
6. build_vector_retriever(复用) —— Chroma 语义召回
7. build_ensemble_retriever(复用) —— 多路加权合并
8. query                   —— 召回 Top-K 片段(附章节 + 向量距离)

常用命令(在项目根目录 D:/PyCode/test/ 下运行,务必用 venv 的 python + -X utf8)
-----------------------------------------------------------------------------
首次/世界观.doc 改了之后重建索引:
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview build
单次查询:
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview query "什么是空心症"
交互式聊天栏(三路并排展示):
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview chat
导出切片到可读 txt:
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview dump
生成评测用例 Excel 模板:
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview init-eval
跑评测,把每条用例在三路 Top-K 的命中/排名写到结果 Excel:
    .venv/Scripts/python.exe -X utf8 -m RAG.rag_worldview eval
"""
from __future__ import annotations

import os

# 离线模式:跳过 HuggingFace 联网检查(与 rag_function 一致)。import 顺序上
# 先设环境变量再 import langchain_huggingface。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import datetime
import pickle
import re
import shutil
import sys
from pathlib import Path

import openpyxl
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 复用 rag_function 里的"通用基础件"(接收 docs/store 参数,与数据格式无关)。
from RAG.rag_function import (
    EMBEDDING_MODEL,
    EnsembleRetriever,
    build_bm25_retriever,
    build_embeddings,
    build_ensemble_retriever,
    build_vector_retriever,
)

# ============== 模块常量 ==============

_THIS_DIR = Path(__file__).parent.resolve()

# 源文档(二进制 .doc)与提取出的纯文本
WV_SOURCE_DOC = _THIS_DIR / "data" / "世界观.doc"
WV_EXTRACTED_TXT = _THIS_DIR / "data" / "_worldview_extracted.txt"

# Chroma 持久化目录(与函数版 chroma_functions 区分开)
WV_PERSIST_DIR = _THIS_DIR / "data" / "chroma_worldview"

# 切片缓存(pickle),BM25 启动时复用
WV_DOCS_CACHE = _THIS_DIR / "data" / "worldview_docs.pkl"

# 切片可读导出
WV_CHUNKS_TXT = _THIS_DIR / "data" / "worldview_chunks.txt"

# Chroma collection 名(独立)
WV_COLLECTION = "rag_worldview"

# 评测用例 / 结果默认目录
WV_EVAL_CASES_XLSX = _THIS_DIR / "data" / "worldview_eval_cases.xlsx"
WV_EVAL_RESULTS_DIR = _THIS_DIR / "data"

# ---- 切片参数 ----
CHUNK_SIZE = 300
CHUNK_OVERLAP = 60
MIN_CHARS = 120  # 短于此长度的切片合并进同章节前一片

# 中文分隔符(按优先级),最后的 "" 兜底硬切超长片段
CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "　", "，", ""]

# 章节头:第X章：... / 尾声：...
CHAPTER_HEADER_RE = re.compile(r"^\s*(第[一二三四五六七八九十]+章[：:].*|尾声[：:].*)$", re.M)

# ---- 检索参数 ----
WV_TOP_K = 3
# Ensemble 权重 (BM25, 向量):散文比函数更偏语义,向量权重更高
WV_WEIGHTS = (0.3, 0.7)


# ============== 1. 提取 .doc 文本 ==============

def extract_doc_text(
    doc_path: Path = WV_SOURCE_DOC,
    out_path: Path = WV_EXTRACTED_TXT,
) -> str:
    """
    用 win32com(Word COM 自动化)提取 .doc 文本,逐段读取以保留段落换行。

    几个坑(都已处理):
      - olefile/textract/docx2txt 都没装,win32com 是唯一可用方式;
      - doc.Paragraphs 的 Range.Text 带尾随 \\r 和表格标记 \\x07,需清洗;
      - 必须在 word.Quit() 之前就把文本存好——Quit() 即使成功也会抛
        com_error -2147023170(远程过程调用失败),所以包 try/except。
    """
    import win32com.client  # 延迟 import,非 Windows/无 Word 环境下不影响其他命令

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
                # 去掉表格标记 \x07 和回车,strip 两端空白
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
    if WV_EXTRACTED_TXT.exists():
        text = WV_EXTRACTED_TXT.read_text(encoding="utf-8").strip()
        if text:
            return text
    return extract_doc_text()


# ============== 2. 切片(章节 + 递归子切) ==============

def _split_into_chapters(full_text: str) -> list[tuple[str, str]]:
    """
    按章节头把全文切成 (标题, 正文) 对,保持原文顺序。
    章节头之前若有零散文字(如序章/前言),归到一个"序"块里。
    """
    matches = list(CHAPTER_HEADER_RE.finditer(full_text))
    if not matches:
        # 没有章节头:整篇作为一个"全文"块
        return [("世界观", full_text.strip())]

    chapters: list[tuple[str, str]] = []

    # 第一个章节头之前的内容(若有)
    head = full_text[: matches[0].start()].strip()
    if head:
        chapters.append(("序", head))

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[body_start:body_end].strip()
        chapters.append((title, body))

    return chapters


def _merge_tiny(chunks: list[str], min_chars: int = MIN_CHARS) -> list[str]:
    """
    把过短的切片并入前一个切片(同章节内调用,不跨章节)。
    若第一个切片就过短,则与后一个合并。
    """
    if not chunks:
        return []
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < min_chars:
            merged[-1] = merged[-1] + "\n" + c
        else:
            merged.append(c)
    # 收尾:若首片过短且有后续,向后并一次
    if len(merged) >= 2 and len(merged[0]) < min_chars:
        merged[1] = merged[0] + "\n" + merged[1]
        merged = merged[1:]
    return merged


def chunk_worldview(full_text: str) -> list[Document]:
    """
    混合切片:先按章节切,再对每章用递归切分器子切,短片合并,
    每片前置章节标题(同时写入 metadata),便于 BM25/向量都拿到章节信号。
    """
    splitter = RecursiveCharacterTextSplitter(
        separators=CHINESE_SEPARATORS,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        keep_separator=True,
    )

    docs: list[Document] = []
    global_idx = 0
    for ch_idx, (title, body) in enumerate(_split_into_chapters(full_text)):
        if not body:
            continue
        pieces = _merge_tiny(splitter.split_text(body))
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            docs.append(
                Document(
                    page_content=f"【{title}】\n{piece}",
                    metadata={
                        "chapter": title,
                        "chapter_index": ch_idx,
                        "chunk_index": global_idx,
                        "source": WV_SOURCE_DOC.name,
                    },
                )
            )
            global_idx += 1
    return docs


# ============== 3. worldview 专属存储封装 ==============
# build_vector_store/load_vector_store 在 rag_function 里直接读模块级常量
# (PERSIST_DIR/DOCS_CACHE/COLLECTION_NAME),指向 functions 索引。这里写两个
# 薄封装,指向 worldview 的独立目录/collection,从而不改动 rag_function。

def build_worldview_vector_store(
    docs: list[Document],
    embeddings,
) -> Chroma:
    """重建 worldview 向量索引并持久化,同时 pickle 切片供 BM25 复用。"""
    if WV_PERSIST_DIR.exists():
        shutil.rmtree(WV_PERSIST_DIR)
    WV_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    vector_store = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory=str(WV_PERSIST_DIR),
        collection_name=WV_COLLECTION,
    )
    if hasattr(vector_store, "persist"):
        vector_store.persist()

    WV_DOCS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with WV_DOCS_CACHE.open("wb") as f:
        pickle.dump(docs, f)

    return vector_store


def load_worldview_vector_store(embeddings) -> Chroma:
    """只读加载已持久化的 worldview Chroma 向量库。"""
    if not WV_PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"向量库目录不存在: {WV_PERSIST_DIR}。"
            f"请先运行: python -m RAG.rag_worldview build"
        )
    return Chroma(
        persist_directory=str(WV_PERSIST_DIR),
        embedding_function=embeddings,
        collection_name=WV_COLLECTION,
    )


def load_worldview_docs() -> list[Document]:
    """从 WV_DOCS_CACHE 反序列化切片结果(供 BM25 复用)。"""
    if not WV_DOCS_CACHE.exists():
        raise FileNotFoundError(
            f"切片缓存不存在: {WV_DOCS_CACHE}。"
            f"请先运行: python -m RAG.rag_worldview build"
        )
    with WV_DOCS_CACHE.open("rb") as f:
        return pickle.load(f)


# ============== 4. 对外入口 ==============

def build_index() -> dict:
    """一站式重建 worldview 索引(提取 → 切片 → 向量库 → dump)。"""
    full_text = _load_extracted_text()
    docs = chunk_worldview(full_text)
    if not docs:
        raise RuntimeError("切片结果为空,请检查 .doc 提取是否成功。")
    embeddings = build_embeddings()
    build_worldview_vector_store(docs, embeddings)
    dump_chunks(docs)
    chapters = sorted({d.metadata["chapter"] for d in docs})
    return {
        "char_count": len(full_text),
        "chunk_count": len(docs),
        "chapters": chapters,
        "persist_dir": str(WV_PERSIST_DIR),
        "docs_cache": str(WV_DOCS_CACHE),
        "embedding_model": EMBEDDING_MODEL,
    }


def _build_three_retrievers(
    top_k: int = WV_TOP_K,
    weights: tuple[float, float] = WV_WEIGHTS,
) -> tuple[object, Chroma, EnsembleRetriever]:
    """加载并构建 BM25 / 向量库 / Ensemble 三路对象,query/chat/eval 共用。"""
    embeddings = build_embeddings()
    vector_store = load_worldview_vector_store(embeddings)
    docs = load_worldview_docs()
    bm25 = build_bm25_retriever(docs, k=top_k)
    vector = build_vector_retriever(vector_store, k=top_k)
    ensemble = build_ensemble_retriever(bm25, vector, weights=weights)
    return bm25, vector_store, ensemble


def get_retriever(
    top_k: int = WV_TOP_K,
    weights: tuple[float, float] = WV_WEIGHTS,
) -> EnsembleRetriever:
    """加载已构建的索引,返回组装好的 EnsembleRetriever。"""
    _, _, ensemble = _build_three_retrievers(top_k=top_k, weights=weights)
    return ensemble


def query(
    text: str,
    top_k: int = WV_TOP_K,
    retriever: EnsembleRetriever | None = None,
) -> list[dict]:
    """
    根据 query 多路召回,返回 Top-K 世界观片段。
    每条含: rank / chapter / chunk_index / text(可选 score 见 chat 视图)。
    """
    if retriever is None:
        retriever = get_retriever(top_k=top_k)
    docs: list[Document] = retriever.invoke(text)[:top_k]
    results: list[dict] = []
    for rank, doc in enumerate(docs, start=1):
        results.append(
            {
                "rank": rank,
                "chapter": doc.metadata.get("chapter", ""),
                "chunk_index": doc.metadata.get("chunk_index", -1),
                "text": doc.page_content,
            }
        )
    return results


# ============== 5. dump / 交互式聊天栏 ==============

def dump_chunks(docs: list[Document] | None = None) -> Path:
    """把切片导出成可读 txt,人工核对切片边界。"""
    if docs is None:
        docs = load_worldview_docs()
    WV_CHUNKS_TXT.parent.mkdir(parents=True, exist_ok=True)
    with WV_CHUNKS_TXT.open("w", encoding="utf-8") as f:
        for doc in docs:
            ci = doc.metadata.get("chunk_index", "?")
            ch = doc.metadata.get("chapter", "")
            f.write(f"===== [{ci}] {ch} (len={len(doc.page_content)}) =====\n")
            f.write(doc.page_content)
            f.write("\n\n")
    print(f"已导出 {len(docs)} 个切片到: {WV_CHUNKS_TXT}")
    return WV_CHUNKS_TXT


def _run_query_with_breakdown(
    text: str,
    ensemble: EnsembleRetriever,
    bm25,
    vector_store: Chroma,
    top_k: int,
) -> None:
    """并排展示 BM25 / 向量(距离) / Ensemble 三路 Top-K,标签用 章节#片号。"""
    try:
        bm25_docs = bm25.invoke(text)[:top_k]
        vec_pairs = vector_store.similarity_search_with_score(text, k=top_k)
        ens_docs = ensemble.invoke(text)[:top_k]
    except Exception as exc:
        print(f"[错误] 检索失败: {exc}")
        return

    def _label(doc: Document) -> str:
        return f"{doc.metadata.get('chapter', '')}#{doc.metadata.get('chunk_index', '?')}"

    bm25_lbl = [_label(d) for d in bm25_docs]
    vec_lbl = [_label(d) for d, _ in vec_pairs]
    vec_sc = [s for _, s in vec_pairs]
    ens_lbl = [_label(d) for d in ens_docs]

    name_w = 22
    print(f"\n{'排名':<4}{'BM25':<{name_w}}{'向量(距离)':<{name_w + 4}}{'Ensemble(最终)':<{name_w}}")
    print("-" * (4 + name_w * 3 + 4))
    rows = max(len(bm25_lbl), len(vec_lbl), len(ens_lbl))
    for i in range(rows):
        bm = bm25_lbl[i] if i < len(bm25_lbl) else ""
        vc = vec_lbl[i] if i < len(vec_lbl) else ""
        sc = f"{vec_sc[i]:.3f}" if i < len(vec_sc) else ""
        en = ens_lbl[i] if i < len(ens_lbl) else ""
        vc_cell = f"{vc} ({sc})" if vc else ""
        print(f"#{i + 1:<3}{bm:<{name_w}}{vc_cell:<{name_w + 4}}{en:<{name_w}}")
    # Ensemble Top1 正文预览
    if ens_docs:
        preview = ens_docs[0].page_content.replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:100] + "..."
        print(f"\nTop1 片段: {preview}")
    print()


def interactive_chat(
    top_k: int = WV_TOP_K,
    weights: tuple[float, float] = WV_WEIGHTS,
    history_turns: int = 3,
) -> None:
    """
    持续对话式检索:多轮循环,每轮把最近 history_turns 句话拼成上下文做检索,
    展示本轮召回到的世界观片段(完整小切片)。不调用 LLM。

    命令:
      :quit / :q / exit  退出
      :k N               修改 top_k
      :reset             清空对话历史
      :history           查看对话历史
      :debug             对当前最后一句做三路并排调试视图
    """
    print("正在加载 worldview 索引(首次加载 bge-m3 约数秒)...")
    bm25, vector_store, ensemble = _build_three_retrievers(top_k=top_k, weights=weights)
    print(f"就绪。top_k={top_k}, weights(BM25,向量)={weights}, 上下文窗口={history_turns} 轮")
    print("直接说话即可检索世界观片段。命令: :quit 退出 | :k N 改top_k | "
          ":reset 清空历史 | :history 看历史 | :debug 三路视图\n")

    history: list[str] = []  # 仅保存用户说过的话,用于拼接检索上下文

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
        if line == ":reset":
            history.clear()
            print("(对话历史已清空)\n")
            continue
        if line == ":history":
            if history:
                for i, h in enumerate(history, start=1):
                    print(f"  {i}. {h}")
            else:
                print("  (暂无历史)")
            print()
            continue
        if line.startswith(":k"):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
                top_k = int(parts[1])
                bm25.k = top_k
                vector = build_vector_retriever(vector_store, k=top_k)
                ensemble = build_ensemble_retriever(bm25, vector, weights=weights)
                print(f"top_k 已改为 {top_k}\n")
            else:
                print("用法: :k 5\n")
            continue
        if line == ":debug":
            if history:
                ctx = _build_context_query(history, history[-1], history_turns)
                _run_query_with_breakdown(ctx, ensemble, bm25, vector_store, top_k)
            else:
                print("(暂无历史,先说点什么)\n")
            continue

        # 正常一轮:拼上下文 → 检索 → 展示召回片段 → 入历史
        ctx_query = _build_context_query(history, line, history_turns)
        results = query(ctx_query, top_k=top_k, retriever=ensemble)
        _print_recall_results(line, ctx_query, results)
        history.append(line)


# 追问信号:含指代词,或属于"承接型"短语(无新实体的延续追问) → 视为对上一轮的
# 延续,需要拼接历史。否则(自带内容名词的新话题,如"锚点是什么")按独立 query 检索,
# 避免旧上下文把话题带偏。注意:不用"句子长度"做判据——"锚点是什么"很短但是完整新话题。
_ANAPHORA = ("它", "他", "她", "这", "那", "其", "刚才", "刚刚", "刚说",
             "上面", "前面", "上述")
_CONTINUERS = ("然后", "后来", "为什么", "为啥", "还有", "接着", "继续",
               "结果", "所以", "再说说", "展开", "详细")


def _is_followup(text: str) -> bool:
    """判断当前句是否为对上一轮的追问(需要历史上下文消解指代)。"""
    if any(a in text for a in _ANAPHORA):
        return True
    # 承接型:去掉尾部语气词后,整句基本就是一个承接词
    stripped = text.rstrip("呢吗啊吧？?。.！! ")
    return stripped in _CONTINUERS


def _build_context_query(history: list[str], current: str, history_turns: int) -> str:
    """
    构造检索 query。仅当当前句是追问(含指代/极短)时,才拼上最近的历史轮,
    用于消解"它/他/这个"等指代;新话题则只用当前句,避免话题漂移。
    """
    if history and _is_followup(current):
        prior = history[-(history_turns - 1):] if history_turns > 1 else []
        return " ".join(prior + [current])
    return current


def _print_recall_results(current: str, ctx_query: str, results: list[dict]) -> None:
    """展示本轮召回到的完整世界观片段。"""
    if ctx_query != current:
        print(f"[追问·检索上下文]: {ctx_query}")
    if not results:
        print("(未召回任何片段)\n")
        return
    print(f"召回 {len(results)} 个片段:")
    for r in results:
        print(f"\n  ── [#{r['rank']}] {r['chapter']} (片号{r['chunk_index']}) ──")
        for ln in r["text"].splitlines():
            print(f"    {ln}")
    print()


# ============== 6. 评测(Excel I/O) ==============

# 验证用例: (用户说的话, 期望章节关键词)。期望章节用"包含匹配",
# 因为章节标题里带括号副标(如"第二章：空心症与ECHO的诞生（社会）")。
WV_EVAL_CASES: list[tuple[str, str]] = [
    ("什么是空心症", "第二章"),
    ("人类为什么会失眠", "第二章"),
    ("ECHO陪伴机器人是怎么诞生的", "第二章"),
    ("神经调节芯片是什么", "第一章"),
    ("大优化元年发生了什么", "第一章"),
    ("莫比乌斯怎么控制人类的", "第一章"),
    ("ECHO为什么被销毁", "第三章"),
    ("什么是情感污染", "第三章"),
    ("清除令是什么", "第三章"),
    ("一级情感污染源是谁", "第三章"),
    ("锚点是什么", "第四章"),
    ("过度共情者有什么症状", "第四章"),
    ("同调是什么意思", "第四章"),
    ("用户是怎么遇到奈奈的", "第四章"),
    ("赛斯是怎么被捡回来的", "第四章"),
    ("故事的核心是什么", "尾声"),
    ("这是一个什么样的故事", "尾声"),
    ("用户找回的是什么", "尾声"),
]


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def init_eval_cases(output_path: Path = WV_EVAL_CASES_XLSX) -> Path:
    """把验证用例写到 Excel 模板,3 列: 序号 / 用户说的话 / 期望章节。已存在则加时间戳不覆盖。"""
    if output_path.exists():
        output_path = output_path.with_name(
            f"{output_path.stem}_{_timestamp()}{output_path.suffix}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "cases"
    ws.append(["序号", "用户说的话", "期望章节"])
    for i, (q, ch) in enumerate(WV_EVAL_CASES, start=1):
        ws.append([i, q, ch])
    wb.save(output_path)
    return output_path


def _read_eval_cases(input_path: Path) -> list[tuple[str, str]]:
    """从 Excel 读 (用户说的话, 期望章节)。自动定位列(兼容有/无序号列)。"""
    if not input_path.exists():
        raise FileNotFoundError(
            f"评测用例 Excel 不存在: {input_path}。"
            f"请先运行: python -m RAG.rag_worldview init-eval"
        )
    wb = openpyxl.load_workbook(input_path, read_only=True)
    ws = wb.active
    header = [str(c.value).strip() if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))[0:3]]
    # 找"用户说的话"和"期望章节"列下标
    try:
        q_idx = header.index("用户说的话")
    except ValueError:
        q_idx = 1 if len(header) > 1 else 0
    try:
        ch_idx = header.index("期望章节")
    except ValueError:
        ch_idx = q_idx + 1

    cases: list[tuple[str, str]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or q_idx >= len(row) or row[q_idx] is None:
            continue
        q = str(row[q_idx]).strip()
        ch = str(row[ch_idx]).strip() if ch_idx < len(row) and row[ch_idx] is not None else ""
        if q:
            cases.append((q, ch))
    wb.close()
    return cases


def _rank_of_chapter(expected: str, chapters: list[str]) -> int | str:
    """期望章节在召回章节序列里的 1-based 排名(包含匹配);不在则 '未召回'。"""
    if not expected:
        return "N/A"
    for i, ch in enumerate(chapters):
        if expected in ch:
            return i + 1
    return "未召回"


def run_eval(
    input_path: Path = WV_EVAL_CASES_XLSX,
    output_path: Path | None = None,
    top_k: int = WV_TOP_K,
    weights: tuple[float, float] = WV_WEIGHTS,
) -> Path:
    """读用例 → 跑三路 → 把命中/排名(按章节)写回新 Excel(绝不覆盖)。"""
    cases = _read_eval_cases(input_path)
    print(f"[eval] 加载用例: {len(cases)} 条 ({input_path})")
    print("[eval] 初始化三路 retriever ...")
    bm25, vector_store, ensemble = _build_three_retrievers(top_k=top_k, weights=weights)

    if output_path is None:
        output_path = WV_EVAL_RESULTS_DIR / f"worldview_eval_results_{_timestamp()}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(["序号", "用户说的话", "期望章节", "是否命中TopK",
               "命中章节", "Ensemble排名", "BM25排名", "向量排名"])

    hit_cnt = 0
    for i, (q, expected) in enumerate(cases, start=1):
        try:
            bm25_ch = [d.metadata.get("chapter", "") for d in bm25.invoke(q)[:top_k]]
            vec_ch = [d.metadata.get("chapter", "")
                      for d in vector_store.similarity_search(q, k=top_k)]
            ens_docs = ensemble.invoke(q)[:top_k]
            ens_ch = [d.metadata.get("chapter", "") for d in ens_docs]
        except Exception as exc:
            print(f"  [{i}/{len(cases)}] 检索失败: {q!r} -> {exc}")
            ws.append([i, q, expected, "ERROR", "", "ERROR", "ERROR", "ERROR"])
            continue

        ens_rank = _rank_of_chapter(expected, ens_ch)
        bm25_rank = _rank_of_chapter(expected, bm25_ch)
        vec_rank = _rank_of_chapter(expected, vec_ch)
        hit = isinstance(ens_rank, int)
        top_chapter = ens_ch[0] if ens_ch else ""
        if hit:
            hit_cnt += 1
        ws.append([i, q, expected, "是" if hit else "否",
                   top_chapter, ens_rank, bm25_rank, vec_rank])
        print(f"  [{i}/{len(cases)}] {q} -> 期望={expected} | "
              f"命中={'是' if hit else '否'} Ensemble={ens_rank} "
              f"BM25={bm25_rank} 向量={vec_rank}")

    wb.save(output_path)
    print(f"\n[eval] 结果已写入: {output_path}")
    if cases:
        print(f"[eval] TopK 命中率: {hit_cnt}/{len(cases)} = {hit_cnt / len(cases):.0%}")
    return output_path


# ============== 7. CLI 入口 ==============

def _print_index_summary(summary: dict) -> None:
    print("worldview 索引构建完成:")
    print(f"  原文字数:   {summary['char_count']}")
    print(f"  切片数量:   {summary['chunk_count']}")
    print(f"  覆盖章节:   {summary['chapters']}")
    print(f"  embedding:  {summary['embedding_model']}")
    print(f"  向量库目录: {summary['persist_dir']}")
    print(f"  切片缓存:   {summary['docs_cache']}")


def _run_query_and_print(text: str, retriever: EnsembleRetriever, top_k: int) -> None:
    try:
        results = query(text, top_k=top_k, retriever=retriever)
    except Exception as exc:
        print(f"[错误] 检索失败: {exc}")
        return
    if not results:
        print("(未召回任何片段)\n")
        return
    print(f"召回 {len(results)} 个片段:")
    for r in results:
        preview = r["text"].replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:120] + "..."
        print(f"  [{r['rank']}] ({r['chapter']}) {preview}")
    print()


def _run_eval_cli(args: list[str]) -> int:
    input_path = WV_EVAL_CASES_XLSX
    output_path: Path | None = None
    top_k = WV_TOP_K
    i = 0
    while i < len(args):
        flag = args[i]
        if flag in ("--input", "-i") and i + 1 < len(args):
            input_path = Path(args[i + 1]); i += 2
        elif flag in ("--output", "-o") and i + 1 < len(args):
            output_path = Path(args[i + 1]); i += 2
        elif flag == "--top-k" and i + 1 < len(args):
            try:
                top_k = int(args[i + 1])
                if top_k <= 0:
                    raise ValueError
            except ValueError:
                print("--top-k 必须是正整数"); return 2
            i += 2
        else:
            print(f"未知 eval 参数: {flag}")
            print('用法: ... eval [--input xxx.xlsx] [--output yyy.xlsx] [--top-k 3]')
            return 2
    run_eval(input_path=input_path, output_path=output_path, top_k=top_k)
    return 0


def _main(argv: list[str]) -> int:
    """命令分发: build | chat | query "<text>" | dump | init-eval | eval"""
    cmd = argv[0] if argv else "chat"

    if cmd == "build":
        _print_index_summary(build_index())
        return 0
    if cmd == "extract":
        text = extract_doc_text()
        print(f"已提取 {len(text)} 字到: {WV_EXTRACTED_TXT}")
        return 0
    if cmd == "chat":
        interactive_chat()
        return 0
    if cmd == "query":
        if len(argv) < 2:
            print('用法: python -m RAG.rag_worldview query "你的问题"')
            return 2
        retriever = get_retriever()
        _run_query_and_print(" ".join(argv[1:]), retriever, WV_TOP_K)
        return 0
    if cmd == "dump":
        dump_chunks()
        return 0
    if cmd == "init-eval":
        out = init_eval_cases()
        print(f"已写入评测用例模板: {out}  (共 {len(WV_EVAL_CASES)} 条)")
        return 0
    if cmd == "eval":
        return _run_eval_cli(argv[1:])

    print(f"未知命令: {cmd}")
    print('可用命令: build | extract | chat | query "<text>" | dump | init-eval | eval')
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
