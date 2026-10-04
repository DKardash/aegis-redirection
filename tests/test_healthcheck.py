import unittest

from app.healthcheck import _http_probe_succeeded


class TestHealthProbeResponse(unittest.TestCase):
    def test_any_complete_http_response_proves_egress(self):
        for status in ("200", "204", "403", "429", "500", "599"):
            with self.subTest(status=status):
                self.assertTrue(_http_probe_succeeded(0, status))

    def test_failed_or_missing_response_does_not_prove_egress(self):
        for code, status in ((7, "000"), (28, "000"), (0, "000"), (0, "bad"), (0, ""), (0, "600")):
            with self.subTest(code=code, status=status):
                self.assertFalse(_http_probe_succeeded(code, status))


if __name__ == "__main__":
    unittest.main()
