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
        self.assertEqual(blocks["question"], result["question"])
        self.assertLessEqual(sum(len(value) for value in result.values()), 900)


if __name__ == "__main__":
    unittest.main()
