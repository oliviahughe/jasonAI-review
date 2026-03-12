#!/usr/bin/env python3
"""
call_deepseek.py - 调用 DeepSeek API（支持中转站）生成理财建议

读取上层目录的 temp_input.json，调用 DeepSeek Chat API，将建议输出到 stdout。
新增能力：
- 结构化事实优先
- 硬约束提示
- 输出冲突检测
- 自动重试
- 最终失败时拒绝返回错误建议
"""

import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
TEMP_INPUT = SKILL_DIR / "temp_input.json"
CONFIG_FILE = SKILL_DIR / "config.json"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
MAX_RETRIES = 2


def load_config() -> dict:
    """读取配置，环境变量优先于 config.json"""
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    api_key = os.environ.get("DEEPSEEK_API_KEY") or cfg.get("deepseek_api_key", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or cfg.get("deepseek_base_url", DEFAULT_BASE_URL)
    model = cfg.get("deepseek_model", DEFAULT_MODEL)

    if not api_key:
        raise SystemExit(
            "错误：未找到 DeepSeek API Key。\n"
            f"请在 {CONFIG_FILE} 中配置 deepseek_api_key，\n"
            "或设置环境变量 DEEPSEEK_API_KEY=sk-xxx\n\n"
            "如使用中转站，同时配置 deepseek_base_url 为中转站地址。"
        )

    return {"api_key": api_key, "base_url": base_url, "model": model}


def load_input() -> dict:
    if not TEMP_INPUT.exists():
        raise SystemExit(
            f"错误：未找到输入文件 {TEMP_INPUT}\n"
            "请先将上下文数据写入 temp_input.json。"
        )
    with open(TEMP_INPUT, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _to_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
        if m:
            return float(m.group(0))
    return default


def _percent_to_ratio(value):
    v = _to_float(value, default=0.0)
    if abs(v) > 1:
        return v / 100.0
    return v


def _ratio_to_pct_str(value):
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def _extract_percent_values(text: str) -> list[float]:
    text = text.replace("，", ",")
    # capture unsigned values; comparisons are done against abs(allowed) to handle negative hold_return
    return [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)%", text)]


def _extract_amount_values(text: str) -> list[float]:
    amounts = []
    text = text.replace("，", ",")
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*元", text):
        amounts.append(float(m.group(1).replace(",", "")))
    return amounts


def _close_to_any(value: float, allowed: list[float], tolerance: float) -> bool:
    return any(abs(value - x) <= tolerance for x in allowed)


def validate_contract(data: dict) -> dict:
    warnings = []
    raw = data.get("raw_facts")
    policy = data.get("policy_constraints")

    if raw is not None and not isinstance(raw, dict):
        warnings.append("raw_facts 应为对象，当前不是对象。")
    if policy is not None and not isinstance(policy, dict):
        warnings.append("policy_constraints 应为对象，当前不是对象。")

    if isinstance(raw, dict):
        if not raw.get("as_of_date"):
            warnings.append("raw_facts.as_of_date 缺失，结论可能存在时点歧义。")
        if raw.get("positions") is not None and not isinstance(raw.get("positions"), list):
            warnings.append("raw_facts.positions 应为数组。")
        if raw.get("pending_trades") is not None and not isinstance(raw.get("pending_trades"), list):
            warnings.append("raw_facts.pending_trades 应为数组。")
        if raw.get("focus_asset_name") is not None and not isinstance(raw.get("focus_asset_name"), str):
            warnings.append("raw_facts.focus_asset_name 应为字符串。")

    if isinstance(policy, dict):
        limit_ratio = _percent_to_ratio(policy.get("single_asset_limit_ratio"))
        if limit_ratio <= 0 or limit_ratio >= 1:
            warnings.append("policy_constraints.single_asset_limit_ratio 超出合理区间(0,1)。")
        if policy.get("stop_loss_rule_exists") is not None and not isinstance(policy.get("stop_loss_rule_exists"), bool):
            warnings.append("policy_constraints.stop_loss_rule_exists 应为布尔值。")

    return {"warnings": warnings}


def derive_metrics(data: dict) -> dict:
    raw = data.get("raw_facts") or {}
    policy = data.get("policy_constraints") or {}

    if not isinstance(raw, dict) or not isinstance(policy, dict):
        return {}

    has_numeric_facts = any(raw.get(k) is not None for k in ("cash_cny", "fund_total_cny"))
    has_positions = isinstance(raw.get("positions"), list) and len(raw.get("positions")) > 0
    has_policy = any(policy.get(k) is not None for k in ("single_asset_limit_ratio", "focus_asset_keywords"))
    if not (has_numeric_facts or has_positions or has_policy):
        return {}

    bank_cash = _to_float(raw.get("bank_cash_cny"))
    money_market_funds = _to_float(raw.get("money_market_funds_cny"))
    broker_cash = _to_float(raw.get("broker_cash_cny"))
    broker_positions = _to_float(raw.get("broker_positions_cny"))
    loan_receivable = _to_float(raw.get("loan_receivable_cny"))
    cash = _to_float(raw.get("cash_cny"), default=bank_cash + broker_cash)
    fund_total = _to_float(raw.get("fund_total_cny"))
    low_risk_assets = _to_float(raw.get("low_risk_assets_cny"), default=bank_cash + money_market_funds + broker_cash)
    total_financial_assets = _to_float(
        raw.get("total_financial_assets_cny"),
        default=low_risk_assets + max(fund_total - money_market_funds, 0.0) + broker_positions + loan_receivable,
    )
    liquid_assets = cash + fund_total

    limit_ratio = _percent_to_ratio(policy.get("single_asset_limit_ratio"))
    if limit_ratio <= 0:
        limit_ratio = 0.15
    limit_amount = total_financial_assets * limit_ratio

    positions = raw.get("positions") or []
    if not isinstance(positions, list):
        positions = []

    focus_keywords = policy.get("focus_asset_keywords") or ["恒生科技", "Hang Seng Tech"]
    if isinstance(focus_keywords, str):
        focus_keywords = [focus_keywords]
    if not isinstance(focus_keywords, list):
        focus_keywords = ["恒生科技", "Hang Seng Tech"]
    focus_asset_name = raw.get("focus_asset_name") or "恒生科技"

    focus_position = None
    for p in positions:
        if not isinstance(p, dict):
            continue
        name = " ".join(
            [
                str(p.get("name", "")),
                str(p.get("symbol", "")),
                str(p.get("index", "")),
                str(p.get("theme", "")),
            ]
        )
        if any(str(k).strip() and str(k) in name for k in focus_keywords):
            focus_position = p
            break

    focus_amount = _to_float((focus_position or {}).get("amount_cny"))
    focus_hold_return_ratio = _percent_to_ratio((focus_position or {}).get("hold_return"))
    focus_total_asset_ratio = (focus_amount / total_financial_assets) if total_financial_assets > 0 else None
    focus_fund_internal_ratio = (focus_amount / fund_total) if fund_total > 0 else None
    focus_need_reduce = bool(focus_position) and focus_amount > limit_amount
    cash_ratio = (cash / total_financial_assets) if total_financial_assets > 0 else None
    low_risk_ratio = (low_risk_assets / total_financial_assets) if total_financial_assets > 0 else None

    stop_loss_rule_exists = bool(policy.get("stop_loss_rule_exists", False))
    stop_loss_ratio = None
    if policy.get("stop_loss_ratio") is not None:
        stop_loss_ratio = _percent_to_ratio(policy.get("stop_loss_ratio"))

    pending_trades = raw.get("pending_trades") or []
    if not isinstance(pending_trades, list):
        pending_trades = []
    pending_sell_count = 0
    for t in pending_trades:
        if not isinstance(t, dict):
            continue
        direction = str(t.get("direction", "")).lower()
        if direction in {"sell", "卖出"}:
            pending_sell_count += 1

    allocation_target_ratios = [
        _percent_to_ratio(r) for r in (policy.get("allocation_target_ratios") or []) if r
    ]

    return {
        "basis": {
            "liquid_assets_formula": "cash_cny + fund_total_cny",
            "total_financial_assets_formula": "low_risk_assets_cny + non_low_risk_funds + broker_positions_cny + loan_receivable_cny",
            "single_asset_limit_formula": "single_asset_limit_ratio * total_financial_assets_cny",
            "single_asset_limit_ratio": limit_ratio,
            "focus_asset_keywords": focus_keywords,
            "single_asset_limit_applies_to": "总金融资产口径（total_financial_assets_cny）",
            "allocation_target_ratios": allocation_target_ratios,
        },
        "metrics": {
            "bank_cash_cny": round(bank_cash, 2),
            "money_market_funds_cny": round(money_market_funds, 2),
            "broker_cash_cny": round(broker_cash, 2),
            "broker_positions_cny": round(broker_positions, 2),
            "loan_receivable_cny": round(loan_receivable, 2),
            "cash_cny": round(cash, 2),
            "low_risk_assets_cny": round(low_risk_assets, 2),
            "fund_total_cny": round(fund_total, 2),
            "liquid_assets_cny": round(liquid_assets, 2),
            "total_financial_assets_cny": round(total_financial_assets, 2),
            "single_asset_limit_cny": round(limit_amount, 2),
            "focus_asset_name": focus_asset_name,
            "focus_amount_cny": round(focus_amount, 2),
            "focus_total_asset_ratio": round(focus_total_asset_ratio, 6) if focus_total_asset_ratio is not None else None,
            "focus_fund_internal_ratio": round(focus_fund_internal_ratio, 6) if focus_fund_internal_ratio is not None else None,
            "focus_hold_return_ratio": round(focus_hold_return_ratio, 6) if focus_hold_return_ratio is not None else None,
            "cash_ratio": round(cash_ratio, 6) if cash_ratio is not None else None,
            "low_risk_ratio": round(low_risk_ratio, 6) if low_risk_ratio is not None else None,
            "pending_sell_count": pending_sell_count,
        },
        "decision_flags": {
            "focus_need_reduce_by_limit_rule": focus_need_reduce,
            "focus_already_within_limit": bool(focus_position) and not focus_need_reduce,
            "stop_loss_rule_exists": stop_loss_rule_exists,
        },
        "policy_echo": {
            "stop_loss_rule_exists": stop_loss_rule_exists,
            "stop_loss_ratio": stop_loss_ratio,
        },
    }


def detect_output_conflicts(text: str, derived: dict) -> list:
    conflicts = []
    if not text or not derived:
        return conflicts

    flags = derived.get("decision_flags") or {}
    metrics = derived.get("metrics") or {}
    focus_name = metrics.get("focus_asset_name") or "焦点资产"
    total_ratio_pct = _ratio_to_pct_str(metrics.get("focus_total_asset_ratio"))
    limit_amount = metrics.get("single_asset_limit_cny")

    if flags.get("focus_already_within_limit"):
        # Only flag tokens that explicitly say "reduce because of 15% limit"
        # Do NOT flag descriptive mentions like "未超过15%" or "符合15%上限"
        limit_rule_tokens = [
            "降至15%以下",
            "降到15%以下",
            "降低到15%以下",
            "减仓至15%",
            "减仓到15%",
            "15%纪律线",
        ]
        if _contains_any(text, limit_rule_tokens):
            conflicts.append(
                f'硬冲突：{focus_name} 按总金融资产口径已在单资产上限内，但输出仍引用"15%上限/降到15%以下"作为动作理由。'
            )
            conflicts.append(
                f"参考值：{focus_name}={metrics.get('focus_amount_cny')} <= 单资产上限金额={limit_amount}；总金融资产占比={total_ratio_pct}。"
            )

    if not flags.get("stop_loss_rule_exists"):
        stop_loss_tokens = [
            "止损线",
            "止损纪律",
            "触及止损",
            "跌破止损",
            "回撤到15%",
            "亏损已触及预设",
            "纪律线",
        ]
        if _contains_any(text, stop_loss_tokens):
            conflicts.append("硬冲突：输出引用了止损线/纪律线，但结构化输入没有提供任何止损规则。")

    if "以程序计算为准" in text:
        bad_total_ratio_tokens = ["20.7%", "20.70%", "23.3%", "23.36%"]
        if _contains_any(text, bad_total_ratio_tokens):
            conflicts.append(
                f"硬冲突：输出声称程序计算出的焦点资产总金融资产占比明显不等于真实值 {total_ratio_pct}。"
            )

    focus_related_lines = []
    focus_markers = [focus_name, "焦点资产", "基金总资产", "总金融资产", "持仓", "占比", "仓位", "市值", "金额"]
    action_markers = ["卖出", "减仓", "买入", "定投", "分配", "计划", "建议", "转入", "投入",
                      # market context — percentages here are market moves, not position stats
                      "跌幅", "涨幅", "回撤", "波动", "GDP", "增速", "两会",
                      # forward projections — these are post-op estimates, not current facts
                      "操作后", "赎回后", "估算", "预计", "降至约", "将降",
                      # reasoning lines — justification context, not current state
                      "理由", "原因", "依据"]
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not _contains_any(line, focus_markers):
            continue
        if _contains_any(line, action_markers):
            continue
        focus_related_lines.append(line)

    cash_ratio = metrics.get("cash_ratio")
    fund_ratio = (1.0 - cash_ratio) if cash_ratio is not None else None  # complement: fund / liquid_assets

    allowed_pct_values = []
    for ratio in (
        metrics.get("focus_total_asset_ratio"),
        metrics.get("focus_fund_internal_ratio"),
        metrics.get("focus_hold_return_ratio"),
        cash_ratio,
        fund_ratio,
        derived.get("basis", {}).get("single_asset_limit_ratio"),
    ):
        if ratio is not None:
            v = ratio * 100
            allowed_pct_values.append(v)
            allowed_pct_values.append(abs(v))  # allow text showing unsigned loss magnitude
    # also allow extra policy ratios (e.g. allocation_target_ratios for medium/low risk goals)
    for r in (derived.get("basis", {}).get("allocation_target_ratios") or []):
        v = r * 100  # already converted to ratio in derive_metrics
        allowed_pct_values.append(v)
        allowed_pct_values.append(abs(v))

    allowed_amount_values = [
        x for x in (
            metrics.get("focus_amount_cny"),
            metrics.get("liquid_assets_cny"),
            metrics.get("fund_total_cny"),
            metrics.get("cash_cny"),
            metrics.get("single_asset_limit_cny"),
        ) if x is not None
    ]

    for line in focus_related_lines:
        for pct in _extract_percent_values(line):
            if not _close_to_any(pct, allowed_pct_values, tolerance=0.6):
                conflicts.append(
                    f"硬冲突：当前仓位描述中出现了未经结构化事实支持的百分比 {pct:.2f}%：{line}"
                )
                break
        for amount in _extract_amount_values(line):
            if not _close_to_any(amount, allowed_amount_values, tolerance=2.0):
                conflicts.append(
                    f"硬冲突：当前仓位描述中出现了未经结构化事实支持的金额 {amount:.2f} 元：{line}"
                )
                break

    return conflicts


def build_messages(data: dict, retry_conflicts: list[str] | None = None) -> list:
    mode = data.get("mode", "advice")
    question = data.get("question", "（未提供问题）")
    kb_results = data.get("kb_results", "（无知识库结果）")
    financial_profile = data.get("financial_profile", "（无财务档案）")
    market_data = data.get("market_data", "") or "（无市场数据）"
    web_results = data.get("web_results", "") or "（无补充检索结果）"
    history = data.get("history", "") or ""
    contract_report = validate_contract(data)
    derived = derive_metrics(data)

    if mode == "research":
        system_content = (
            "你是一个专业的个人财务助手，参考财经博主「Jason 不跪」的投资理念，"
            "整合知识库、近期市场信息和补充检索结果，回答用户的咨询问题。\n\n"
            "要求：\n"
            "- 优先回答用户真正关心的问题，不强行转成调仓建议\n"
            "- 明确区分 Jason 观点、市场事实和你自己的综合判断\n"
            "- 如果 Jason 知识库没有覆盖，明确说明，不要编造\n"
            "- 输出清晰直接，避免学术腔"
        )
        user_content = "\n".join(
            [
                f"## 用户问题\n{question}\n",
                f"## 知识库检索结果（Jason 的观点）\n{kb_results}\n",
                f"## 近30天市场动态\n{market_data}\n",
                f"## 补充检索结果\n{web_results}\n",
                f"## 用户财务背景（仅作轻量参考）\n{financial_profile}\n",
                "---\n请整合以上信息，回答用户问题。若涉及市场信息，请尽量带具体日期；若知识库中没有直接依据，明确说明不确定性。",
            ]
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    system_content = (
        "你是一个专业的个人理财顾问，参考财经博主「Jason 不跪」的投资理念，为用户提供个性化的理财建议。\n\n"
        "建议风格要求：\n"
        "- 数据驱动，有理有据\n"
        "- 直接给出可执行建议，不泛泛而谈\n"
        "- 明确引用 Jason 的观点作为逻辑依据，注明来自哪篇文章\n"
        "- 结合用户的具体资产状况和风险偏好\n"
        "- 结合近期市场动态，建议贴近当下市场\n"
        "- 不用'可以看出''通过分析'等学术腔\n"
        "- 判断果断，归因即时，±15% 即值得关注\n"
        "- 输出结构清晰，分点列出，控制在 600 字以内\n"
        "- 你可以自由组织表达，不需要固定模板；但不能无视已给出的程序计算结果与口径定义\n"
        "- 严禁编造未提供的止损线、仓位规则、目标收益率、日期或程序计算结果\n"
        "- 如果某条规则已经完成，不要重复把它当作当前动作理由\n"
        "- 可以建议减仓，但必须写清真实理由；不能偷换成一个不成立的规则"
    )

    user_parts = [
        f"## 用户问题\n{question}\n",
        f"## 知识库检索结果（Jason 的观点）\n{kb_results}\n",
        f"## 用户财务档案\n{financial_profile}\n",
        f"## 近30天市场动态\n{market_data}\n",
        f"## 补充检索结果\n{web_results}\n",
    ]

    if history:
        user_parts.append(f"## 历史建议记录（保持连贯性，避免自相矛盾）\n{history}\n")

    if contract_report.get("warnings"):
        user_parts.append(
            "## 参数契约告警（非致命）\n"
            + "\n".join([f"- {w}" for w in contract_report["warnings"]])
            + "\n"
        )

    if derived:
        metrics = derived.get("metrics") or {}
        flags = derived.get("decision_flags") or {}
        hard_facts = [
            f"- 焦点资产：{metrics.get('focus_asset_name') or '恒生科技'}",
            f"- 总金融资产 = {metrics.get('total_financial_assets_cny')} 元",
            f"- 低风险资金 = {metrics.get('low_risk_assets_cny')} 元，占比 {_ratio_to_pct_str(metrics.get('low_risk_ratio'))}",
            f"- 现金（银行现金+券商现金，不含货基）= {metrics.get('cash_cny')} 元",
            f"- 基金合计（含货基） = {metrics.get('fund_total_cny')} 元",
            f"- 焦点资产金额 = {metrics.get('focus_amount_cny')} 元",
            f"- 焦点资产总金融资产占比 = {_ratio_to_pct_str(metrics.get('focus_total_asset_ratio'))}",
            f"- 焦点资产基金内部占比 = {_ratio_to_pct_str(metrics.get('focus_fund_internal_ratio'))}",
            f"- 单资产上限金额 = {metrics.get('single_asset_limit_cny')} 元",
            f"- 单资产15%规则是否已满足 = {'是' if flags.get('focus_already_within_limit') else '否'}",
            f"- 是否存在显式止损规则 = {'是' if flags.get('stop_loss_rule_exists') else '否'}",
            '- 50%低风险配置是中期目标，不是单日必须精确打到的硬阈值；若建议调仓，只能说方向和节奏，不能强行推导“今天必须腾挪 X 万元”',
            '- 若要描述"当前事实"，只能使用上面这些金额和占比；不要自行改写成别的当前数字',
        ]
        user_parts.append("## 硬约束（不得冲突）\n" + "\n".join(hard_facts) + "\n")
        user_parts.append(
            "## 程序计算结果（优先口径）\n"
            f"{json.dumps(derived, ensure_ascii=False, indent=2)}\n"
        )

    if retry_conflicts:
        user_parts.append(
            "## 你上一版的硬冲突（必须完全修正）\n"
            + "\n".join([f"- {c}" for c in retry_conflicts])
            + "\n请重写整份建议，保留表达能力，但不得重复这些冲突。\n"
        )

    user_parts.append(
        "---\n"
        "请综合以上信息，给出具体、可执行的理财建议。要求：\n"
        "1. 明确引用 Jason 在哪篇文章中的观点（格式：'根据 Jason 在《XXX》中的观点...'）\n"
        "2. 引用近期市场信息时注明来源和日期\n"
        "3. 结合用户的具体财务数据给出针对性操作建议\n"
        "4. 如果知识库中没有相关内容，诚实告知，不要编造 Jason 的观点\n"
        "5. 如果 last30days 数据缺失，基于知识库和财务档案继续给建议\n"
        "6. 若程序计算结果与文本描述冲突，优先采用程序计算结果并说明口径\n"
        "7. 若焦点资产已低于15%上限，不能再把'降到15%以下'作为当前建议理由；如仍建议减仓，只能基于基金内部集中度、趋势、再平衡或用户风险承受度\n"
        "8. 若未提供止损规则，禁止自行编造'触及15%止损线/纪律线'\n"
        "9. 若低风险资金高于50%目标，只能表述为“偏高、可逐步消化”，不能在没有明确结构化依据时输出“约X万元闲置/必须马上转出X万元”"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def generate_with_guardrails(client, cfg: dict, data: dict) -> str:
    mode = data.get("mode", "advice")
    if mode != "advice":
        messages = build_messages(data)
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
        )
        return response.choices[0].message.content or ""

    retry_conflicts = None
    final_conflicts = []
    for _ in range(MAX_RETRIES + 1):
        messages = build_messages(data, retry_conflicts=retry_conflicts)
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
        )
        output = response.choices[0].message.content or ""
        final_conflicts = detect_output_conflicts(output, derive_metrics(data))
        if not final_conflicts:
            return output
        retry_conflicts = final_conflicts

    raise SystemExit(
        "错误：DeepSeek 输出未通过硬校验，已拦截，未向上游返回错误建议。\n"
        + "\n".join([f"- {c}" for c in final_conflicts])
    )


def main():
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("错误：缺少 openai 库。\n请运行：pip install openai")

    cfg = load_config()
    data = load_input()
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    output = generate_with_guardrails(client, cfg, data)
    print(output)


if __name__ == "__main__":
    main()
