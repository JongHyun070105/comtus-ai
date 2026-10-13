from contextlib import redirect_stderr
from io import StringIO
import unittest
from unittest.mock import patch

from comtus_ai.cli import main


class NavigationCollectCLITests(unittest.TestCase):
    def test_dry_run_routes_to_swift_capture_and_never_requests_input(self):
        with patch("comtus_ai.cli._run_swift", return_value=0) as run_swift:
            self.assertEqual(main(["navigate", "collect", "--dry-run"]), 0)
        run_swift.assert_called_once_with(["navigate", "collect", "--dry-run"])

    def test_live_input_requires_idle_only_before_swift_is_called(self):
        error = StringIO()
        with patch("comtus_ai.cli._run_swift") as run_swift, redirect_stderr(error):
            result = main(["navigate", "collect", "--allow-ui-input"])
        self.assertEqual(result, 2)
        self.assertIn("requires --idle-only", error.getvalue())
        run_swift.assert_not_called()

    def test_live_input_routes_with_both_explicit_flags(self):
        with patch("comtus_ai.cli._run_swift", return_value=0) as run_swift:
            self.assertEqual(main(["navigate", "collect", "--allow-ui-input", "--idle-only"]), 0)
        run_swift.assert_called_once_with(["navigate", "collect", "--allow-ui-input", "--idle-only"])


if __name__ == "__main__":
    unittest.main()
