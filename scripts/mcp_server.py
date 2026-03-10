"""
Jason 财经知识库 MCP Server
注册所有工具供 Claude Desktop 调用。
"""

import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from ingest import (
    ingest_article as _ingest_article,
    ingest_all_raw as _ingest_all_raw,
    search_knowledge_base as _search_kb,
    load_settings,
    get_project_root,
    get_data_root,
)
from crawl import crawl_article as _crawl_article

# 初始化 MCP Server
mcp = FastMCP("jason-kb")


def _get_settings() -> dict:
    return load_settings()


def _resolve_path(relative: str) -> Path:
    """将配置中的相对路径解析为绝对路径"""
    return get_data_root() / relative


def _get_auth_token() -> str:
    return os.environ.get("AUTH_TOKEN", "").strip()


def _is_authorized(headers: Optional[dict] = None) -> bool:
    """本地未配置 AUTH_TOKEN 时跳过校验；云端要求 Bearer token 精确匹配。"""
    expected_token = _get_auth_token()
    if not expected_token:
        return True

    headers = headers or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        return False

    provided_token = auth_header[len("Bearer ") :].strip()
    return provided_token == expected_token


def _build_sse_app():
    """构建带 Bearer auth 的 SSE app。未配置 AUTH_TOKEN 时不加鉴权。"""
    app = mcp.sse_app("/sse")
    if not _get_auth_token():
        return app

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path in ("/", "/healthz"):
                return await call_next(request)
            if not _is_authorized(dict(request.headers)):
                return PlainTextResponse("Unauthorized", status_code=401)
            return await call_next(request)

    app.add_middleware(BearerAuthMiddleware)
    return app


def _resolve_profile_paths(settings: dict, profile: Optional[str] = None) -> tuple[str, Path, Path]:
    """根据 profile 名解析财务档案与建议历史路径。兼容旧版单档案配置。"""
    profiles_cfg = settings.get("profiles") or {}
    people = profiles_cfg.get("people") if isinstance(profiles_cfg, dict) else None

    if isinstance(people, dict) and people:
        default_profile = profiles_cfg.get("default") or next(iter(people.keys()))
        selected = (profile or default_profile).strip()

        if selected not in people:
            available = ", ".join(people.keys())
            raise ValueError(f"无效 profile：{selected}。可选：{available}")

        person_cfg = people[selected] or {}
        financial_rel = person_cfg.get("financial_yaml")
        advice_rel = person_cfg.get("advice_history")
        if not financial_rel or not advice_rel:
            raise ValueError(f"profile 配置不完整：{selected}")

        return selected, _resolve_path(financial_rel), _resolve_path(advice_rel)

    # 兼容旧配置：仍使用 paths.financial_yaml / paths.advice_history
    financial_rel = settings["paths"]["financial_yaml"]
    advice_rel = settings["paths"]["advice_history"]
    return "default", _resolve_path(financial_rel), _resolve_path(advice_rel)


# ============================================================
# 工具 1: search_knowledge_base
# ============================================================
@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """向量检索知识库，返回与 query 最相关的 N 段内容，附带来源文章标题和日期。

    Args:
        query: 搜索关键词或问题
        top_k: 返回最相关的结果数量，默认 5
    """
    settings = _get_settings()
    results = _search_kb(query, top_k=top_k, settings=settings)

    if not results:
        return "知识库中未找到相关内容。请确认知识库是否已入库文章。"

    output_parts = []
    for i, item in enumerate(results, 1):
        score = item.get("relevance_score", "N/A")
        output_parts.append(
            f"【结果 {i}】相关度: {score}\n"
            f"标题: {item['title']}\n"
            f"日期: {item['date']}\n"
            f"来源: {item['source']}\n"
            f"内容:\n{item['content']}\n"
        )

    return "\n---\n".join(output_parts)


