# RAG 检索实现说明文档

> 目标:让开发人员仅凭本文档,就能从零手写出一套等价的"文档片段检索"系统。
> 参考实现:`RAG/rag_worldview.py`(世界观文档检索)与其复用的 `RAG/rag_function.py`(函数定义检索)。
> 本文档不假设读者读过源码,但每节会标注对应的函数名,便于对照。

---

## 0. 这套 RAG 在做什么

一句话:**给定用户的一句话,从一篇文档里召回最相关的若干文字片段。**

它不是问答系统,不调用大模型生成答案,只负责"检索"这一环——把文档切成小块、建索引,用户输入时返回 Top-K 最相关的块。返回的块可以直接展示,也可以拼进 LLM 的 prompt 作为上下文(本实现只做到"返回片段")。

核心技术选型:
- **多路召回**:同时用"关键词召回(BM25)"和"语义召回(向量)",再加权合并。单独任何一路都有盲区,合起来更稳。
- **本地嵌入模型**:向量化用本地 BAAI/bge-m3,不依赖联网,不调远程 API。
- **本地向量库**:Chroma,数据落盘到本地目录。
- **中文分词**:BM25 对中文必须先用 jieba 分词,否则等于失效。

---

## 1. 整体架构

分两个阶段:**建索引(离线,跑一次)** 和 **查询(在线,每次输入)**。

### 建索引阶段(`build` 命令)
```
.doc 文档
   │  ① 提取纯文本(保留段落换行)
   ▼
纯文本
   │  ② 切片:按结构切成语义块(每块带标题前缀 + metadata)
   ▼
切片列表 (list[Document])
   ├─③ 嵌入模型把每块向量化 ─→ ④ 写入 Chroma 向量库(落盘)
   └─────────────────────────→ 同时 pickle 缓存切片,供 BM25 启动复用
```

### 查询阶段(`query` / `chat` 命令)
```
用户输入
   │
   ▼
┌─────────────┬──────────────┐
│ BM25 召回    │ 向量召回      │   ← 两路并行
│ (jieba 分词) │ (Chroma 检索) │
└──────┬──────┴──────┬───────┘
       └──── ⑤ Ensemble 加权合并去重 ────┐
                                          ▼
                                 Top-K 片段(带章节/排名)
```

记住这张图,后面每一节就是在实现图里的某个方框。

---

## 2. 依赖与运行环境

### 第三方库(哪些是库、哪些是手写,这点很重要)
| 能力 | 用什么 | 库 or 手写 |
|---|---|---|
| .doc 文本提取 | `win32com`(Word COM 自动化) | 第三方(pywin32) |
| 文本切分(递归切) | `RecursiveCharacterTextSplitter` | 第三方(langchain-text-splitters) |
| 按结构切章节 | `re` 正则 + 手写循环 | 手写(标准库) |
| 短片合并 | 手写列表遍历 | 手写 |
| 嵌入模型 | `HuggingFaceEmbeddings` + bge-m3 | 第三方(langchain-huggingface) |
| 向量库 | `Chroma` | 第三方(langchain-chroma) |
| 关键词召回 | `BM25Retriever` | 第三方(langchain-community + rank-bm25) |
| 中文分词 | `jieba` | 第三方 |
| 多路合并 | `EnsembleRetriever` | 第三方(langchain) |
| Excel 读写 | `openpyxl` | 第三方 |

pip 安装清单(版本仅供参考):
```
langchain-chroma langchain-community langchain-huggingface
langchain-text-splitters jieba rank-bm25 openpyxl
sentence-transformers   # bge-m3 运行时依赖
pywin32                 # 仅 Windows 提取 .doc 需要
```

### 关键环境注意点(踩过的坑)
1. **离线模式**:导入 langchain_huggingface **之前**先设环境变量,否则每次启动会卡在 huggingface.co 的联网检查:
   ```python
   import os
   os.environ.setdefault("HF_HUB_OFFLINE", "1")
   os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
   ```
   代价是模型不会自动更新(想升级时临时删掉这两行联网跑一次)。
