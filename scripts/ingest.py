"""
文章切片 + 向量化入库模块
读取 /raw/ 目录下的 markdown 文章，按段落切片后通过 OpenAI Embedding 存入 Chroma。
"""

import os
import re
import yaml
import hashlib
from pathlib import Path
from typing import Optional

import chromadb
from openai import OpenAI


def load_settings() -> dict:
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    if os.environ.get("OPENAI_API_KEY"):
        settings["openai"]["api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("OPENAI_BASE_URL"):
        settings["openai"]["base_url"] = os.environ["OPENAI_BASE_URL"]

    return settings


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent


def get_data_root() -> Path:
    """获取数据根目录；云端可通过 DATA_DIR 重定向到持久化卷。"""
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        return Path(data_dir)
    return get_project_root()


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    解析 markdown 文件的 frontmatter 和正文。
    返回 (metadata_dict, body_text)
    """
    metadata = {}
    body = content

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        body = match.group(2)

    return metadata, body.strip()


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """
    按段落切片文本。
    策略：先按段落分割，再合并小段落 / 拆分大段落，保证每块在 chunk_size 左右。
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # 如果单段落超过 chunk_size，按句子拆分
        if len(para) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            sentences = re.split(r"(?<=[。！？；\.\!\?\;])", para)
            sub_chunk = ""
            for sent in sentences:
                if not sent.strip():
                    continue
                if len(sub_chunk) + len(sent) > chunk_size:
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                    # overlap：保留上一块尾部部分
                    sub_chunk = sub_chunk[-overlap:] + sent if sub_chunk else sent
                else:
                    sub_chunk += sent
            if sub_chunk.strip():
                chunks.append(sub_chunk.strip())
            continue

        # 正常段落合并逻辑
        if len(current_chunk) + len(para) + 1 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # overlap
            current_chunk = current_chunk[-overlap:] + "\n" + para if current_chunk else para
        else:
            current_chunk = current_chunk + "\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def get_chroma_client(settings: dict) -> chromadb.PersistentClient:
    """获取 Chroma 持久化客户端"""
    root = get_data_root()
    chroma_path = root / settings["paths"]["chroma_dir"]
    return chromadb.PersistentClient(path=str(chroma_path))


def get_collection(client: chromadb.PersistentClient, settings: dict):
    """获取或创建 collection"""
    return client.get_or_create_collection(
        name=settings["ingest"]["collection_name"],
        metadata={"hnsw:space": "cosine"},
    )


def compute_file_hash(file_path: Path) -> str:
    """计算文件内容的 MD5 哈希，用于判断是否已入库"""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


def get_embeddings(texts: list[str], settings: dict) -> list[list[float]]:
    """调用 OpenAI Embedding API（支持代理 base_url）"""
    client_kwargs = {"api_key": settings["openai"]["api_key"]}
    if settings["openai"].get("base_url"):
        client_kwargs["base_url"] = settings["openai"]["base_url"]
    client = OpenAI(**client_kwargs)
    response = client.embeddings.create(
        model=settings["openai"]["embedding_model"],
        input=texts,
    )
    return [item.embedding for item in response.data]


def ingest_article(file_path: str, settings: Optional[dict] = None) -> dict:
    """
    对指定文章文件执行切片 + embedding + 入库。
    返回 {"status": "ok"/"skipped"/"error", "chunks": int, "file": str, "message": str}
    """
    if settings is None:
        settings = load_settings()

    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "chunks": 0, "file": str(path), "message": "文件不存在"}

    if not path.suffix == ".md":
        return {"status": "error", "chunks": 0, "file": str(path), "message": "仅支持 .md 文件"}

    content = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(content)

    if not body:
        return {"status": "skipped", "chunks": 0, "file": str(path), "message": "文章正文为空"}

    file_hash = compute_file_hash(path)

    client = get_chroma_client(settings)
    collection = get_collection(client, settings)

    # 检查是否已入库（通过 file_hash 元数据）
    existing = collection.get(where={"file_hash": file_hash})
    if existing and existing["ids"]:
        return {
            "status": "skipped",
            "chunks": len(existing["ids"]),
            "file": str(path),
            "message": f"文件已入库（{len(existing['ids'])} 个切片）",
        }

    # 切片
    chunk_size = settings["ingest"].get("chunk_size", 400)
    chunk_overlap = settings["ingest"].get("chunk_overlap", 50)
    chunks = chunk_text(body, chunk_size=chunk_size, overlap=chunk_overlap)

    if not chunks:
        return {"status": "skipped", "chunks": 0, "file": str(path), "message": "切片结果为空"}

    # Embedding
    embeddings = get_embeddings(chunks, settings)

    # 准备元数据
    title = metadata.get("标题", path.stem)
    date = str(metadata.get("日期", "未知"))
    source = metadata.get("来源", "未知")
    link = metadata.get("链接", "")

    ids = [f"{file_hash}_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "title": title,
            "date": date,
            "source": source,
            "link": link,
            "file_name": path.name,
            "file_hash": file_hash,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    # 入库
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )

    return {
        "status": "ok",
        "chunks": len(chunks),
        "file": str(path),
        "message": f"成功入库 {len(chunks)} 个切片，标题：{title}",
    }


def ingest_all_raw(settings: Optional[dict] = None) -> list[dict]:
    """
    批量处理 /raw/ 目录下所有 .md 文件。
    返回每个文件的入库结果列表。
    """
    if settings is None:
        settings = load_settings()

    root = get_data_root()
    raw_dir = root / settings["paths"]["raw_dir"]

    if not raw_dir.exists():
        return [{"status": "error", "chunks": 0, "file": str(raw_dir), "message": "raw 目录不存在"}]

    results = []
    md_files = sorted(raw_dir.glob("*.md"))

    if not md_files:
        return [{"status": "skipped", "chunks": 0, "file": str(raw_dir), "message": "raw 目录下没有 .md 文件"}]

    for md_file in md_files:
        result = ingest_article(str(md_file), settings)
        results.append(result)

    return results


def search_knowledge_base(
    query: str, top_k: int = 5, settings: Optional[dict] = None
) -> list[dict]:
    """
    向量检索知识库，返回与 query 最相关的 N 段内容。
    """
    if settings is None:
        settings = load_settings()

    client = get_chroma_client(settings)
    collection = get_collection(client, settings)

    # 获取 query 的 embedding
    query_embedding = get_embeddings([query], settings)[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    items = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else None
            items.append(
                {
                    "content": doc,
                    "title": meta.get("title", "未知"),
                    "date": meta.get("date", "未知"),
                    "source": meta.get("source", "未知"),
                    "relevance_score": round(1 - distance, 4) if distance is not None else None,
                }
            )

    return items


if __name__ == "__main__":
    # 独立运行时：批量入库 /raw/ 下所有文章
    results = ingest_all_raw()
    for r in results:
        print(f"[{r['status']}] {r['file']}: {r['message']}")
