"""Юнит-тесты на парсинг share-URL и генерацию конфигов Xray.
Запуск: python -m unittest discover -s tests (из каталога manager)."""

import unittest

from app.protocols import (
    build_share_url,
    parse_hysteria2_url,
    parse_share_url,
    parse_trojan_url,
    parse_vless_url,
    server_identity,
)
from app.xray import build_config, build_multi_config

VLESS_URL = (
    "vless://11111111-2222-3333-4444-555555555555@vless.example.com:443"
    "?encryption=none&security=reality&type=tcp&flow=xtls-rprx-vision"
    "&sni=www.microsoft.com&fp=chrome&pbk=ABC123&sid=abcd#My Server"
)

TROJAN_URL = (
    "trojan://pass123@trojan.example.com:443"
    "?security=tls&type=tcp&sni=trojan.example.com&fp=chrome"
    "&alpn=h2#Trojan Server"
)

HYSTERIA2_URL = (
    "hysteria2://s3cret@hy2.example.com:8443"
    "?sni=hy2.example.com&fp=chrome#Hy2 Server"
)

XHTTP_URL = (
    "vless://22222222-3333-4444-5555-666666666666@xhttp.example.com:443"
    "?encryption=none&security=reality&type=xhttp&mode=auto&path=/xray"
    "&sni=www.cloudflare.com&fp=chrome&pbk=DEF456&sid=ef12#Xhttp Server"
)


