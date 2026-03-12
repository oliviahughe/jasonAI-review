#!/usr/bin/env python3

"""Routing and compact-context helpers for Jason AI prompts."""

from __future__ import annotations


MODE_KEYWORDS = {
    "history": ("之前给我的建议", "历史建议", "回顾建议"),
    "record": ("更新", "加到", "卖了", "收入涨到", "仓位变了"),
    "advice": ("怎么配", "买不买", "要不要加仓", "调仓", "分几笔", "仓位"),
}


def classify_mode(question: str) -> str:
    text = (question or "").strip()
    for mode, keywords in MODE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return mode
    return "research"


def compact_history(history: str, max_chars: int = 400) -> str:
    if not history:
        return ""

    lines = [line.strip() for line in history.splitlines() if line.strip()]
    merged: list[str] = []

    for line in lines:
        normalized = line.replace("继续", "").replace("仍", "")
        if any(
            normalized == existing.replace("继续", "").replace("仍", "")
            or normalized in existing
            or existing.replace("继续", "").replace("仍", "") in normalized
            for existing in merged
        ):
            continue
        merged.append(line)

    summary = "\n".join(merged)
    return summary[:max_chars]
