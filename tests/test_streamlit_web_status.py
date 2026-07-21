from pathlib import Path
import unittest

class StreamlitWebStatusTests(unittest.TestCase):
    def test_streamlit_contains_web_source_status_sections(self):
        text = Path("app_streamlit.py").read_text(encoding="utf-8")
        self.assertIn("Webcontext-modus", text)
        self.assertIn("Gebruik overige externe webbronnen", text)
        self.assertIn("Officiële webbronnen", text)
        self.assertIn("Externe webbronnen", text)
        self.assertIn("Bronstatus", text)
        self.assertIn("Alleen bij ontbrekende lokale context", text)
        self.assertIn("Altijd proberen als extra context", text)
        self.assertIn("Forceer webcontext", text)

if __name__ == "__main__":
    unittest.main()
