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


if __name__ == "__main__":
    unittest.main()