2. **中文编码**:Windows 控制台默认 GBK,打印中文会乱码。运行时给 Python 加 `-X utf8`。
3. **虚拟环境**:确保跑在装了 jieba 等依赖的 venv 里,别用系统 python。
4. **bge-m3 首次需联网下载**(~2.3GB),下载后才能开离线模式。

---

## 3. 模块常量(先定好,后面都引用)

```python
from pathlib import Path
import re

_THIS_DIR = Path(__file__).parent.resolve()

# —— 路径 ——
WV_SOURCE_DOC    = _THIS_DIR / "data" / "世界观.doc"          # 源文档
WV_EXTRACTED_TXT = _THIS_DIR / "data" / "_worldview_extracted.txt"  # 提取出的纯文本
WV_PERSIST_DIR   = _THIS_DIR / "data" / "chroma_worldview"   # 向量库落盘目录
WV_DOCS_CACHE    = _THIS_DIR / "data" / "worldview_docs.pkl" # 切片缓存(BM25复用)
WV_CHUNKS_TXT    = _THIS_DIR / "data" / "worldview_chunks.txt" # 切片可读导出
WV_COLLECTION    = "rag_worldview"                            # Chroma collection 名

# —— 切片参数 ——
CHUNK_SIZE    = 300   # 每片目标字数上限
CHUNK_OVERLAP = 60    # 相邻片重叠字数(防句子被边界切断)
MIN_CHARS     = 120   # 短于此的片回填进前一片

# 递归切分器的分隔符,按优先级从粗到细;最后的 "" 兜底硬切
CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "　", "，", ""]

# 章节标题正则:只认 "第X章：" 和 "尾声：",re.M 让 ^$ 按行匹配
CHAPTER_HEADER_RE = re.compile(r"^\s*(第[一二三四五六七八九十]+章[：:].*|尾声[：:].*)$", re.M)

# —— 检索参数 ——
EMBEDDING_MODEL = "BAAI/bge-m3"
WV_TOP_K   = 3            # 返回片段数
WV_WEIGHTS = (0.3, 0.7)   # Ensemble 权重 (BM25, 向量),散文偏语义
```

> 设计提示:把"路径/切片参数/检索参数"集中成常量,换一篇文档时只改这里。换不同结构的文档(如下文"记忆篇章")时,主要改 `CHAPTER_HEADER_RE` 和切片粒度。

(下一节开始讲每一步的实现)

---

## 4. 第一步:提取 .doc 文本(`extract_doc_text`)

**目标**:把二进制 `.doc` 转成纯文本,且**保留段落换行**(换行是后续按结构切片的依据)。

`.doc`(老版 Word,OLE2 格式)不是纯文本,得解析。常见的纯 Python 库(olefile/textract/docx2txt)对 `.doc` 支持都不好,**最可靠的是用 win32com 驱动本机 Word 来读**(代价是必须装 Word、只能在 Windows 跑)。

```python
def extract_doc_text(doc_path=WV_SOURCE_DOC, out_path=WV_EXTRACTED_TXT) -> str:
    import win32com.client   # 延迟导入:非 Windows 环境跑其他命令时不受影响

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    paragraphs = []
    try:
        doc = word.Documents.Open(str(doc_path), ReadOnly=True)
        try:
            for para in doc.Paragraphs:          # 逐段读 → 天然保留段落边界
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
            pass   # Quit 即使成功也常抛 com_error,忽略
    full_text = "\n".join(paragraphs)            # 段落间用 \n 连接
    out_path.write_text(full_text, encoding="utf-8")
    return full_text
```

**三个坑(都已在代码里处理)**:
1. `para.Range.Text` 带表格单元标记 `\x07` 和回车 `\r`,要清掉。
2. **必须在 `word.Quit()` 之前就把文本攒好**——`Quit()` 即使成功也常抛 `com_error -2147023170`,所以包 `try/except` 不让它影响结果。
3. 逐段(`doc.Paragraphs`)读而不是一次性 `doc.Content.Text`,这样段落边界(换行)才能保留;一次性读容易把全文挤成一坨。

