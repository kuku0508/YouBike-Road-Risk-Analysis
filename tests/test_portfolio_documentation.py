import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CASES = ROOT / "notes" / "phase8_6b-human-case-studies.md"
PIPELINE = ROOT / "figures" / "project_pipeline.svg"


class PortfolioDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")
        cls.cases = CASES.read_text(encoding="utf-8")

    def test_01_required_readme_story_sections_exist(self):
        for heading in (
            "## 研究問題", "## 核心成果", "## 資料", "## 資料處理與分析流程",
            "## 核心分析方法", "## 四個人工檢視案例", "## 研究限制",
            "## 可重現性與驗證", "## 技術棧", "## Quick start", "## 專案結構", "## 結論",
        ):
            self.assertIn(heading, self.readme)

    def test_02_key_metrics_and_metric_boundaries_are_present(self):
        for value in (
            "109,713,899", "92,699,907", "2,782", "1,125,519", "1,100,919",
            "106,049", "46,586", "39,711", "85.2423%", "4,654,909", "53,032", "53,025",
        ):
            self.assertIn(value, self.readme)
        self.assertIn("PDO component = unobserved", self.readme)
        self.assertIn("CBI = SRI + SSI", self.readme)
        self.assertIn("CBI 不包含自行車 exposure", self.readme)

    def test_03_exactly_four_human_case_studies_are_recorded(self):
        headings = re.findall(r"^## 案例 ([A-Z])｜", self.cases, flags=re.MULTILINE)
        self.assertEqual(headings, ["A", "B", "C", "D"])
        self.assertEqual(self.cases.count("reference_microsegment_ids = not formally recorded"), 5)
        self.assertNotIn("## 案例 E｜", self.cases)

    def test_04_case_c_does_not_invent_exact_cbi(self):
        case_c = self.cases.split("## 案例 C｜", 1)[1].split("## 案例 D｜", 1)[0]
        self.assertIn("沒有記錄可稽核的 exact CBI", case_c)
        self.assertNotRegex(case_c, r"CBI\s*(?:約|=|：)\s*`?\d")

    def test_05_case_structure_is_consistent(self):
        starts = {label: self.cases.index(f"## 案例 {label}｜") for label in ("A", "B", "C", "D")}
        ends = {"A": starts["B"], "B": starts["C"], "C": starts["D"], "D": self.cases.index("## 跨案例整理")}
        for label in ("A", "B", "C", "D"):
            section = self.cases[starts[label]:ends[label]]
            for heading in ("### 資料證據", "### 道路現況觀察", "### 可能風險機制", "### 改善方向", "### 研究限制"):
                self.assertIn(heading, section)

    def test_06_no_forbidden_portfolio_claims_or_streetview_images(self):
        combined = self.readme + self.cases
        self.assertNotIn("Modified EPDO", combined)
        self.assertIn("不代表中位數是統計最佳門檻", self.readme)
        self.assertIn("不能寫成「沒有人行道造成 CBI 較高」", self.cases)
        self.assertNotIn("找出了臺北最危險道路", combined)
        for suffix in (".jpg", ".jpeg", ".webp"):
            self.assertNotIn(suffix, combined.lower())

    def test_07_all_local_readme_links_resolve(self):
        targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", self.readme)
        local_targets = [target.split("#", 1)[0] for target in targets if "://" not in target]
        self.assertTrue(local_targets)
        missing = [target for target in local_targets if target and not (ROOT / target).exists()]
        self.assertEqual(missing, [])

    def test_08_pipeline_svg_has_accessible_text_and_locked_steps(self):
        svg = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        for phrase in ("原始 YouBike 旅次", "BRouter 路徑重建", "事故實體重建", "四個人工道路案例"):
            self.assertIn(phrase, svg)


if __name__ == "__main__":
    unittest.main()