# ============================================================
# 工具 2: get_financial_profile
# ============================================================
@mcp.tool()
def get_financial_profile(profile: Optional[str] = None) -> str:
    """读取用户当前财务状态，返回 financial.yaml 的结构化内容。

    Args:
        profile: 档案名，可选（如“墨烦”）。未传时使用默认档案。
    """
    settings = _get_settings()
    try:
        profile_name, fp_path, _ = _resolve_profile_paths(settings, profile)
    except ValueError as e:
        return str(e)

    if not fp_path.exists():
        return f"财务档案文件不存在（profile={profile_name}）：{fp_path}"

    content = fp_path.read_text(encoding="utf-8")
    return f"用户财务档案（profile={profile_name}）:\n\n{content}"


# ============================================================
# 工具 3: update_financial_profile
# ============================================================
@mcp.tool()
def update_financial_profile(field: str, value: str, profile: Optional[str] = None) -> str:
    """更新 financial.yaml 中的指定字段，并记录更新时间。

    Args:
        field: 要更新的字段路径，用点号分隔，如 "资产.A股" 或 "风险偏好"
        value: 新的值
        profile: 档案名，可选（如“墨烦”）。未传时使用默认档案。
    """
    settings = _get_settings()
    try:
        profile_name, fp_path, _ = _resolve_profile_paths(settings, profile)
    except ValueError as e:
        return str(e)

    if not fp_path.exists():
        return f"财务档案文件不存在（profile={profile_name}）：{fp_path}"

    with open(fp_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 解析字段路径
    keys = field.split(".")
    target = data
    for key in keys[:-1]:
        if key not in target or not isinstance(target[key], dict):
            return f"字段路径无效：{field}"
        target = target[key]

    last_key = keys[-1]

    # 尝试转换数值
    try:
        parsed_value = int(value)
    except ValueError:
        try:
            parsed_value = float(value)
        except ValueError:
            parsed_value = value

    old_value = target.get(last_key, "（不存在）")
    target[last_key] = parsed_value

    # 更新时间戳
    data["更新时间"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(fp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    return f"已更新（profile={profile_name}）[{field}]: {old_value} → {parsed_value}（更新时间: {data['更新时间']}）"


# ============================================================
# 工具 4: ingest_article
# ============================================================
@mcp.tool()
def ingest_article(file_path: str) -> str:
    """对指定文章文件执行切片 + embedding + 入库，返回入库状态和切片数量。

    Args:
        file_path: 文章 .md 文件的路径（绝对路径或相对于项目根目录的路径）
    """
    settings = _get_settings()

    path = Path(file_path)
    if not path.is_absolute():
        path = get_data_root() / file_path

    result = _ingest_article(str(path), settings)
    return f"[{result['status']}] {result['message']}"


# ============================================================
# 工具 5: ingest_all_raw
# ============================================================
@mcp.tool()
def ingest_all_raw() -> str:
    """批量处理 /raw/ 目录下所有尚未入库的文章，返回每篇文章的入库状态。"""
    settings = _get_settings()
    results = _ingest_all_raw(settings)

    lines = []
    ok_count = 0
    skip_count = 0
    err_count = 0

    for r in results:
        lines.append(f"[{r['status']}] {r['file']}: {r['message']}")
        if r["status"] == "ok":
            ok_count += 1
        elif r["status"] == "skipped":
            skip_count += 1
        else:
            err_count += 1

    summary = f"\n--- 汇总 ---\n新入库: {ok_count} | 已跳过: {skip_count} | 失败: {err_count}"
    return "\n".join(lines) + summary


# ============================================================
# 工具 6: trigger_crawl
# ============================================================
@mcp.tool()
def trigger_crawl(url: str, source: str = "公众号") -> str:
    """接收一个 URL，爬取正文，自动保存到 /raw/ 并调用入库。

    Args:
        url: 文章的 URL 地址
        source: 来源，填 "公众号" 或 "知识星球"
    """
    settings = _get_settings()

    # 第一步：爬取并保存
    crawl_result = _crawl_article(url, source, settings)

    if crawl_result["status"] != "ok":
        return f"爬取失败: {crawl_result['message']}"

    # 第二步：入库
    ingest_result = _ingest_article(crawl_result["file_path"], settings)

    return (
        f"爬取成功: {crawl_result['title']}\n"
        f"文件: {crawl_result['file_path']}\n"
        f"入库: [{ingest_result['status']}] {ingest_result['message']}"
    )


# ============================================================
# 工具 7: get_recent_articles
# ============================================================
@mcp.tool()
def get_recent_articles(n: int = 10) -> str:
    """返回最近入库的 N 篇文章标题和日期，用于确认知识库更新状态。

    Args:
        n: 返回的文章数量，默认 10
    """
    settings = _get_settings()
    raw_dir = _resolve_path(settings["paths"]["raw_dir"])

    if not raw_dir.exists():
        return "raw 目录不存在"

    md_files = sorted(raw_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    if not md_files:
        return "raw 目录下没有文章"

    articles = []
    for f in md_files[:n]:
        content = f.read_text(encoding="utf-8")
        # 快速解析 frontmatter
        import re
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                meta = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                meta = {}
        else:
            meta = {}

        title = meta.get("标题", f.stem)
        date = str(meta.get("日期", "未知"))
        source = meta.get("来源", "未知")
        articles.append(f"- [{date}] {title}（{source}）")

    return f"最近 {len(articles)} 篇文章:\n" + "\n".join(articles)


# ============================================================
# 工具 8: get_advice_history
# ============================================================
@mcp.tool()
def get_advice_history(n: int = 5, profile: Optional[str] = None) -> str:
    """返回最近 N 条建议记录，帮助维持建议的连贯性。

    Args:
        n: 返回的建议数量，默认 5
        profile: 档案名，可选（如“墨烦”）。未传时使用默认档案。
    """
    settings = _get_settings()
    try:
        profile_name, _, ah_path = _resolve_profile_paths(settings, profile)
    except ValueError as e:
        return str(e)

    if not ah_path.exists():
        return f"建议历史文件不存在（profile={profile_name}）：{ah_path}"

    content = ah_path.read_text(encoding="utf-8")

    # 按 ## 分割为各条建议
    import re
    entries = re.split(r"\n(?=## \d{4}-\d{2}-\d{2})", content)
    # 过滤掉非建议内容（如文件头部注释）
    advice_entries = [e.strip() for e in entries if e.strip().startswith("## ")]

    if not advice_entries:
        return "暂无历史建议记录"

    # 取最近 n 条
    recent = advice_entries[-n:]
    return f"最近 {len(recent)} 条建议（profile={profile_name}）:\n\n" + "\n\n---\n\n".join(recent)


# ============================================================
# 工具 9: save_advice
# ============================================================
@mcp.tool()
def save_advice(advice: str, profile: Optional[str] = None) -> str:
    """将本次生成的建议追加写入 advice_history.md，附带时间戳。

    Args:
        advice: 建议内容
        profile: 档案名，可选（如“墨烦”）。未传时使用默认档案。
    """
    settings = _get_settings()
    try:
        profile_name, _, ah_path = _resolve_profile_paths(settings, profile)
    except ValueError as e:
        return str(e)

    ah_path.parent.mkdir(parents=True, exist_ok=True)
    if not ah_path.exists():
        ah_path.write_text("# 理财建议历史\n", encoding="utf-8")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n## {timestamp}\n\n{advice}\n"

    with open(ah_path, "a", encoding="utf-8") as f:
        f.write(entry)

    return f"建议已保存（profile={profile_name}，{timestamp}）"


# ============================================================
# 启动
# ============================================================
def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "sse":
        port = int(os.environ.get("PORT", "8080"))
        if _get_auth_token():
            import uvicorn

            uvicorn.run(_build_sse_app(), host="0.0.0.0", port=port)
        else:
            mcp.run(
                transport="sse",
                host="0.0.0.0",
                port=port,
            )
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