> 如果你的源文档是 `.docx`/`.txt`/`.md`,这步可换成 `python-docx` 或直接 `open().read()`,后续步骤不变。提取的产物就是"带 `\n` 的纯文本",这是切片的输入。

---

## 5. 第二步:切片(核心,决定检索质量)

切片好坏直接决定召回质量。原则:**一个切片 = 一个语义完整、主题单一、大小适中的块**。太大→一块混多个主题,向量分不开;太小→信息不足,噪声大。

世界观文档是"章节式叙事"(第一章/第二章/.../尾声,章内还有子段落),所以用**混合策略**:① 先按章节切 → ② 章内太大的再递归子切 → ③ 残留短片回填合并。总入口是 `chunk_worldview`,串起这三步。

### 5.1 按章节切(`_split_into_chapters`)——手写 + 正则

**目的**:沿"章节标题行"把全文切成有序的 `(标题, 正文)` 列表。

用正则找出所有标题的位置,再用"下一个标题的起点"当"本章正文的终点"夹出正文:
```python
def _split_into_chapters(full_text):
    matches = list(CHAPTER_HEADER_RE.finditer(full_text))   # 所有章节头
    if not matches:
        return [("世界观", full_text.strip())]              # 没标题→整篇一块

    chapters = []
    head = full_text[:matches[0].start()].strip()           # 第一个标题前的内容
    if head:
        chapters.append(("序", head))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()                                 # 本标题结尾
        body_end = matches[i+1].start() if i+1 < len(matches) else len(full_text)
        chapters.append((title, full_text[body_start:body_end].strip()))
    return chapters
```

**正则要点**(`CHAPTER_HEADER_RE`):
- `re.M`(多行)让 `^...$` 逐行匹配,而非整篇只匹配一次。
- 只锚定 `第X章：` / `尾声：`,所以文档里的子标题如 `【未被讲述的真相】`**不会**被误判成章节头。

世界观切完得到 5 个章节对。

### 5.2 章内递归子切(`RecursiveCharacterTextSplitter`)——第三方库

**为什么还要切**:有的章 ~700 字且混多个主题(如第三章=日志异常+清除令+残骸传说),整章一片向量分不开。所以每章正文再喂给递归切分器:
```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    separators=CHINESE_SEPARATORS,   # 降级顺序 \n\n→\n→。→！？；→　→，→""
    chunk_size=CHUNK_SIZE,           # 300
    chunk_overlap=CHUNK_OVERLAP,     # 60
    length_function=len,
    keep_separator=True,
)
pieces = splitter.split_text(body)
```

**"递归"的含义**:它按 `separators` 的优先级**逐级降级**切——先用 `\n\n`;某块仍 >300 字就在块内改用 `\n`;再不行用 `。`,继续 `！？；`、全角空格、`，`,最后 `""` 硬切兜底。同时它**贪婪地把相邻小段攒到接近 300 字**,所以原文里的零碎短段会被自然合并成合适大小的片。

- `chunk_overlap=60`:相邻两片重叠 60 字。作用是**防止句子在切片边界被截断后语义丢失**——上一片结尾 60 字会重复出现在下一片开头。
- `separators` 用中文标点:默认英文 splitter 对中文几乎无效,必须显式给中文句末标点。

### 5.3 短片回填合并(`_merge_tiny`)——手写

**为什么需要**:5.2 切完可能留下很短的尾巴片(如某章结尾只剩一句),单独成片信息量低、是检索噪声。把短于 `MIN_CHARS=120` 的片并进**前一片**:
```python
def _merge_tiny(chunks, min_chars=MIN_CHARS):
    if not chunks:
        return []
    merged = []
    for c in chunks:
        if merged and len(c) < min_chars:
            merged[-1] = merged[-1] + "\n" + c     # 短片并进上一片
        else:
            merged.append(c)
    if len(merged) >= 2 and len(merged[0]) < min_chars:  # 首片太短则向后并
        merged[1] = merged[0] + "\n" + merged[1]
        merged = merged[1:]
    return merged
```
**注意它在单章内部调用**(见 5.4 循环),所以**绝不跨章合并**——不会把第三章尾巴并进第四章。