class TestParseUrls(unittest.TestCase):
    def test_parse_vless_url(self):
        s = parse_vless_url(VLESS_URL)
        self.assertEqual(s.address, "vless.example.com")
        self.assertEqual(s.port, 443)
        self.assertEqual(s.uuid, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(s.security, "reality")
        self.assertEqual(s.sni, "www.microsoft.com")
        self.assertEqual(s.reality_public_key, "ABC123")
        self.assertEqual(s.reality_short_id, "abcd")
        self.assertEqual(s.fingerprint, "chrome")
        self.assertEqual(s.name, "My Server")

    def test_parse_trojan_url(self):
        s = parse_trojan_url(TROJAN_URL)
        self.assertEqual(s.protocol, "trojan")
        self.assertEqual(s.uuid, "pass123")
        self.assertEqual(s.security, "tls")
        self.assertEqual(s.sni, "trojan.example.com")

    def test_parse_hysteria2_url(self):
        s = parse_hysteria2_url(HYSTERIA2_URL)
        self.assertEqual(s.protocol, "hysteria2")
        self.assertEqual(s.uuid, "s3cret")
        self.assertEqual(s.network, "hysteria")
        self.assertEqual(s.security, "tls")

    def test_parse_xhttp(self):
        s = parse_vless_url(XHTTP_URL)
        self.assertEqual(s.network, "xhttp")
        self.assertEqual(s.mode, "auto")
        self.assertEqual(s.path, "/xray")

    def test_dispatch_auto(self):
        self.assertEqual(parse_share_url(VLESS_URL).protocol, "vless")
        self.assertEqual(parse_share_url(TROJAN_URL).protocol, "trojan")
        self.assertEqual(parse_share_url(HYSTERIA2_URL).protocol, "hysteria2")

    def test_roundtrip(self):
        for url in (VLESS_URL, TROJAN_URL, HYSTERIA2_URL, XHTTP_URL):
            s = parse_share_url(url)
            s2 = parse_share_url(build_share_url(s.model_dump()))
            self.assertEqual(s2.model_dump(), s.model_dump(), url)

    def test_reject_invalid(self):
        with self.assertRaises(ValueError):
            parse_share_url("ss://notsupported")

    def test_subscription_identity_keeps_distinct_protocols_on_same_endpoint(self):
        vless = parse_share_url(VLESS_URL).model_dump()
        hysteria = parse_hysteria2_url(HYSTERIA2_URL).model_dump()
        hysteria.update(address=vless["address"], port=vless["port"])
        self.assertNotEqual(server_identity(vless), server_identity(hysteria))
        renamed = dict(vless, name="Another display name")
        self.assertEqual(server_identity(vless), server_identity(renamed))


class TestBuildConfig(unittest.TestCase):
    def test_build_config_proxy_inbound(self):
        s = parse_vless_url(VLESS_URL).model_dump()
        cfg = build_config(s, inbound="proxy")
        tags = {i["tag"] for i in cfg["inbounds"]}
        self.assertEqual(tags, {"socks-in", "http-in"})
        socks = next(i for i in cfg["inbounds"] if i["tag"] == "socks-in")
        self.assertEqual(socks["protocol"], "socks")
        self.assertIs(socks["settings"]["udp"], True)
        out = cfg["outbounds"][0]
        self.assertEqual(out["protocol"], "vless")
        self.assertEqual(out["streamSettings"]["security"], "reality")
        self.assertEqual(out["streamSettings"]["realitySettings"]["publicKey"], "ABC123")
        self.assertEqual(cfg["routing"]["rules"][0]["outboundTag"], "vless-main")

    def test_build_config_tproxy_inbound(self):
        s = parse_vless_url(VLESS_URL).model_dump()
        cfg = build_config(s, inbound="tproxy")
        self.assertEqual(cfg["inbounds"][0]["streamSettings"]["sockopt"]["tproxy"], "tproxy")

    def test_build_config_both_inbound(self):
        s = parse_vless_url(VLESS_URL).model_dump()
        cfg = build_config(s, inbound="both")
        tags = {i["tag"] for i in cfg["inbounds"]}
        self.assertEqual(tags, {"socks-in", "http-in", "tproxy-in"})
        tp = next(i for i in cfg["inbounds"] if i["tag"] == "tproxy-in")
        self.assertEqual(tp["port"], 12345)
        self.assertEqual(tp["streamSettings"]["sockopt"]["tproxy"], "tproxy")

    def test_build_config_trojan(self):
        s = parse_trojan_url(TROJAN_URL).model_dump()
        cfg = build_config(s)
        out = cfg["outbounds"][0]
        self.assertEqual(out["protocol"], "trojan")
        self.assertEqual(out["settings"]["servers"][0]["password"], "pass123")
        self.assertEqual(out["streamSettings"]["security"], "tls")

    def test_build_config_hysteria2(self):
        s = parse_hysteria2_url(HYSTERIA2_URL).model_dump()
        cfg = build_config(s)
        out = cfg["outbounds"][0]
        self.assertEqual(out["protocol"], "hysteria")
        self.assertEqual(out["settings"]["version"], 2)
        self.assertEqual(out["streamSettings"]["network"], "hysteria")
        self.assertEqual(out["streamSettings"]["hysteriaSettings"]["auth"], "s3cret")

    def test_build_config_xhttp(self):
        s = parse_vless_url(XHTTP_URL).model_dump()
        cfg = build_config(s)
        out = cfg["outbounds"][0]
        stream = out["streamSettings"]
        self.assertEqual(stream["network"], "xhttp")
        self.assertEqual(stream["xhttpSettings"]["path"], "/xray")
        self.assertEqual(stream["xhttpSettings"]["mode"], "auto")

    def test_build_config_kill_switch_shape(self):
        s = parse_vless_url(VLESS_URL).model_dump()
        cfg = build_config(s)
        tags = {o["tag"] for o in cfg["outbounds"]}
        self.assertIn("direct", tags)
        self.assertIn("block", tags)
        for rule in cfg["routing"]["rules"]:
            self.assertEqual(rule["outboundTag"], "vless-main")

    def test_build_multi_config_routes_profile_by_inbound(self):
        default = parse_vless_url(VLESS_URL).model_dump()
        profile_server = parse_hysteria2_url(HYSTERIA2_URL).model_dump()
        cfg = build_multi_config(default, [{
            "id": 2,
            "tproxy_port": 12346,
            "server": profile_server,
        }])
        inbound = next(i for i in cfg["inbounds"] if i["tag"] == "tproxy-profile-2")
        self.assertEqual(inbound["port"], 12346)
        rule = cfg["routing"]["rules"][0]
        self.assertEqual(rule["inboundTag"], ["tproxy-profile-2"])
        self.assertEqual(rule["outboundTag"], "profile-2")
        outbound = next(o for o in cfg["outbounds"] if o["tag"] == "profile-2")
        self.assertEqual(outbound["protocol"], "hysteria")


if __name__ == "__main__":
    unittest.main()
