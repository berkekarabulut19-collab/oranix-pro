from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent


class MatchDetailUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "ui" / "styles.css").read_text(encoding="utf-8")

    def test_detail_modal_has_six_compact_navigation_tabs(self):
        labels = re.findall(r'id="btn_tab\d"[^>]*>.*?<b>(.*?)</b>', self.app_js)
        self.assertEqual(labels, ["Genel Bakış", "Handikap", "Model", "H2H", "Skorlar", "Güç"])

    def test_only_active_detail_section_is_visible(self):
        self.assertIn(".tab-content { display: none;", self.styles)
        self.assertIn(".tab-content.active { display: block;", self.styles)

    def test_probability_is_primary_and_missing_odds_stays_secondary(self):
        self.assertIn("match-detail-hero", self.app_js)
        self.assertIn("prediction-spotlight", self.app_js)
        self.assertIn("outcome-details", self.app_js)
        self.assertIn("model olasılığı", self.app_js)

    def test_model_scorecard_uses_real_performance_api(self):
        index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("🧪 Model Karnesi", index)
        self.assertIn("get_model_performance", self.app_js)
        self.assertIn("Yalnızca maç başlamadan kilitlenen tahminler ölçülür", index)
        self.assertNotIn("%87.4", index)


if __name__ == "__main__":
    unittest.main()