### 5.4 组装成 Document(`chunk_worldview` 主循环)

每个最终片:正文前贴 `【章节标题】`,章节信息同时写进 metadata:
```python
from langchain_core.documents import Document

def chunk_worldview(full_text):
    splitter = RecursiveCharacterTextSplitter(...)   # 见 5.2
    docs, global_idx = [], 0
    for ch_idx, (title, body) in enumerate(_split_into_chapters(full_text)):
        if not body:
            continue
        for piece in _merge_tiny(splitter.split_text(body)):  # ②再③
            piece = piece.strip()
            if not piece:
                continue
            docs.append(Document(
                page_content=f"【{title}】\n{piece}",   # 正文前贴章节标题
                metadata={
                    "chapter": title,
                    "chapter_index": ch_idx,
                    "chunk_index": global_idx,
                    "source": WV_SOURCE_DOC.name,
                },
            ))
            global_idx += 1
    return docs
```

**为什么正文要贴 `【标题】` 前缀**:让 BM25 和向量都能拿到"章节信号"。例如查"空心症"时,第二章标题里就含"空心症",关键词直接命中;向量也因标题语义而更易匹配。metadata 里的 `chapter` 则用于检索后标注命中章节、做评测打分。

**切片参数速查**:
| 常量 | 值 | 作用 |
|---|---|---|
| `CHAPTER_HEADER_RE` | `第X章：/尾声：` | 识别章节头,不误伤【】子标题 |
| `CHUNK_SIZE` | 300 | 每片字数上限 |
| `CHUNK_OVERLAP` | 60 | 相邻片重叠,防边界切断 |
| `MIN_CHARS` | 120 | 短于此回填进前一片 |

世界观最终切出 **11 片**,第四章的"锚点/赛斯/奈奈"干净分成 3 片——这就是混合切片相对"整章一片"的收益。

---

## 6. 第三步:嵌入模型(`build_embeddings`)

把文字变成向量(一串浮点数),语义相近的文字向量距离也近。用本地 bge-m3:
```python
from langchain_huggingface import HuggingFaceEmbeddings

def build_embeddings(model_name=EMBEDDING_MODEL):
    return HuggingFaceEmbeddings(
        model_name=model_name,                       # "BAAI/bge-m3"
        model_kwargs={"device": "cpu"},              # 无 GPU 也能跑;有 CUDA 改 "cuda" 提速
        encode_kwargs={"normalize_embeddings": True},# 向量归一化,配余弦相似度更稳
    )
```
- `device="cpu"`:任何机器都能跑。CPU 上单次查询向量化约 130ms,冷启动加载模型约 4 秒。
- `normalize_embeddings=True`:输出向量归一化。Chroma 默认用余弦相似度,归一化后效果更稳定。
- bge-m3 输出 1024 维向量,中英文都支持。

---

## 7. 第四步:向量库 Chroma(`build_/load_worldview_vector_store`)

向量库负责"存所有切片的向量 + 按相似度检索"。Chroma 是嵌入式的,直接落盘到本地目录,无需起服务。

**建库(build 时跑)**:
```python
from langchain_chroma import Chroma
import shutil, pickle

def build_worldview_vector_store(docs, embeddings):
    if WV_PERSIST_DIR.exists():
        shutil.rmtree(WV_PERSIST_DIR)        # 先清空,保证索引和当前切片一致
    WV_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    vector_store = Chroma.from_documents(    # 自动:逐片向量化 → 写入并落盘
        documents=docs,
        embedding=embeddings,
        persist_directory=str(WV_PERSIST_DIR),
        collection_name=WV_COLLECTION,
    )
    with WV_DOCS_CACHE.open("wb") as f:      # 同时缓存切片,供 BM25 复用
        pickle.dump(docs, f)
    return vector_store
```

**读库(query/chat 时跑)**:
```python
def load_worldview_vector_store(embeddings):
    if not WV_PERSIST_DIR.exists():
        raise FileNotFoundError("向量库不存在,请先 build")
    return Chroma(
        persist_directory=str(WV_PERSIST_DIR),
        embedding_function=embeddings,
        collection_name=WV_COLLECTION,
    )
```

