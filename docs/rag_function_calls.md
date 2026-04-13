# 极简本地 RAG 函数调用文档

## 概述
`rag_local.py` 仅保留两个公开函数：

- `upload_docs`：传入文件目录并重建本地索引
- `search_docs`：输入问题并返回检索结果

实现边界：

- 仅做检索，不做模型生成
- 每次上传都全量重建索引
- 仅支持目录递归扫描 `*.txt` / `*.md` / `*.pdf`
- 文本文件按 `UTF-8` 读取

## 函数签名

```python
def upload_docs(
    doc_dir: str | Path,
    persist_dir: str | Path = Path("data/chroma_rag"),
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
) -> dict[str, Any]
```

```python
def search_docs(
    query: str,
    persist_dir: str | Path = Path("data/chroma_rag"),
    top_k: int = 4,
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
) -> list[dict[str, str]]
```

## 固定策略

- 分块参数固定在模块内：`chunk_size=500`、`chunk_overlap=100`
- 不暴露分块参数给调用方
- 不做自定义纠错、重试、参数兜底

## 返回结构

### `upload_docs(...) -> dict`

```json
{
  "doc_dir": "知识库绝对路径",
  "persist_dir": "向量库绝对路径",
  "source_file_count": 0,
  "document_count": 0,
  "chunk_count": 0,
  "embedding_model": "BAAI/bge-small-zh-v1.5"
}
```

### `search_docs(...) -> list[dict]`

返回列表中的每一项结构如下：

```json
{
  "source": "来源文件绝对路径",
  "content": "检索到的切片内容"
}
```

## 异常说明

- 不做额外自定义异常包装
- 非法路径、空目录、不可解码文本、空问题、无索引等场景，行为由底层库决定（可能抛异常，也可能返回空结果）

## Python 调用示例

```python
from rag_local import upload_docs, search_docs

# 1) 传文件目录并重建索引
index_info = upload_docs(
    doc_dir="data/knowledge",
    persist_dir="data/chroma_rag",
    embedding_model="BAAI/bge-small-zh-v1.5",
)
print(index_info)

# 2) 提问并检索
results = search_docs(
    query="这个项目主要是做什么的？",
    persist_dir="data/chroma_rag",
    top_k=3,
)
print(results)
```
