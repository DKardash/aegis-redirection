import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db as database
from app.config import settings
from app import subscriptions


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


if __name__ == "__main__":
    unittest.main()