**为什么要 pickle 缓存切片(`WV_DOCS_CACHE`)**:BM25(下一节)需要拿到原始切片列表才能建索引,而切片是在 build 时算好的。把切片 pickle 下来,query 时直接反序列化复用,不用每次重新提取+切片。
```python
def load_worldview_docs():
    with WV_DOCS_CACHE.open("rb") as f:
        return pickle.load(f)
```

> **独立 collection 的意义**:`collection_name` + `persist_directory` 决定了索引存哪。不同文档(世界观 vs 记忆篇章 vs 函数定义)各用一套,互不污染。本项目里函数定义用 `chroma_functions`/`rag_functions`,世界观用 `chroma_worldview`/`rag_worldview`。

---

## 8. 第五步:两路召回器

### 8.1 BM25 关键词召回(`build_bm25_retriever`)——必须配 jieba

BM25 是经典关键词检索算法(按词频/逆文档频率打分)。它默认按空格分词,**对中文几乎无效**("播放音乐"被当成一个词),所以必须传入 jieba 分词函数:
```python
import jieba
from langchain_community.retrievers import BM25Retriever

def _jieba_preprocess(text):
    return [tok for tok in jieba.lcut(text) if tok.strip()]   # "播放音乐"→["播放","音乐"]

def build_bm25_retriever(docs, k=WV_TOP_K):
    retriever = BM25Retriever.from_documents(docs, preprocess_func=_jieba_preprocess)
    retriever.k = k     # 召回数量
    return retriever
```
**这是中文 RAG 最容易踩的坑**:不传 `preprocess_func`,BM25 等于废了。

### 8.2 向量语义召回(`build_vector_retriever`)

把 Chroma 包成 LangChain 统一的 Retriever 接口(供下面 Ensemble 合并):
```python
def build_vector_retriever(vector_store, k=WV_TOP_K):
    return vector_store.as_retriever(search_kwargs={"k": k})
```

### 8.3 多路加权合并(`build_ensemble_retriever`)

`EnsembleRetriever` 把两路结果按权重融合(用 RRF 倒数排名融合),去重后给出最终排序:
```python
from langchain.retrievers import EnsembleRetriever   # 1.x 在 langchain_classic.retrievers

def build_ensemble_retriever(bm25, vector, weights=WV_WEIGHTS):
    return EnsembleRetriever(retrievers=[bm25, vector], weights=list(weights))
```
- `weights=(0.3, 0.7)` 含义 = (BM25 权重, 向量权重)。世界观是散文,语义匹配更重要,所以向量权重高;但 BM25 仍能兜底实体词(空心症/锚点/神经调节芯片)。
- 函数定义检索那套用 (0.4, 0.6),因为函数名/关键词更重要,BM25 权重适当调高。**权重要按数据特点调**。

### 8.4 三件一起装好(`_build_three_retrievers`)

query/chat/eval 都要这三个对象,封一个统一构建函数:
```python
def _build_three_retrievers(top_k=WV_TOP_K, weights=WV_WEIGHTS):
    embeddings = build_embeddings()
    vector_store = load_worldview_vector_store(embeddings)
    docs = load_worldview_docs()              # pickle 复用,不重新切片
    bm25 = build_bm25_retriever(docs, k=top_k)
    vector = build_vector_retriever(vector_store, k=top_k)
    ensemble = build_ensemble_retriever(bm25, vector, weights=weights)
    return bm25, vector_store, ensemble
```

---

## 9. 查询(`query`)

把上面拼起来,给一句话返回 Top-K 片段:
```python
def query(text, top_k=WV_TOP_K, retriever=None):
    if retriever is None:
        retriever = get_retriever(top_k=top_k)   # = _build_three_retrievers 的 ensemble
    docs = retriever.invoke(text)[:top_k]
    return [
        {
            "rank": i,
            "chapter": d.metadata.get("chapter", ""),
            "chunk_index": d.metadata.get("chunk_index", -1),
            "text": d.page_content,
        }
        for i, d in enumerate(docs, start=1)
    ]
```
`retriever.invoke(text)` 内部会:① 把 text 交给 BM25(jieba 分词后打分)② 把 text 向量化后在 Chroma 找近邻 ③ Ensemble 按权重融合两路、去重、排序。返回的每条带 `chapter`(命中哪章)和完整 `text`。

