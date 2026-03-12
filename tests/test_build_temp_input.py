import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "build_temp_input.py"
TMP_ROOT = REPO_ROOT / "tests" / "_tmp_build_temp_input"


def load_module():
    spec = importlib.util.spec_from_file_location("build_temp_input_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildTempInputTests(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if not TMP_ROOT.exists():
            return
        for path in sorted(TMP_ROOT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        TMP_ROOT.rmdir()

    def test_parse_legacy_export_csv_uses_embedded_amount_not_day_pnl(self):
        module = load_module()
        csv_path = TMP_ROOT / "holding.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "名称 / 金额,日收益,持有收益,累计收益",
                    '"天弘恒生科技 ETF 联接 (QDII) C基金 进阶理财 金选指数基金8,870.25 占比 32.82%",171.99,"-1,663.84 -15.79%","-2,609.35"',
                    '"余额宝灵活取用8,767.63 占比 32.44%",0.14,112.07,112.07',
                    '"长城工资宝货币 C基金 稳健理财2,487.64 占比 9.21%",0.08,0.6403,0.64',
                    "",
                    "明细 全部 全部,,,",
                    "卖出 基金 | 天弘中证电网设备主题指数 C 312.37 份,,,",
                    "预计 03-12 24 点前到账,,,",
                    "2026/3/11 13:33,,,",
                    "",
                    '场内基金,"总资产 (人民币) 仓位 9.4%\n5,002.20",,',
                    "市值,盈亏 / 比例,持仓 / 可用,成本 / 现价",
                    "300ETF 471.10,2.2047,100 100,4.689 4.711",
                ]
            ),
            encoding="utf-8",
        )

        parsed = module.parse_holdings_input(csv_path, None)

        self.assertAlmostEqual(20125.52, parsed["fund_total_cny"], places=2)
        self.assertAlmostEqual(8870.25, parsed["positions"][0]["amount_cny"], places=2)
        self.assertEqual("货币基金", parsed["positions"][1]["asset_type"])
        self.assertAlmostEqual(11255.27, parsed["money_market_funds_cny"], places=2)
        self.assertAlmostEqual(471.10, parsed["broker_positions_cny"], places=2)
        self.assertEqual("卖出", parsed["pending_trades"][0]["direction"])
        self.assertEqual("预计 2026-03-12 24 点前到账", parsed["pending_trades"][0]["status"])

    def test_parse_structured_text_extracts_broker_and_cash_fields(self):
        module = load_module()
        text_path = TMP_ROOT / "holding.txt"
        text_path.write_text(
            "\n".join(
                [
                    "日期：2026-03-11",
                    "银行现金：76531",
                    "货币基金：",
                    "- 余额宝 | 8767.63 | 持有收益 112.07",
                    "- 长城工资宝货币C | 2487.64 | 持有收益 0.64",
                    "",
                    "场外基金：",
                    "- 天弘恒生科技ETF联接(QDII)C | 8870.25 | 持有收益 -1663.84 | 持有收益率 -15.79%",
                    "- 招商中证白酒指数C | 2283.21 | 持有收益 -404.43",
                    "",
                    "券商账户：",
                    "- 可用现金 | 4531.10",
                    "- 持仓 | 510300 | 市值 471.10 | 成本价 4.689 | 现价 4.711 | 持仓数量 100",
                    "",
                    "待到账交易：",
                    "- 2026-03-11 | 卖出 | 天弘中证电网设备主题指数C | 312.37份 | 预计 2026-03-12 24点前到账",
                ]
            ),
            encoding="utf-8",
        )

        parsed = module.parse_holdings_input(None, text_path)

        self.assertEqual("2026-03-11", parsed["as_of_date"])
        self.assertAlmostEqual(76531.0, parsed["bank_cash_cny"], places=2)
        self.assertAlmostEqual(11255.27, parsed["money_market_funds_cny"], places=2)
        self.assertAlmostEqual(4531.10, parsed["broker_cash_cny"], places=2)
        self.assertAlmostEqual(471.10, parsed["broker_positions_cny"], places=2)
        self.assertAlmostEqual(22408.73, parsed["fund_total_cny"], places=2)
        self.assertEqual("510300", parsed["positions"][-1]["symbol"])

    def test_build_payload_emits_unified_fact_fields(self):
        module = load_module()
        question_file = TMP_ROOT / "question.txt"
        kb_file = TMP_ROOT / "kb.txt"
        profile_file = TMP_ROOT / "profile.txt"
        market_file = TMP_ROOT / "market.txt"
        history_file = TMP_ROOT / "history.txt"
        holdings_file = TMP_ROOT / "holding.txt"
        for path, text in (
            (question_file, "q"),
            (kb_file, "kb"),
            (profile_file, "现金及活期：76531\n借给他人的借款：34031"),
            (market_file, "market"),
            (history_file, "history"),
            (
                holdings_file,
                "\n".join(
                    [
                        "日期：2026-03-11",
                        "银行现金：76531",
                        "货币基金：",
                        "- 余额宝 | 8767.63",
                        "",
                        "场外基金：",
                        "- 天弘恒生科技ETF联接(QDII)C | 8870.25 | 持有收益率 -15.79%",
                        "",
                        "券商账户：",
                        "- 可用现金 | 4531.10",
                        "- 持仓 | 510300 | 市值 471.10",
                    ]
                ),
            )
        ):
            path.write_text(text, encoding="utf-8")

        args = module.parse_args(
            [
                "--question-file",
                str(question_file),
                "--kb-file",
                str(kb_file),
                "--financial-profile-file",
                str(profile_file),
                "--market-data-file",
                str(market_file),
                "--history-file",
                str(history_file),
                "--holdings-text-path",
                str(holdings_file),
                "--as-of-date",
                "2026-03-11",
            ]
        )
        payload = module.build_payload(args)

        raw = payload["raw_facts"]
        self.assertAlmostEqual(76531.0, raw["bank_cash_cny"], places=2)
        self.assertAlmostEqual(8767.63, raw["money_market_funds_cny"], places=2)
        self.assertAlmostEqual(4531.10, raw["broker_cash_cny"], places=2)
        self.assertAlmostEqual(471.10, raw["broker_positions_cny"], places=2)
        self.assertAlmostEqual(89829.73, raw["low_risk_assets_cny"], places=2)
        self.assertAlmostEqual(133202.08, raw["total_financial_assets_cny"], places=2)

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
                "--question-file",
                str(question_file),
                "--kb-file",
                str(kb_file),
                "--financial-profile-file",
                str(profile_file),
                "--market-data-file",
                str(market_file),
                "--web-results-file",
                str(web_file),
                "--mode",
                "research",
                "--as-of-date",
                "2026-03-12",
            ]
        )

        payload = module.build_payload(args)

        self.assertEqual("research", payload["mode"])
        self.assertEqual("web", payload["web_results"])
        self.assertEqual("", payload["history"])
        self.assertNotIn("raw_facts", payload)


if __name__ == "__main__":
    unittest.main()
