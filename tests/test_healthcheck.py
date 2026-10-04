import unittest

from app.healthcheck import _http_probe_succeeded, _probe_targets


class TestHealthProbeResponse(unittest.TestCase):
    def test_any_complete_http_response_proves_egress(self):
        for status in ("200", "204", "403", "429", "500", "599"):
            with self.subTest(status=status):
                self.assertTrue(_http_probe_succeeded(0, status))

    def test_failed_or_missing_response_does_not_prove_egress(self):
        for code, status in ((7, "000"), (28, "000"), (0, "000"), (0, "bad"), (0, ""), (0, "600")):
            with self.subTest(code=code, status=status):
                self.assertFalse(_http_probe_succeeded(code, status))

    def test_prefers_configured_server_sni_before_fallback_targets(self):
        self.assertEqual(
            _probe_targets({"sni": "mask.example"}),
            ["https://mask.example/", "https://www.gstatic.com/generate_204"],
        )
        self.assertEqual(
            _probe_targets({}),
            ["https://www.gstatic.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace"],
        )

    def test_route_check_marks_http_timeout_inconclusive_when_vpn_tcp_port_is_open(self):
        from unittest.mock import patch
        from app import healthcheck

        with patch.object(healthcheck, "check_server", return_value=(False, None, "curl timeout")), \
             patch.object(healthcheck, "tcp_check", return_value=(True, 12, "")):
            result = healthcheck.route_check({"address": "nl.example", "port": 443})
        self.assertIsNone(result[0])
        self.assertEqual(result[1], 12)
        self.assertIn("маршрут сохранён", result[2])


if __name__ == "__main__":
    unittest.main()
