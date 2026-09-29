import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import addresslists, healthcheck, profiles, xray

SERVER = {"id": 1, "protocol": "vless", "address": "example.com", "port": 443,
          "uuid": "12345678-1234-1234-1234-123456789abc", "security": "none", "network": "tcp"}
PROFILE = {"id": 1, "server_id": 1, "backup_server_id": 2, "enabled": True, "tproxy_port": 12346}
OK = (True, 50, "")
FAIL = (False, None, "timeout")


class RoutingRevisionTests(unittest.TestCase):
    def test_failover_and_recovery_hysteresis(self):
        state = profiles.choose_route(PROFILE, {}, {1: FAIL, 2: OK})
        self.assertEqual(state["active_server_id"], 1)
        state = profiles.choose_route(PROFILE, state, {1: FAIL, 2: OK})
        self.assertEqual(state["active_server_id"], 2)
        state = profiles.choose_route(PROFILE, state, {1: OK, 2: OK})
        self.assertEqual(state["active_server_id"], 2)
        state = profiles.choose_route(PROFILE, state, {1: OK, 2: OK})
        self.assertEqual(state["active_server_id"], 1)

    def test_all_down_blocks_then_recovers(self):
        state = {}
        for _ in range(2):
            state = profiles.choose_route(PROFILE, state, {1: FAIL, 2: FAIL})
        self.assertEqual(state["active_server_id"], 0)
        self.assertEqual(profiles.active_id(PROFILE, {"1": state}), 0)
        state = profiles.choose_route(PROFILE, state, {1: FAIL, 2: OK})
        self.assertEqual(state["active_server_id"], 2)

    def test_interfaces_are_independent(self):
        a = profiles.choose_route(PROFILE, {"failures": {"1": 1}}, {1: FAIL, 2: OK, 3: OK})
        b = profiles.choose_route({**PROFILE, "id": 2, "server_id": 3}, {}, {1: FAIL, 2: OK, 3: OK})
        self.assertEqual((a["active_server_id"], b["active_server_id"]), (2, 3))

    def test_overlapping_tick_is_skipped(self):
        with profiles._TICK_LOCK, patch.object(profiles, "_failover_tick") as tick:
            self.assertIn("уже", profiles.failover_tick())
            tick.assert_not_called()

    def test_no_global_proxy_and_blocked_profile(self):
        config = xray.build_multi_config(None, [dict(PROFILE, server=SERVER),
            {"id": 2, "tproxy_port": 12347, "server": None}])
        self.assertFalse(any(i["protocol"] in ("socks", "http") for i in config["inbounds"]))
        self.assertEqual(config["routing"]["rules"][-1]["outboundTag"], "block")
        self.assertEqual(next(o for o in config["outbounds"] if o["tag"] == "profile-2")["protocol"], "blackhole")

    def test_config_tests_use_unique_files(self):
        paths = []
        def run(command, **kwargs):
            path = Path(command[-1])
            paths.append(str(path))
            self.assertEqual(json.loads(path.read_text())["test"], True)
            return SimpleNamespace(returncode=0)
        with patch.object(xray.subprocess, "run", side_effect=run):
            with ThreadPoolExecutor(max_workers=3) as pool:
                self.assertTrue(all(ok for ok, _ in pool.map(xray.test_config, [{"test": True}] * 9)))
        self.assertEqual(len(set(paths)), 9)
        self.assertTrue(all(not Path(p).exists() for p in paths))

    def test_probe_retries_and_cleans_up(self):
        proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda **kw: None)
        runs = [SimpleNamespace(returncode=28, stdout="000 10", stderr="timeout"),
                SimpleNamespace(returncode=0, stdout="204 0.1", stderr="")]
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(healthcheck.subprocess, "Popen", return_value=proc) as start, \
             patch.object(healthcheck.subprocess, "run", side_effect=runs) as run, \
             patch.object(healthcheck.socket, "create_connection", return_value=Connection()), \
             patch.object(healthcheck.time, "sleep"):
            self.assertEqual(healthcheck.check_server(SERVER, False), (True, 100, ""))
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("127.0.0.1:1080", str(run.call_args_list))
        self.assertFalse(Path(start.call_args.args[0][-1]).exists())

    def test_only_three_lists_and_disabled_preserved(self):
        groups = addresslists.parse_rsc('add list=TELEGRAM_DNS address=telegram.example disabled=yes\nadd list=DISCORD_DNS address=discord.example\nadd list=PUBG_DNS address=pubg.example')
        self.assertEqual([g["title"] for g in groups], list(addresslists.ALLOWED_LISTS))
        again = addresslists.parse_rsc(addresslists.build_ip_rsc(groups))
        self.assertEqual(groups, again)
        self.assertTrue(any(e["disabled"] for g in groups for e in g["entries"]))
        with self.assertRaises(ValueError):
            addresslists.parse_rsc("add list=bad/list address=example.com")
        self.assertEqual(addresslists.parse_rsc('add list=VPN address=legacy.example')[0]['title'], 'VPN')

    def test_property_order_and_wrapping(self):
        source = 'add address=example.com disabled=yes ' + chr(92) + '\n    comment="test label" list=TELEGRAM_DNS'
        groups = addresslists.parse_rsc(source)
        self.assertEqual(groups[0]["entries"][0]["comment"], "test label")
        self.assertTrue(groups[0]["entries"][0]["disabled"])


if __name__ == "__main__":
    unittest.main()
