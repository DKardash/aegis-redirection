"""Юнит-тесты на парсинг. Запуск: python -m unittest discover -s tests (из каталога manager)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import addresslists, mikrotik  # noqa: E402


class TestDurationParsing(unittest.TestCase):
    def test_compact(self):
        self.assertEqual(mikrotik._parse_duration_sec("9s"), 9)
        self.assertEqual(mikrotik._parse_duration_sec("1m37s"), 97)
        self.assertEqual(mikrotik._parse_duration_sec("1h2m3s"), 3723)
        self.assertEqual(mikrotik._parse_duration_sec("3w4d18h45m21s"), 2227521)

    def test_spaced(self):
        self.assertEqual(mikrotik._parse_duration_sec("1w 2d 3h 4m 5s"), 788645)

    def test_invalid(self):
        self.assertIsNone(mikrotik._parse_duration_sec(""))
        self.assertIsNone(mikrotik._parse_duration_sec(None))
        self.assertIsNone(mikrotik._parse_duration_sec("abc"))
        self.assertIsNone(mikrotik._parse_duration_sec("1z"))


class TestFriendlyErrors(unittest.TestCase):
    def test_auth(self):
        self.assertIn("логин", mikrotik._friendly("HTTP 401"))

    def test_refused(self):
        self.assertIn("недоступен", mikrotik._friendly("Connection refused"))

    def test_timeout(self):
        self.assertIn("таймаут", mikrotik._friendly("timed out"))

    def test_pass_through(self):
        self.assertEqual(mikrotik._friendly(""), "")
        self.assertEqual(mikrotik._friendly("strange"), "strange")


class TestModeRuleSelection(unittest.TestCase):
    def _r(self, **kw):
        base = {
            ".id": "*1",
            "action": "mark-routing",
            "chain": "prerouting",
            "new-routing-mark": "mark_table_VPN",
        }
        base.update(kw)
        return base

    def test_in_interface_is_mode(self):
        self.assertTrue(mikrotik._is_mode_rule(self._r(**{"in-interface": "!wg0"}), "mark_table_VPN"))

    def test_output_rule_is_mode(self):
        self.assertTrue(mikrotik._is_mode_rule(self._r(chain="output"), "mark_table_VPN"))

    def test_dns_rule_not_mode(self):
        self.assertFalse(mikrotik._is_mode_rule(self._r(comment="DISCORD"), "mark_table_VPN"))

    def test_other_table_not_match(self):
        self.assertFalse(
            mikrotik._is_mode_rule(self._r(new_routing_mark="mark_table_L2TP"), "mark_table_VPN")
        )

    def test_not_mark_routing(self):
        self.assertFalse(mikrotik._is_mode_rule(self._r(action="mark-connection"), "mark_table_VPN"))


class TestParseRsc(unittest.TestCase):
    SAMPLE = (
        "/ip firewall address-list\n"
        'add list=TELEGRAM_DNS comment="Telegram" address=telegram.org\n'
        'add list=TELEGRAM_DNS comment="Telegram" address=t.me\n'
        'add list=DISCORD_DNS comment="Discord" address=discord.com\n'
        'add list=PUBG_DNS comment="PUBG" address=pubg.com\n'
    )

    def test_group_count(self):
        g = addresslists.parse_rsc(self.SAMPLE)
        self.assertEqual(len(g), 3)

    def test_entries(self):
        g = addresslists.parse_rsc(self.SAMPLE)
        self.assertEqual(g[0]["title"], "TELEGRAM_DNS")
        self.assertEqual(g[0]["count"], 2)
        self.assertEqual(g[1]["entries"][0]["comment"], "Discord")
        self.assertEqual(g[1]["entries"][0]["address"], "discord.com")
        self.assertEqual(g[2]["count"], 1)

    def test_empty(self):
        self.assertEqual(addresslists.parse_rsc(""), [])


if __name__ == "__main__":
    unittest.main()
