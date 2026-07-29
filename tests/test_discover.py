from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aether-hub"))

import discover  # noqa: E402


class DiscoverSpendTests(unittest.TestCase):
    def test_reports_spend_against_configured_budget(self):
        with mock.patch.object(discover, "_http", return_value=(200, {"spend": 1.5, "max_budget": 20.0})), \
                mock.patch.object(discover, "_litellm_budget_duration", return_value="30d"):
            result = discover.discover_spend("http://litellm:4000", "sk-test")
        self.assertEqual(result, {"ok": True, "spend": 1.5, "max_budget": 20.0, "budget_duration": "30d"})

    def test_defaults_spend_to_zero_when_none(self):
        with mock.patch.object(discover, "_http", return_value=(200, {"spend": None, "max_budget": 20.0})), \
                mock.patch.object(discover, "_litellm_budget_duration", return_value=None):
            result = discover.discover_spend("http://litellm:4000", "sk-test")
        self.assertEqual(result["spend"], 0.0)

    def test_unreachable_proxy_reports_not_ok(self):
        with mock.patch.object(discover, "_http", return_value=(None, {"error": "connection refused"})):
            result = discover.discover_spend("http://litellm:4000", "sk-test")
        self.assertEqual(result, {"ok": False})


if __name__ == "__main__":
    unittest.main()