---

## 10. 多轮对话式检索(`interactive_chat`)

在单次 query 之上加"会话循环 + 上下文记忆",但**不调用 LLM**,每轮只返回召回片段。

核心难点是**上下文该不该拼**:
- 用户说"它是怎么被发现的"——这是**追问**,"它"指代上一轮的话题,必须把历史拼进检索 query 才能消解指代。
- 用户说"锚点是什么"——这是**新话题**,如果把上一轮的"空心症"也拼进去,反而会把检索结果拽回旧章节(实测会偏)。

所以用一个轻量启发式判断"是不是追问",**只有追问才拼历史**:
```python
_ANAPHORA   = ("它","他","她","这","那","其","刚才","刚刚","刚说","上面","前面","上述")
_CONTINUERS = ("然后","后来","为什么","为啥","还有","接着","继续","结果","所以","再说说","展开","详细")

def _is_followup(text):
    if any(a in text for a in _ANAPHORA):       # 含指代词 → 追问
        return True
    stripped = text.rstrip("呢吗啊吧？?。.！! ")
    return stripped in _CONTINUERS              # 整句就是个承接词 → 追问

def _build_context_query(history, current, history_turns):
    if history and _is_followup(current):
        prior = history[-(history_turns - 1):]  # 拼最近几轮
        return " ".join(prior + [current])
    return current                              # 新话题:只用当前句
```
> **注意不要用"句子长度"判断追问**:"锚点是什么"很短但是完整新话题。早期版本用长度阈值,结果短问句被误判成追问、检索被带偏。改成"指代词/承接词"判据后正常。

聊天循环(简化):
```python
def interactive_chat(top_k=WV_TOP_K, weights=WV_WEIGHTS, history_turns=3):
    bm25, vector_store, ensemble = _build_three_retrievers(top_k, weights)
    history = []
    while True:
        line = input("你 >>> ").strip()
        if line in (":quit", ":q", "exit"): break
        if line == ":reset": history.clear(); continue
        # ... :history / :k N / :debug 等命令 ...
        ctx_query = _build_context_query(history, line, history_turns)
        results = query(ctx_query, top_k=top_k, retriever=ensemble)
        _print_recall_results(line, ctx_query, results)   # 打印完整片段
        history.append(line)
```
命令:`:quit` 退出 | `:k N` 改 top_k | `:reset` 清空历史 | `:history` 看历史 | `:debug` 三路并排调试视图。

---

## 11. 评测(Excel I/O)

用一批"问题→期望章节"的用例,量化检索效果。

**用例与判分**:
```python
WV_EVAL_CASES = [
    ("什么是空心症", "第二章"),
    ("锚点是什么", "第四章"),
    ("ECHO为什么被销毁", "第三章"),
    # ...
]

def _rank_of_chapter(expected, chapters):       # chapters=召回片段的章节序列
    if not expected: return "N/A"
    for i, ch in enumerate(chapters):
        if expected in ch:                       # 包含匹配(标题带括号副标)
            return i + 1                          # 1-based 排名
    return "未召回"
```

**跑评测**:对每条用例分别跑 BM25/向量/Ensemble 三路,记录期望章节在各路 Top-K 里的排名,写进新 Excel:
```python
def run_eval(input_path=WV_EVAL_CASES_XLSX, output_path=None, top_k=WV_TOP_K, weights=WV_WEIGHTS):
    cases = _read_eval_cases(input_path)
    bm25, vector_store, ensemble = _build_three_retrievers(top_k, weights)
    if output_path is None:
        output_path = WV_EVAL_RESULTS_DIR / f"worldview_eval_results_{_timestamp()}.xlsx"  # 带时间戳,不覆盖
    # ... 逐条检索,_rank_of_chapter 算排名,openpyxl 写: 用户说的话/期望章节/是否命中TopK/命中章节/三路排名 ...
```
- **结果文件带时间戳,绝不覆盖旧结果**——调完参数重跑能横向对比。
- 关注指标:**TopK 命中率**(期望章节是否进了前 K)和 **Ensemble 排名第 1 的比例**。世界观 18 条用例当前 100% 命中、15/18 排第 1。

