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


if __name__ == "__main__":
    unittest.main()
