#!/usr/bin/env python3
"""
build_temp_input.py - 从持仓 CSV / 结构化文本和上下文文本构建标准 temp_input.json

职责：
- 解析旧平台导出 CSV、标准 CSV、结构化文本
- 输出统一事实层，避免下游模型自行猜测口径
- 将 question / kb / profile / market / history 组装成标准输入
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.context_router import budget_text_blocks, compact_history

SKILL_DIR = Path(__file__).parent.parent
DEFAULT_OUTPUT = SKILL_DIR / "temp_input.json"

MONEY_MARKET_KEYWORDS = ("余额宝", "工资宝", "货币")
BROKER_POSITION_TYPES = {"场内持仓", "券商持仓"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse_decimal(value: str | float | int | None) -> Decimal | None:
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


def parse_loan_receivable_from_profile(profile_text: str) -> Decimal:
    patterns = [
        r"借给他人的借款[:：]\s*([0-9][0-9,，.]*)",
        r"借给他人的借款[^0-9]{0,10}([0-9][0-9,，.]*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, profile_text)
        if not m:
            continue
        value = parse_decimal(m.group(1))
        if value is not None:
            return value
    return Decimal("0")


def _extract_first_decimal(text: str) -> Decimal | None:
    m = re.search(r"([0-9][0-9,]*\.\d+|[0-9][0-9,]*)", text.replace("，", ","))
    return parse_decimal(m.group(1)) if m else None


def _extract_last_decimal(text: str) -> Decimal | None:
    matches = re.findall(r"([0-9][0-9,]*\.\d+|[0-9][0-9,]*)", text.replace("，", ","))
    return parse_decimal(matches[-1]) if matches else None


def _extract_pct(text: str) -> str | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)%", text)
    return f"{m.group(1)}%" if m else None


def _normalize_date(text: str) -> str:
    s = text.strip().replace("/", "-")
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", s):
        parts = s.split("-")
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return text.strip()


def _is_money_market(name: str, asset_type: str = "") -> bool:
    return asset_type == "货币基金" or any(keyword in name for keyword in MONEY_MARKET_KEYWORDS)


def _new_result() -> dict:
    return {
        "as_of_date": None,
        "positions": [],
        "pending_trades": [],
        "bank_cash_cny": 0.0,
        "money_market_funds_cny": 0.0,
        "broker_cash_cny": 0.0,
        "broker_positions_cny": 0.0,
        "fund_total_cny": 0.0,
        "warnings": [],
    }


def _append_position(result: dict, item: dict) -> None:
    result["positions"].append(item)
    asset_type = item.get("asset_type", "")
    amount = float(item.get("amount_cny", 0.0))
    if asset_type in {"货币基金", "场外基金"}:
        result["fund_total_cny"] += amount
    if asset_type == "货币基金":
        result["money_market_funds_cny"] += amount
    if asset_type in BROKER_POSITION_TYPES:
        result["broker_positions_cny"] += amount


def parse_legacy_export_csv(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    result = _new_result()
    holding_pattern = re.compile(r"^(?P<name>.*?)(?P<amount>\d[\d,]*\.\d{2}) 占比 (?P<ratio>\d+(?:\.\d+)?)%$")

    idx = 1
    while idx < len(rows):
        row = rows[idx]
        first = row[0].strip() if row else ""
        if not any(cell.strip() for cell in row):
            idx += 1
            break
        if first.startswith("明细"):
            idx += 1
            break
        match = holding_pattern.search(first)
        if match:
            name = match.group("name").strip()
            amount = parse_decimal(match.group("amount")) or Decimal("0")
            item = {
                "name": name,
                "amount_cny": float(amount),
                "asset_type": "货币基金" if _is_money_market(name) else "场外基金",
                "account_type": "基金平台",
                "weight_text": f'{match.group("ratio")}%',
            }
            if len(row) > 1 and row[1].strip():
                item["day_pnl"] = row[1].strip()
            if len(row) > 2 and row[2].strip():
                item["hold_return"] = row[2].strip()
                pct = _extract_pct(row[2])
                if pct:
                    item["hold_return_ratio"] = pct
            if len(row) > 3 and row[3].strip():
                item["cumulative_pnl"] = row[3].strip()
            _append_position(result, item)
        idx += 1

    pending_name = None
    pending_status = None
    while idx < len(rows):
        row = rows[idx]
        first = row[0].strip() if row else ""
        if not any(cell.strip() for cell in row):
            idx += 1
            continue
        if first.startswith("卖出 基金 | "):
            pending_name = first.replace("卖出 基金 | ", "", 1).strip()
            pending_status = None
        elif first.startswith("预计 "):
            status_text = first.replace("预计 ", "", 1).strip()
            mmdd = re.search(r"(\d{2})-(\d{2})", status_text)
            if mmdd:
                status_text = f"预计 2026-{mmdd.group(1)}-{mmdd.group(2)} 24 点前到账"
            else:
                status_text = f"预计 {status_text}"
            pending_status = status_text
        elif re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}.*", first) and pending_name:
            result["pending_trades"].append(
                {
                    "date": _normalize_date(first.split()[0]),
                    "direction": "卖出",
                    "asset": pending_name,
                    "status": pending_status or "",
                }
            )
            pending_name = None
            pending_status = None
        elif first.startswith("场内基金"):
            idx += 2
            if idx < len(rows):
                broker_row = rows[idx]
                broker_first = broker_row[0].strip() if broker_row else ""
                m = re.match(r"(?P<symbol>\S+)\s+(?P<amount>\d[\d,]*\.\d+)$", broker_first)
                if m:
                    item = {
                        "name": m.group("symbol"),
                        "symbol": m.group("symbol"),
                        "amount_cny": float(parse_decimal(m.group("amount")) or Decimal("0")),
                        "asset_type": "场内持仓",
                        "account_type": "券商",
                    }
                    if len(broker_row) > 1 and broker_row[1].strip():
                        item["hold_return"] = broker_row[1].strip()
                    if len(broker_row) > 2 and broker_row[2].strip():
                        qty_parts = broker_row[2].split()
                        if qty_parts:
                            item["quantity"] = qty_parts[0]
                    if len(broker_row) > 3 and broker_row[3].strip():
                        price_parts = broker_row[3].split()
                        if price_parts:
                            item["cost_price"] = price_parts[0]
                        if len(price_parts) > 1:
                            item["current_price"] = price_parts[1]
                    _append_position(result, item)
            break
        idx += 1

    return result


def parse_standard_csv(csv_path: Path) -> dict:
    result = _new_result()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            asset_type = (row.get("资产类型") or "").strip()
            name = (row.get("名称") or "").strip()
            amount = parse_decimal(row.get("持仓金额"))
            if not asset_type or not name or amount is None:
                continue
            if asset_type == "银行现金":
                result["bank_cash_cny"] += float(amount)
                continue
            if asset_type == "券商现金":
                result["broker_cash_cny"] += float(amount)
                continue
            item = {
                "name": name,
                "amount_cny": float(amount),
                "asset_type": asset_type,
                "account_type": (row.get("账户类型") or "").strip(),
            }
            if row.get("持有收益"):
                item["hold_return"] = row["持有收益"].strip()
            if row.get("持有收益率"):
                item["hold_return_ratio"] = row["持有收益率"].strip()
            if row.get("当日收益"):
                item["day_pnl"] = row["当日收益"].strip()
            if row.get("备注"):
                item["note"] = row["备注"].strip()
            is_low_risk = (row.get("是否低风险") or "").strip().lower() in {"是", "true", "1", "y", "yes"}
            if is_low_risk and asset_type == "场外基金":
                item["asset_type"] = "货币基金"
            _append_position(result, item)
    return result


def parse_structured_text(text_path: Path) -> dict:
    result = _new_result()
    current_section = None
    for raw_line in read_text(text_path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("日期：") or line.startswith("日期:"):
            result["as_of_date"] = _normalize_date(line.split("：", 1)[1] if "：" in line else line.split(":", 1)[1])
            continue
        if line.startswith("银行现金：") or line.startswith("银行现金:"):
            amount = _extract_first_decimal(line)
            result["bank_cash_cny"] = float(amount or Decimal("0"))
            continue
        if line.endswith("：") or line.endswith(":"):
            current_section = line.rstrip("：:")
            continue
        if not line.startswith("- "):
            continue

        body = line[2:].strip()
        parts = [part.strip() for part in body.split("|")]
        if current_section == "货币基金":
            amount = parse_decimal(parts[1]) if len(parts) > 1 else None
            item = {
                "name": parts[0],
                "amount_cny": float(amount or Decimal("0")),
                "asset_type": "货币基金",
                "account_type": "基金平台",
            }
            if len(parts) > 2:
                item["hold_return"] = parts[2]
            _append_position(result, item)
        elif current_section == "场外基金":
            amount = parse_decimal(parts[1]) if len(parts) > 1 else None
            item = {
                "name": parts[0],
                "amount_cny": float(amount or Decimal("0")),
                "asset_type": "场外基金",
                "account_type": "基金平台",
            }
            for extra in parts[2:]:
                if "收益率" in extra:
                    pct = _extract_pct(extra)
                    if pct:
                        item["hold_return_ratio"] = pct
                elif "持有收益" in extra:
                    item["hold_return"] = extra
            _append_position(result, item)
        elif current_section == "券商账户":
            if parts[0] == "可用现金":
                amount = parse_decimal(parts[1]) if len(parts) > 1 else None
                result["broker_cash_cny"] += float(amount or Decimal("0"))
            elif parts[0] == "持仓" and len(parts) >= 3:
                amount = _extract_last_decimal(parts[2]) or Decimal("0")
                item = {
                    "name": parts[1],
                    "symbol": parts[1],
                    "amount_cny": float(amount),
                    "asset_type": "场内持仓",
                    "account_type": "券商",
                }
                for extra in parts[2:]:
                    if "成本价" in extra:
                        value = _extract_first_decimal(extra)
                        if value is not None:
                            item["cost_price"] = str(value)
                    elif "现价" in extra:
                        value = _extract_first_decimal(extra)
                        if value is not None:
                            item["current_price"] = str(value)
                    elif "持仓数量" in extra:
                        value = _extract_first_decimal(extra)
                        if value is not None:
                            item["quantity"] = str(value)
                _append_position(result, item)
        elif current_section == "待到账交易":
            if len(parts) >= 5:
                result["pending_trades"].append(
                    {
                        "date": _normalize_date(parts[0]),
                        "direction": parts[1],
                        "asset": parts[2],
                        "amount": parts[3],
                        "status": parts[4],
                    }
                )
    return result


def parse_holdings_input(csv_path: Path | None, holdings_text_path: Path | None) -> dict:
    if csv_path and holdings_text_path:
        raise SystemExit("错误：--csv-path 与 --holdings-text-path 只能二选一。")
    if not csv_path and not holdings_text_path:
        raise SystemExit("错误：必须提供 --csv-path 或 --holdings-text-path。")
    if holdings_text_path:
        return parse_structured_text(holdings_text_path)

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    first_header = header[0].strip() if header else ""
    if first_header == "名称 / 金额":
        return parse_legacy_export_csv(csv_path)
    return parse_standard_csv(csv_path)


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
    web_results = read_text(Path(args.web_results_file)).strip() if args.web_results_file else ""
    requested_mode = (args.mode or "").strip()
    mode = requested_mode or "advice"
    history = read_text(Path(args.history_file)).strip() if args.history_file and mode == "advice" else ""

    payload = {
        "mode": mode,
        "question": question,
        "kb_results": kb_results,
        "financial_profile": financial_profile,
        "market_data": market_data,
        "web_results": web_results,
        "history": compact_history(history) if history else "",
    }
    payload.update(
        budget_text_blocks(
            {
                "question": payload["question"],
                "kb_results": payload["kb_results"],
                "financial_profile": payload["financial_profile"],
                "market_data": payload["market_data"],
                "web_results": payload["web_results"],
                "history": payload["history"],
            },
            mode=mode,
            soft_limit=5000 if mode == "advice" else 3200,
        )
    )

    if mode != "advice":
        return payload

    parsed = parse_holdings_input(Path(args.csv_path) if args.csv_path else None, Path(args.holdings_text_path) if args.holdings_text_path else None)

    profile_cash = parse_cash_from_profile(financial_profile)
    bank_cash_cny = parse_decimal(args.cash_cny) if args.cash_cny else profile_cash
    if parsed.get("bank_cash_cny"):
        bank_cash_cny = Decimal(str(parsed["bank_cash_cny"]))
    if bank_cash_cny is None:
        raise SystemExit("错误：无法从输入或财务档案中自动解析银行现金，请通过 --cash-cny 显式传入。")

    loan_receivable = parse_loan_receivable_from_profile(financial_profile)
    money_market_funds = Decimal(str(parsed.get("money_market_funds_cny", 0.0)))
    broker_cash = Decimal(str(parsed.get("broker_cash_cny", 0.0)))
    broker_positions = Decimal(str(parsed.get("broker_positions_cny", 0.0)))
    fund_total = Decimal(str(parsed.get("fund_total_cny", 0.0)))
    non_low_risk_funds = fund_total - money_market_funds
    low_risk_assets = bank_cash_cny + money_market_funds + broker_cash
    total_financial_assets = low_risk_assets + non_low_risk_funds + broker_positions + loan_receivable
    cash_cny = bank_cash_cny + broker_cash

    focus_keywords = [x.strip() for x in args.focus_keywords.split(",") if x.strip()]
    if not focus_keywords:
        focus_keywords = ["恒生科技", "Hang Seng Tech"]

    focus_position = pick_focus_position(parsed["positions"], focus_keywords)
    focus_asset_name = args.focus_asset_name or (focus_keywords[0] if focus_keywords else "焦点资产")
    as_of_date = parsed.get("as_of_date") or args.as_of_date

    raw_facts = {
        "as_of_date": as_of_date,
        "focus_asset_name": focus_asset_name,
        "bank_cash_cny": float(bank_cash_cny),
        "money_market_funds_cny": float(money_market_funds),
        "broker_cash_cny": float(broker_cash),
        "broker_positions_cny": float(broker_positions),
        "loan_receivable_cny": float(loan_receivable),
        "cash_cny": float(cash_cny),
        "low_risk_assets_cny": float(low_risk_assets),
        "fund_total_cny": float(fund_total),
        "total_financial_assets_cny": float(total_financial_assets),
        "positions": parsed["positions"],
        "pending_trades": parsed["pending_trades"],
    }

    if focus_position is not None:
        raw_facts["focus_position_snapshot"] = focus_position

    payload["raw_facts"] = raw_facts
    payload["policy_constraints"] = {
        "single_asset_limit_ratio": args.single_asset_limit_ratio,
        "focus_asset_keywords": focus_keywords,
        "stop_loss_rule_exists": args.stop_loss_rule_exists,
    }

    if args.stop_loss_rule_exists and args.stop_loss_ratio is not None:
        payload["policy_constraints"]["stop_loss_ratio"] = args.stop_loss_ratio

    if parsed.get("warnings"):
        payload["parse_warnings"] = parsed["warnings"]

    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build temp_input.json for jason-kb")
    parser.add_argument("--question-file", required=True, help="UTF-8 text file with the user question")
    parser.add_argument("--kb-file", required=True, help="UTF-8 text file with knowledge base results")
    parser.add_argument("--financial-profile-file", required=True, help="UTF-8 text file with financial profile")
    parser.add_argument("--market-data-file", required=True, help="UTF-8 text file with market data")
    parser.add_argument("--web-results-file", help="UTF-8 text file with supplemental web search results")
    parser.add_argument("--history-file", help="UTF-8 text file with advice history")
    parser.add_argument("--csv-path", help="Holding CSV path")
    parser.add_argument("--holdings-text-path", help="Structured holdings text path")
    parser.add_argument("--mode", choices=["research", "advice", "record", "history"], help="Force prompt assembly mode")
    parser.add_argument("--as-of-date", required=True, help="Facts as-of date, e.g. 2026-03-06")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output temp_input.json path")
    parser.add_argument("--cash-cny", help="Override bank cash amount if profile text cannot be parsed")
    parser.add_argument("--focus-asset-name", default="恒生科技", help="Human-readable focus asset name")
    parser.add_argument(
        "--focus-keywords",
        default="恒生科技,Hang Seng Tech",
        help="Comma-separated keywords used to find the focus asset in positions",
    )
    parser.add_argument("--single-asset-limit-ratio", type=float, default=0.15, help="Limit ratio on total financial assets")
    parser.add_argument("--stop-loss-rule-exists", action="store_true", help="Set if explicit stop-loss rule exists")
    parser.add_argument("--stop-loss-ratio", type=float, help="Optional stop-loss ratio if explicit rule exists")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"temp input written: {output_path}")


if __name__ == "__main__":
    main()
