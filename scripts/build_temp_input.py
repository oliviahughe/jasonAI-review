#!/usr/bin/env python3
"""
build_temp_input.py - 从原始持仓 CSV 和上下文文本构建标准 temp_input.json

职责：
- 解析基金/账户 CSV
- 自动生成 raw_facts / policy_constraints
- 将 question / kb / profile / market / history 组装成标准输入

设计原则：
- 上游结构化，不依赖模型“自己理解数字”
- 尽量从财务档案文本中推导现金口径
- 对无法可靠推导的内容允许显式参数覆盖
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
DEFAULT_OUTPUT = SKILL_DIR / "temp_input.json"

DEFAULT_EXCLUDED_FROM_FUND_TOTAL = {"余额宝", "账户余额"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse_decimal(value: str) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in {"", "-", "—"}:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def percent_to_ratio(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 100.0 if v > 1 else v
    s = str(value).strip().replace("%", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if v > 1 else v


def parse_cash_from_profile(profile_text: str) -> Decimal | None:
    patterns = [
        r"现金及活期[:：]\s*([0-9][0-9,，.]*)",
        r"现金及活期[^0-9]{0,10}([0-9][0-9,，.]*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, profile_text)
        if not m:
            continue
        value = parse_decimal(m.group(1))
        if value is not None:
            return value
    return None


def parse_csv(csv_path: Path, excluded_from_fund_total: set[str]) -> dict:
    rows = list(csv.reader(csv_path.open(encoding="utf-8-sig")))

    holdings_rows = []
    idx = 1
    while idx < len(rows):
        row = rows[idx]
        if not any(cell.strip() for cell in row):
            break
        holdings_rows.append(row)
        idx += 1

    transaction_rows = []
    for row in rows[idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        if row[0].strip().startswith("202"):
            transaction_rows.append(row)

    positions = []
    fund_total = Decimal("0")
    balances = []
    for row in holdings_rows:
        name = row[0].strip()
        amount = parse_decimal(row[1] if len(row) > 1 else "")
        if amount is None:
            continue

        item = {
            "name": name,
            "amount_cny": float(amount),
        }
        if len(row) > 2 and row[2].strip():
            item["weight_text"] = row[2].strip()
        if len(row) > 3 and row[3].strip():
            item["day_pnl"] = row[3].strip()
        if len(row) > 4 and row[4].strip():
            item["hold_pnl"] = row[4].strip()
        if len(row) > 5 and row[5].strip():
            item["hold_return"] = row[5].strip()
        if len(row) > 7 and row[7].strip():
            item["note"] = row[7].strip()

        if name in excluded_from_fund_total:
            balances.append(item)
        else:
            positions.append(item)
            fund_total += amount

    pending_trades = []
    for row in transaction_rows:
        pending_trades.append(
            {
                "date": row[0].strip(),
                "direction": row[1].strip() if len(row) > 1 else "",
                "asset": row[2].strip() if len(row) > 2 else "",
                "amount": row[3].strip() if len(row) > 3 else "",
                "status": row[4].strip() if len(row) > 4 else "",
            }
        )

    return {
        "positions": positions,
        "balances": balances,
        "fund_total_cny": float(fund_total),
        "pending_trades": pending_trades,
    }


def pick_focus_position(positions: list[dict], focus_keywords: list[str]) -> dict | None:
    for pos in positions:
        name = pos.get("name", "")
        if any(keyword and keyword in name for keyword in focus_keywords):
            return pos
    return None


def build_payload(args: argparse.Namespace) -> dict:
    question = read_text(Path(args.question_file)).strip()
    kb_results = read_text(Path(args.kb_file)).strip()
    financial_profile = read_text(Path(args.financial_profile_file)).strip()
    market_data = read_text(Path(args.market_data_file)).strip()
    history = read_text(Path(args.history_file)).strip() if args.history_file else ""

    parsed = parse_csv(Path(args.csv_path), excluded_from_fund_total=DEFAULT_EXCLUDED_FROM_FUND_TOTAL)

    cash_cny = parse_decimal(args.cash_cny) if args.cash_cny else parse_cash_from_profile(financial_profile)
    if cash_cny is None:
        raise SystemExit("错误：无法从财务档案中自动解析现金及活期，请通过 --cash-cny 显式传入。")

    focus_keywords = [x.strip() for x in args.focus_keywords.split(",") if x.strip()]
    if not focus_keywords:
        focus_keywords = ["恒生科技", "Hang Seng Tech"]

    focus_position = pick_focus_position(parsed["positions"], focus_keywords)
    focus_asset_name = args.focus_asset_name or (focus_keywords[0] if focus_keywords else "焦点资产")

    raw_facts = {
        "as_of_date": args.as_of_date,
        "focus_asset_name": focus_asset_name,
        "cash_cny": float(cash_cny),
        "fund_total_cny": parsed["fund_total_cny"],
        "positions": parsed["positions"],
        "pending_trades": parsed["pending_trades"],
    }

    if focus_position is not None:
        raw_facts["focus_position_snapshot"] = focus_position

    payload = {
        "question": question,
        "kb_results": kb_results,
        "financial_profile": financial_profile,
        "market_data": market_data,
        "history": history,
        "raw_facts": raw_facts,
        "policy_constraints": {
            "single_asset_limit_ratio": args.single_asset_limit_ratio,
            "focus_asset_keywords": focus_keywords,
            "stop_loss_rule_exists": args.stop_loss_rule_exists,
        },
    }

    if args.stop_loss_rule_exists and args.stop_loss_ratio is not None:
        payload["policy_constraints"]["stop_loss_ratio"] = args.stop_loss_ratio

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build temp_input.json for jason-kb")
    parser.add_argument("--question-file", required=True, help="UTF-8 text file with the user question")
    parser.add_argument("--kb-file", required=True, help="UTF-8 text file with knowledge base results")
    parser.add_argument("--financial-profile-file", required=True, help="UTF-8 text file with financial profile")
    parser.add_argument("--market-data-file", required=True, help="UTF-8 text file with market data")
    parser.add_argument("--history-file", help="UTF-8 text file with advice history")
    parser.add_argument("--csv-path", required=True, help="Holding CSV path")
    parser.add_argument("--as-of-date", required=True, help="Facts as-of date, e.g. 2026-03-06")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output temp_input.json path")
    parser.add_argument("--cash-cny", help="Override cash amount if profile text cannot be parsed")
    parser.add_argument("--focus-asset-name", default="恒生科技", help="Human-readable focus asset name")
    parser.add_argument(
        "--focus-keywords",
        default="恒生科技,Hang Seng Tech",
        help="Comma-separated keywords used to find the focus asset in positions",
    )
    parser.add_argument("--single-asset-limit-ratio", type=float, default=0.15, help="Limit ratio on total financial assets")
    parser.add_argument("--stop-loss-rule-exists", action="store_true", help="Set if explicit stop-loss rule exists")
    parser.add_argument("--stop-loss-ratio", type=float, help="Optional stop-loss ratio if explicit rule exists")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"temp input written: {output_path}")


if __name__ == "__main__":
    main()
