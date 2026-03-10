"""
爬取脚本
接收 URL，提取正文内容，保存为标准格式的 .md 文件到 /raw/ 目录。
支持公众号文章和知识星球内容。
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import yaml
from bs4 import BeautifulSoup
from markdownify import markdownify as md


def load_settings() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def get_data_root() -> Path:
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        return Path(data_dir)
    return get_project_root()


def sanitize_filename(title: str) -> str:
    """清理标题，生成合法文件名"""
    # 移除不适合作文件名的字符
    clean = re.sub(r'[\\/*?:"<>|]', "", title)
    clean = clean.strip()
    # 截断过长的标题
    if len(clean) > 50:
        clean = clean[:50]
    return clean


def extract_wechat_article(url: str, settings: dict) -> dict:
    """
    提取微信公众号文章内容。
    返回 {"title": str, "body": str, "date": str}
    """
    headers = {"User-Agent": settings["crawl"]["user_agent"]}
    timeout = settings["crawl"].get("timeout", 30)

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取标题
    title_tag = soup.find("h1", class_="rich_media_title") or soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "未知标题"

    # 提取正文
    content_div = soup.find("div", class_="rich_media_content") or soup.find("article")
    if content_div:
        # 移除脚本和样式
        for tag in content_div.find_all(["script", "style"]):
            tag.decompose()
        body = md(str(content_div), strip=["img"]).strip()
    else:
        body = ""

    # 提取日期
    date_tag = soup.find("em", id="publish_time")
    date_str = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime("%Y-%m-%d")

    return {"title": title, "body": body, "date": date_str}


def extract_generic_article(url: str, settings: dict) -> dict:
    """
    通用文章提取（知识星球或其他来源的兜底方案）。
    """
    headers = {"User-Agent": settings["crawl"]["user_agent"]}
    timeout = settings["crawl"].get("timeout", 30)

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取标题
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else "未知标题"

    # 提取正文 — 尝试常见的内容容器
    content = None
    for selector in ["article", "main", ".content", ".post-content", "#content"]:
        content = soup.select_one(selector)
        if content:
            break

    if content:
        for tag in content.find_all(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        body = md(str(content), strip=["img"]).strip()
    else:
        # 最后兜底：提取 body 全部文本
        body_tag = soup.find("body")
        if body_tag:
            for tag in body_tag.find_all(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            body = md(str(body_tag), strip=["img"]).strip()
        else:
            body = ""

    date_str = datetime.now().strftime("%Y-%m-%d")

    return {"title": title, "body": body, "date": date_str}


def _is_wechat_link_line(line: str) -> bool:
    """判断是否为微信公众号历史文章链接行，如 [标题](url)"""
    stripped = line.strip()
    return bool(re.match(r'^\[.+\]\(https?://mp\.weixin\.qq\.com/.+\)$', stripped))


def _is_promo_line(line: str, promo_keywords: list) -> bool:
    """判断是否为推广内容行"""
    stripped = line.strip()
    if not stripped:
        return False
    # 含推广关键词
    if any(kw in stripped for kw in promo_keywords):
        return True
    # 微信历史文章链接
    if _is_wechat_link_line(stripped):
        return True
    return False


def clean_promotional_content(body: str) -> str:
    """
    清理文章末尾的推广内容：历史文章推荐列表、知识星球广告、二维码引导语等。
    策略：从文章末尾向前扫描，识别推广区块并截断。
    """
    lines = body.split("\n")

    # 推广内容的特征关键词（通常出现在文末）
    promo_keywords = [
        "欢迎加入星球",
        "加入星球",
        "扫下图二维码",
        "扫描二维码",
        "长按识别",
        "知识星球",
        "每天不到",
        "星球1满",
        "星球2",
        "日更",
        "进星球",
        "最终建立自己的魔镜体系",
        "魔镜体系",
        "如有技术问题",
    ]

    # 从末尾往前扫描，跳过空行，连续匹配推广行
    cut_index = len(lines)

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            # 空行：如果已在推广区块内则继续向前
            if cut_index < len(lines):
                continue
            else:
                continue
        if _is_promo_line(line, promo_keywords):
            cut_index = i
        else:
            # 遇到非推广的非空行，停止
            break

    # 截断并清理末尾空行
    cleaned = "\n".join(lines[:cut_index]).rstrip()
    return cleaned


def save_article(title: str, body: str, date: str, source: str, url: str, settings: dict) -> Path:
    """
    将提取的文章保存为标准格式 .md 文件到 /raw/ 目录。
    返回保存的文件路径。
    """
    root = get_data_root()
    raw_dir = root / settings["paths"]["raw_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：YYYYMMDD_标题简写.md
    date_prefix = date.replace("-", "")[:8]
    safe_title = sanitize_filename(title)
    filename = f"{date_prefix}_{safe_title}.md"
    file_path = raw_dir / filename

    # 避免重名
    counter = 1
    while file_path.exists():
        filename = f"{date_prefix}_{safe_title}_{counter}.md"
        file_path = raw_dir / filename
        counter += 1

    # 写入 frontmatter + 正文
    frontmatter = {
        "日期": date,
        "来源": source,
        "标题": title,
        "链接": url,
    }
    frontmatter_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip()

    content = f"---\n{frontmatter_str}\n---\n\n{body}\n"
    file_path.write_text(content, encoding="utf-8")

    return file_path


def crawl_article(url: str, source: str = "公众号", settings: Optional[dict] = None) -> dict:
    """
    主入口：爬取 URL 并保存为 .md 文件。
    source: "公众号" 或 "知识星球"
    返回 {"status": str, "file_path": str, "title": str, "message": str}
    """
    if settings is None:
        settings = load_settings()

    try:
        # 根据 URL 特征选择提取器
        if "mp.weixin.qq.com" in url:
            result = extract_wechat_article(url, settings)
        else:
            result = extract_generic_article(url, settings)

        title = result["title"]
        body = result["body"]
        date = result["date"]

        # 清理末尾推广内容
        if body:
            body = clean_promotional_content(body)

        if not body:
            return {
                "status": "error",
                "file_path": "",
                "title": title,
                "message": "未能提取到正文内容，可能需要手动复制或使用截图 OCR",
            }

        file_path = save_article(title, body, date, source, url, settings)

        return {
            "status": "ok",
            "file_path": str(file_path),
            "title": title,
            "message": f"文章已保存：{file_path.name}",
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "file_path": "",
            "title": "",
            "message": f"网络请求失败：{e}",
        }
    except Exception as e:
        return {
            "status": "error",
            "file_path": "",
            "title": "",
            "message": f"爬取失败：{e}",
        }
