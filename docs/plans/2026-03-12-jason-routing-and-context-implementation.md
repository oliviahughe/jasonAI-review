# Jason Routing And Context Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add mode-based routing and elastic context budgeting so `jason-kb` can answer both general finance questions and portfolio advice without always forcing holdings history and hard validation.

**Architecture:** Introduce a small routing/context module that decides `research`, `advice`, `record`, or `history`, and produces compact context blocks before DeepSeek is called. Keep `call_deepseek.py` as the single model invocation entrypoint, but make its prompt assembly and validation mode-aware. Update docs and skill instructions so users and downstream agents know when heavy context is included and when it is intentionally omitted.

**Tech Stack:** Python 3, `unittest`, existing `openai` client, Markdown docs

---

### Task 1: Add mode routing and compact-context helpers

**Files:**
- Create: `scripts/context_router.py`
- Test: `tests/test_context_router.py`

**Step 1: Write the failing test**

```python
import unittest

from scripts.context_router import classify_mode, compact_history


class ContextRouterTests(unittest.TestCase):
    def test_classify_mode_distinguishes_research_and_advice(self):
        self.assertEqual("research", classify_mode("Jason 怎么看黄金后市？"))
        self.assertEqual("advice", classify_mode("我有 5 万闲钱现在怎么配？"))

    def test_compact_history_merges_repeated_guidance(self):
        history = "\n".join(
            [
                "2026-03-01：宽基优先、主题小仓、分批执行。",
                "2026-03-05：继续宽基优先、主题小仓、分批执行。",
                "2026-03-09：恒生科技先不追高，仍以分批为主。",
            ]
        )
        summary = compact_history(history, max_chars=120)
        self.assertIn("宽基优先", summary)
        self.assertIn("恒生科技", summary)
        self.assertLessEqual(len(summary), 120)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_context_router -v`

Expected: FAIL with `ModuleNotFoundError` or missing function errors because `scripts/context_router.py` does not exist yet.

**Step 3: Write minimal implementation**

```python
ROUTE_KEYWORDS = {
    "advice": ("怎么配", "买不买", "要不要加仓", "调仓", "分几笔", "仓位"),
    "record": ("更新", "加到", "卖了", "收入涨到", "仓位变了"),
    "history": ("之前给我的建议", "历史建议", "回顾建议"),
}


def classify_mode(question: str) -> str:
    q = (question or "").strip()
    for mode, keywords in ROUTE_KEYWORDS.items():
        if any(keyword in q for keyword in keywords):
            return mode
    return "research"


def compact_history(history: str, max_chars: int = 400) -> str:
    lines = [line.strip() for line in history.splitlines() if line.strip()]
    deduped = []
    for line in lines:
        if line not in deduped:
            deduped.append(line)
    text = "\n".join(deduped)
    return text[:max_chars]
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_context_router -v`

Expected: PASS for both routing and compact-history tests.

**Step 5: Commit**

```bash
git add tests/test_context_router.py scripts/context_router.py
git commit -m "feat: add routing and context helpers"
```

### Task 2: Teach temp input building to emit mode-aware payloads

**Files:**
- Modify: `scripts/build_temp_input.py`
- Test: `tests/test_build_temp_input.py`

**Step 1: Write the failing test**

Add a new case to `tests/test_build_temp_input.py`:

```python
def test_build_payload_for_research_mode_skips_holdings_and_history_by_default(self):
    module = load_module()
    question_file = TMP_ROOT / "question.txt"
    kb_file = TMP_ROOT / "kb.txt"
    profile_file = TMP_ROOT / "profile.txt"
    market_file = TMP_ROOT / "market.txt"
    web_file = TMP_ROOT / "web.txt"

    question_file.write_text("Jason 怎么看黄金？", encoding="utf-8")
    kb_file.write_text("kb", encoding="utf-8")
    profile_file.write_text("风险偏好: 稳健", encoding="utf-8")
    market_file.write_text("market", encoding="utf-8")
    web_file.write_text("web", encoding="utf-8")

    args = module.parse_args(
        [
            "--question-file", str(question_file),
            "--kb-file", str(kb_file),
            "--financial-profile-file", str(profile_file),
            "--market-data-file", str(market_file),
            "--web-results-file", str(web_file),
            "--mode", "research",
            "--as-of-date", "2026-03-12",
        ]
    )

    payload = module.build_payload(args)

    self.assertEqual("research", payload["mode"])
    self.assertEqual("web", payload["web_results"])
    self.assertEqual("", payload["history"])
    self.assertNotIn("raw_facts", payload)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_build_temp_input.BuildTempInputTests.test_build_payload_for_research_mode_skips_holdings_and_history_by_default -v`

