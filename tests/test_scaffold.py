import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ScaffoldSmokeTest(unittest.TestCase):
    def test_package_and_phase_modules_import(self):
        import bugzilla_qa
        import bugzilla_qa.app
        import bugzilla_qa.benchmark
        import bugzilla_qa.data
        import bugzilla_qa.evaluation
        import bugzilla_qa.methods
        import bugzilla_qa.retrieval

        self.assertEqual(bugzilla_qa.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
