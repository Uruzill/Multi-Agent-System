"""
ChromaDB 知识库封装 —— 建库、检索、文档管理。

依赖：langchain-community, chromadb, sentence-transformers
首次运行会自动下载 BAAI/bge-small-zh-v1.5 嵌入模型。

自 Task 4 起，所有函数均需 user_id 参数，实现按用户物理隔离存储。
"""

import os
import shutil
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_embeddings = None
_vectorstores = {}  # 按 user_id 缓存 vectorstore，替换原来的全局单例


def _get_user_dirs(user_id: str):
    """返回 (documents_dir, chroma_db_dir)，按 user_id 物理隔离。
    目录不存在时自动创建。"""
    docs = os.path.join(BASE_DIR, "rag", "documents", user_id)
    db = os.path.join(BASE_DIR, "rag", "chroma_db", user_id)
    os.makedirs(docs, exist_ok=True)
    os.makedirs(db, exist_ok=True)
    return docs, db


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={"local_files_only": True},
        )
    return _embeddings


def _get_vectorstore(user_id: str):
    """按 user_id 加载向量库，每个用户独立缓存。"""
    if user_id not in _vectorstores:
        docs_dir, persist_dir = _get_user_dirs(user_id)
        emb = _get_embeddings()
        if os.path.exists(os.path.join(persist_dir, "chroma.sqlite3")):
            _vectorstores[user_id] = Chroma(
                persist_directory=persist_dir,
                embedding_function=emb,
            )
    return _vectorstores.get(user_id)


def build_index(user_id: str):
    """扫描用户文档目录下所有 PDF/TXT，重建索引。
    先删除旧 collection，确保不会累积重复切片。"""
    global _vectorstores

    docs_dir, persist_dir = _get_user_dirs(user_id)

    # 1. 先清除该用户的缓存，显式关闭旧连接释放 SQLite 锁
    old_vs = _vectorstores.pop(user_id, None)
    if old_vs is not None and hasattr(old_vs, "_client"):
        try:
            old_vs._client.close()
            if hasattr(old_vs._client, "_system"):
                old_vs._client._system.stop()
        except Exception:
            pass

    # 2. 删除旧 collection + 数据文件（直接删文件比用 PersistentClient 更可靠）
    db_path = os.path.join(persist_dir, "chroma.sqlite3")
    for _ in range(10):
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
            break
        except PermissionError:
            import time
            time.sleep(0.3)
    # 清理 ChromaDB 1.5 的 UUID 子目录（存放向量数据）
    for item in os.listdir(persist_dir):
        item_path = os.path.join(persist_dir, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path, ignore_errors=True)

    # 3. 扫描文档
    emb = _get_embeddings()
    docs = []
    for fname in os.listdir(docs_dir):
        fpath = os.path.join(docs_dir, fname)
        if fname.endswith(".pdf"):
            loader = PyPDFLoader(fpath)
            docs.extend(loader.load())
        elif fname.endswith(".txt"):
            loader = TextLoader(fpath, encoding="utf-8")
            docs.extend(loader.load())

    if not docs:
        return 0

    # 4. 切分
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300, chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    # 过滤空内容切片（扫描版 PDF 无法提取文字时会生成空 page_content）
    chunks = [c for c in chunks if c.page_content and c.page_content.strip()]
    if not chunks:
        return 0

    # 5. 创建新 collection
    Chroma.from_documents(
        documents=chunks,
        embedding=emb,
        persist_directory=persist_dir,
    )

    return len(chunks)


def search(query: str, user_id: str, k: int = 3, min_score: float = 0.40) -> list[str]:
    """检索用户知识库，返回前 k 条结果（含页码 + 相关度），低于 min_score 的结果被丢弃"""
    vs = _get_vectorstore(user_id)
    if vs is None:
        return []
    docs_with_scores = vs.similarity_search_with_relevance_scores(query, k=k)
    result = []
    for d, score in docs_with_scores:
        if score < min_score:
            continue
        page = d.metadata.get("page", "?")
        content = d.page_content[:300]  # 截断避免过长
        result.append(f"[第{page+1}页, 相关度{score:.2f}] {content}")
    return result


def get_document_list(user_id: str) -> list[str]:
    """列出用户 documents/ 下的文件名"""
    docs_dir, _ = _get_user_dirs(user_id)
    if not os.path.exists(docs_dir):
        return []
    return [f for f in os.listdir(docs_dir)
            if f.endswith((".pdf", ".txt"))]


def get_stats(user_id: str) -> dict:
    """返回用户知识库统计信息（不触发模型下载）"""
    docs = get_document_list(user_id)
    _, persist_dir = _get_user_dirs(user_id)
    db_path = os.path.join(persist_dir, "chroma.sqlite3")
    if not os.path.exists(db_path):
        return {"文档数": len(docs), "切片数": 0, "就绪": False}
    vs = _get_vectorstore(user_id)
    if vs is None:
        return {"文档数": len(docs), "切片数": 0, "就绪": False}
    return {"文档数": len(docs), "切片数": vs._collection.count(), "就绪": True}