Expected: FAIL because `--mode` / `--web-results-file` are not supported and `build_payload` always expects holdings-oriented input.

**Step 3: Write minimal implementation**

Update `scripts/build_temp_input.py` so it:

- accepts `--mode`
- accepts `--web-results-file`
- skips holdings parsing when mode is `research`
- keeps existing holdings path for `advice`
- emits `mode` and `web_results`
- only injects `history` when mode is `advice`

Minimal shape:

```python
payload = {
    "mode": args.mode,
    "question": question,
    "kb_results": kb_results,
    "financial_profile": financial_profile_excerpt,
    "market_data": market_data,
    "web_results": web_results,
    "history": compacted_history if args.mode == "advice" else "",
}

if args.mode == "advice":
    payload["raw_facts"] = raw_facts
    payload["policy_constraints"] = policy_constraints
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_build_temp_input -v`

Expected: PASS for existing unified facts tests plus the new research-mode payload test.

**Step 5: Commit**

```bash
git add tests/test_build_temp_input.py scripts/build_temp_input.py
git commit -m "feat: add mode-aware temp input builder"
```

### Task 3: Make DeepSeek prompts and validation mode-aware

**Files:**
- Modify: `scripts/call_deepseek.py`
- Create: `tests/test_call_deepseek_modes.py`
- Modify: `tests/test_call_deepseek_metrics.py`

**Step 1: Write the failing test**

Create `tests/test_call_deepseek_modes.py`:

```python
import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "call_deepseek.py"


def load_module():
    spec = importlib.util.spec_from_file_location("call_deepseek_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CallDeepSeekModesTests(unittest.TestCase):
    def test_build_messages_for_research_omits_history_and_hard_constraints(self):
        module = load_module()
        messages = module.build_messages(
            {
                "mode": "research",
                "question": "Jason 怎么看黄金？",
                "kb_results": "kb",
                "market_data": "market",
                "web_results": "web",
                "financial_profile": "风险偏好: 稳健",
                "history": "不应出现",
            }
        )
        text = messages[1]["content"]
        self.assertIn("web", text)
        self.assertNotIn("历史建议记录", text)
        self.assertNotIn("硬约束", text)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_call_deepseek_modes -v`

Expected: FAIL because `build_messages()` currently ignores `mode`, has no `web_results`, and always assumes advice-style prompt assembly.

**Step 3: Write minimal implementation**

Refactor `scripts/call_deepseek.py` to:

- read `mode = data.get("mode", "advice")`
- build separate prompt sections for `research` and `advice`
- include `web_results` in both `research` and `advice`
- only call `derive_metrics()` and `detect_output_conflicts()` in `advice`
- return model output directly in `research`

Minimal branching:

```python
mode = data.get("mode", "advice")
if mode == "research":
    messages = build_research_messages(data)
    return client.chat.completions.create(...).choices[0].message.content or ""

messages = build_advice_messages(data, retry_conflicts=retry_conflicts)
...
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_call_deepseek_metrics tests.test_call_deepseek_modes -v`

Expected: PASS for existing metrics coverage and the new research-mode prompt behavior test.

**Step 5: Commit**

```bash
git add tests/test_call_deepseek_metrics.py tests/test_call_deepseek_modes.py scripts/call_deepseek.py
git commit -m "feat: add mode-aware deepseek prompts"
```

### Task 4: Add elastic budgeting for history, profile, and retrieved context

**Files:**
- Modify: `scripts/context_router.py`
- Modify: `scripts/build_temp_input.py`
- Create: `tests/test_context_budgeting.py`

**Step 1: Write the failing test**

Create `tests/test_context_budgeting.py`:

```python
import unittest

from scripts.context_router import budget_text_blocks


class ContextBudgetingTests(unittest.TestCase):
    def test_budget_text_blocks_prioritizes_question_and_recent_strategy(self):
        blocks = {
            "question": "我想知道现在黄金和 A 股怎么平衡配置",
            "kb_results": "K" * 800,
            "market_data": "M" * 800,
            "web_results": "W" * 800,
            "history": "宽基优先，主题小仓，分批执行。\n恒生科技暂不追高。",
        }
        result = budget_text_blocks(blocks, mode="advice", soft_limit=900)
        self.assertIn("宽基优先", result["history"])
        self.assertLessEqual(sum(len(v) for v in result.values()), 900)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_context_budgeting -v`

Expected: FAIL because no budgeting helper exists yet.

