import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db as database
from app import crud
from app.config import settings
from app import subscriptions
from app.protocols import parse_vless_url


class SubscriptionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.connection = getattr(database._local, "conn", None)
        if self.connection is not None:
            self.connection.close()
            del database._local.conn
        self.settings_patches = [
            patch.object(settings, "database_path", self.root / "test.db"),
            patch.object(settings, "backups_dir", self.root / "backups"),
            patch.object(settings, "generated_dir", self.root / "generated"),
        ]
        for p in self.settings_patches:
            p.start()
        database.init_db()

    def tearDown(self):
        conn = getattr(database._local, "conn", None)
        if conn is not None:
            conn.close()
            del database._local.conn
        for p in reversed(self.settings_patches):
            p.stop()
        self.temp.cleanup()

    def test_subscription_url_is_private_and_removal_keeps_servers_independent(self):
        secret_url = "https://feed.example/sub?token=private-value"
        subscription_id = subscriptions.remember(secret_url)
        rows = subscriptions.list_subscriptions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["host"], "feed.example")
        self.assertNotIn(secret_url, str(rows))
        self.assertNotIn("private-value", str(rows))
        self.assertEqual(subscriptions.due_ids(), [subscription_id])

        subscriptions.mark_imported(subscription_id, 2)
        self.assertEqual(subscriptions.due_ids(), [])
        self.assertTrue(subscriptions.set_enabled(subscription_id, False))
        self.assertEqual(subscriptions.due_ids(), [])
        self.assertTrue(subscriptions.delete(subscription_id))
        self.assertEqual(subscriptions.list_subscriptions(), [])

    def test_server_list_exposes_latest_latency_separately_from_historical_best(self):
        server = crud.create_server(parse_vless_url(
            "vless://uuid@server.example:443?security=none&type=tcp#Server"
        ).model_dump())
        crud.set_health(server["id"], True, 24, "")
        crud.set_health(server["id"], True, 680, "")
        refreshed = crud.get_server(server["id"])
        self.assertEqual(refreshed["latest_latency_ms"], 680)
        self.assertEqual(refreshed["best_latency_ms"], 24)

    def _server(self, name, address):
        return parse_vless_url(
            f"vless://uuid@{address}:443?security=none&type=tcp#{name}"
        )

    def test_sync_removes_missing_owned_servers_after_valid_feed(self):
        first, second = self._server("First", "first.example"), self._server("Second", "second.example")
        subscription_id = subscriptions.remember("https://feed.example/sub")
        a = crud.create_server(first.model_dump())
        b = crud.create_server(second.model_dump())
        subscriptions.link_current_servers(subscription_id, [first, second])

        with patch("app.subscriptions.protocols.parse_subscription_url", return_value=[second]), \
             patch("app.profiles._stored_profiles", return_value=[]):
            result = subscriptions.sync(subscription_id)

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["retained_count"], 0)
        self.assertIsNone(crud.get_server(a["id"]))
        self.assertIsNotNone(crud.get_server(b["id"]))

    def test_sync_retains_removed_server_if_an_interface_references_it(self):
        first, second = self._server("First", "first.example"), self._server("Second", "second.example")
        subscription_id = subscriptions.remember("https://feed.example/sub")
        a = crud.create_server(first.model_dump())
        crud.create_server(second.model_dump())
        subscriptions.link_current_servers(subscription_id, [first, second])

        with patch("app.subscriptions.protocols.parse_subscription_url", return_value=[second]), \
             patch("app.profiles._stored_profiles", return_value=[{"server_id": a["id"], "backup_server_id": None}]):
            result = subscriptions.sync(subscription_id)

        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["retained_count"], 1)
        self.assertIsNotNone(crud.get_server(a["id"]))

    def test_failed_or_empty_feed_does_not_remove_servers(self):
        first = self._server("First", "first.example")
        subscription_id = subscriptions.remember("https://feed.example/sub")
        server = crud.create_server(first.model_dump())
        subscriptions.link_current_servers(subscription_id, [first])

        with patch("app.subscriptions.protocols.parse_subscription_url", return_value=[]):
            with self.assertRaises(RuntimeError):
                subscriptions.sync(subscription_id)
        self.assertIsNotNone(crud.get_server(server["id"]))


if __name__ == "__main__":
    unittest.main()