---

## 12. 命令行入口(`_main`)

```python
def _main(argv):
    cmd = argv[0] if argv else "chat"
    if cmd == "build":     _print_index_summary(build_index()); return 0   # 提取+切片+建库
    if cmd == "extract":   extract_doc_text(); return 0                     # 仅提取
    if cmd == "chat":      interactive_chat(); return 0
    if cmd == "query":     _run_query_and_print(" ".join(argv[1:]), get_retriever(), WV_TOP_K); return 0
    if cmd == "dump":      dump_chunks(); return 0                          # 导出切片到 txt 供核对
    if cmd == "init-eval": init_eval_cases(); return 0                      # 生成用例模板
    if cmd == "eval":      return _run_eval_cli(argv[1:])
```
运行(Windows + venv + utf8):
```
python -X utf8 -m RAG.rag_worldview build
python -X utf8 -m RAG.rag_worldview query "什么是空心症"
python -X utf8 -m RAG.rag_worldview chat
python -X utf8 -m RAG.rag_worldview eval
```

`build` 后建议 `dump` 看一眼 `worldview_chunks.txt`,人工核对切片边界是否合理——这是调切片参数最直接的反馈。

---

## 13. 换一篇新文档怎么改(实战:记忆篇章)

本套实现里"嵌入/向量库/BM25/Ensemble/查询/评测"全是通用的,**换文档只需改"提取+切片"和路径常量**。

判断切片策略的关键:**看新文档的天然结构单元**。
- 世界观是"章节式,章内混多主题"→ 需要"章节切 + 章内递归子切 + 短片合并"。
- "记忆篇章"是"10 个依恋度 Lv,每个 Lv 一段独立回忆(~230 字,主题单一)"→ **每个 Lv 本身就是理想切片**,只需改标题正则切成 10 段,**第②步递归子切和第③步合并基本可省**(除非某 Lv 超长再兜底切)。

改动清单:
1. 新增标题正则:`re.compile(r"【依恋度\s*Lv\.?\s*\d+\s*解锁】.*")`,替换 `_split_into_chapters` 里用的正则(或参数化)。
2. 切片函数:默认"一标题一片",仅当某片 > `CHUNK_SIZE*1.5` 时才递归子切。
3. 路径/collection 换成 `chroma_memory` / `memory_docs.pkl` / `rag_memory`,与世界观隔离。
4. metadata 把 `chapter` 换成 `level`(等级名),其余结构不变。
5. 评测用例换成"记忆类问题→期望 Lv"。

> 一般原则:**文档有清晰的结构标记(标题/编号/Lv)就优先沿标记切,一个结构单元一片;单元过大且混主题才追加递归子切;过小才合并。** 切完一定 dump 出来人眼看一遍。

---

## 14. 常见坑速查

| 现象 | 原因 | 解决 |
|---|---|---|
| BM25 中文召回全乱 | 没传 jieba 分词 | `preprocess_func=_jieba_preprocess` |
| 启动卡在联网/超时 | 没开离线模式 | import 前设 `HF_HUB_OFFLINE=1` |
| 中文打印乱码 | 控制台 GBK | `python -X utf8` |
| `.doc` 提取后全挤成一坨 | 一次性读 Content | 逐段 `doc.Paragraphs` 读 |
| `word.Quit()` 报 com_error | Word COM 已知问题 | 文本先存好,Quit 包 try/except |
| 一块混多个主题、召回分不开 | 切片太大 | 调小 chunk_size 或按结构切 |
| 短问句检索被历史带偏 | 用长度判断追问 | 改用指代词/承接词判据 |
| 重跑评测覆盖了旧结果 | 输出固定文件名 | 输出加时间戳 |