**Step 3: Write minimal implementation**

In `scripts/context_router.py`, add a helper that:

- always keeps `question`
- aggressively trims `kb_results`, `market_data`, and `web_results`
- keeps `history` short but non-empty in `advice`
- uses different soft limits for `research` and `advice`

Minimal shape:

```python
def budget_text_blocks(blocks: dict[str, str], mode: str, soft_limit: int) -> dict[str, str]:
    priority = ["question", "history", "kb_results", "market_data", "web_results"]
    caps = {"research": 3000, "advice": 5000}
    ...
```

Wire this into `scripts/build_temp_input.py` before serializing the payload.

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_context_router tests.test_context_budgeting tests.test_build_temp_input -v`

Expected: PASS, and research/advice payloads now contain trimmed context instead of raw full text.

**Step 5: Commit**

```bash
git add tests/test_context_budgeting.py tests/test_context_router.py scripts/context_router.py scripts/build_temp_input.py
git commit -m "feat: add elastic context budgeting"
```

### Task 5: Update skill and user-facing docs

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Create: `docs/remote-mcp-quickstart-for-friends.md`

**Step 1: Write the failing doc checklist**

Create a short checklist in your working notes and verify all three gaps exist before editing:

- `README.md` does not yet describe `research / advice / record / history`
- `SKILL.md` still frames the DeepSeek path as a single advice-centric flow
- there is no friend-facing remote MCP quickstart doc

**Step 2: Run the check**

Run: `Select-String -Path README.md,SKILL.md -Pattern "research|advice|record|history|quickstart-for-friends"`

Expected: no complete coverage of the new modes, and no existing friend quickstart file.

**Step 3: Write minimal documentation changes**

Update docs to explain:

- when holdings/history are intentionally omitted
- that advice history is compacted, not endlessly appended
- how a beginner can connect to the remote MCP endpoint from Claude and Codex

Suggested starter text for `docs/remote-mcp-quickstart-for-friends.md`:

```md
# 远端 MCP 快速上手

适合对象：没有本地 `jason-kb` skill、没有配过 MCP 的朋友。

你只需要准备：
- 服务地址
- Bearer Token
- 一个支持 MCP 的客户端
```

**Step 4: Verify docs**

Run: `Select-String -Path README.md,SKILL.md,'docs/remote-mcp-quickstart-for-friends.md' -Pattern "research|advice|record|history|历史建议|Bearer|Unauthorized|Invalid Host"`

Expected: matches in all target docs for the new modes and the troubleshooting keywords.

**Step 5: Commit**

```bash
git add SKILL.md README.md docs/remote-mcp-quickstart-for-friends.md
git commit -m "docs: explain routing modes and remote mcp setup"
```

### Task 6: Full verification before merge

**Files:**
- Verify only; no required edits unless a failure is found

**Step 1: Run unit tests**

Run: `python -m unittest tests.test_context_router tests.test_context_budgeting tests.test_build_temp_input tests.test_call_deepseek_metrics tests.test_call_deepseek_modes -v`

Expected: all tests PASS.

**Step 2: Run a manual research-mode smoke test**

Run:

```bash
python scripts/build_temp_input.py `
  --question-file tests/_fixtures/research_question.txt `
  --kb-file tests/_fixtures/kb.txt `
  --financial-profile-file tests/_fixtures/profile.txt `
  --market-data-file tests/_fixtures/market.txt `
  --web-results-file tests/_fixtures/web.txt `
  --mode research `
  --as-of-date 2026-03-12
```

Expected: generated `temp_input.json` contains `mode=research`, `web_results`, and no holdings-only facts.

**Step 3: Run a manual advice-mode smoke test**

Run:

```bash
python scripts/build_temp_input.py `
  --question-file tests/_fixtures/advice_question.txt `
  --kb-file tests/_fixtures/kb.txt `
  --financial-profile-file tests/_fixtures/profile.txt `
  --market-data-file tests/_fixtures/market.txt `
  --web-results-file tests/_fixtures/web.txt `
  --history-file tests/_fixtures/history.txt `
  --holdings-text-path docs/holdings-template.txt `
  --mode advice `
  --as-of-date 2026-03-12
```

Expected: generated `temp_input.json` contains `mode=advice`, compacted `history`, and structured `raw_facts`.

**Step 4: Inspect git state**

Run: `git status --short`

Expected: only intended files are modified or staged.

**Step 5: Commit verification cleanup if needed**

```bash
git add <only intended files>
git commit -m "test: verify routing and context budgeting flow"
```
