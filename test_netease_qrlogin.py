"""扫码登录模块测试：全部使用假传输，不访问网络。"""
import unittest
from unittest.mock import patch

import netease_qrlogin as qr


def fake_fetch(payload, set_cookie=None):
    def _impl(url, timeout=10.0):
        return payload, list(set_cookie or [])
    return _impl


class CreateQrKeyTests(unittest.TestCase):
    def test_returns_unikey(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 200, "unikey": "abc-123"})):
            self.assertEqual(qr.create_qr_key(), "abc-123")

    def test_error_on_bad_code(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 500})):
            with self.assertRaises(qr.QRLoginError):
                qr.create_qr_key()

    def test_qr_login_url_format(self):
        url = qr.qr_login_url("abc-123")
        self.assertEqual(url, "https://music.163.com/login?keyuuid=abc-123")


class CheckQrKeyTests(unittest.TestCase):
    def test_waiting(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 801, "message": "等待扫码"})):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_WAITING)
        self.assertIsNone(result["music_u"])
        self.assertEqual(result["message"], "等待扫码")

    def test_scanned(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 802, "message": "扫码确认"})):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_SCANNED)

    def test_success_extracts_music_u(self):
        set_cookie = [
            "__csrf_token=abc; Path=/; Domain=.music.163.com",
            "MUSIC_U=cookievalue123; Path=/; Domain=.music.163.com; HttpOnly",
            "MUSIC_SNS=xyz; Path=/",
        ]
        with patch.object(qr, "_fetch", fake_fetch({"code": 803}, set_cookie)):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_SUCCESS)
        self.assertEqual(result["music_u"], "cookievalue123")

    def test_success_without_music_u_raises(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 803}, [])):
            with self.assertRaises(qr.QRLoginError):
                qr.check_qr_key("key")

    def test_expired(self):
        with patch.object(qr, "_fetch", fake_fetch({"code": 800, "message": "登录二维码已过期"})):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_EXPIRED)

    def test_url_is_quoted(self):
        seen = {}

        def impl(url, timeout=10.0):
            seen["url"] = url
            return {"code": 801}, []

        with patch.object(qr, "_fetch", impl):
            qr.check_qr_key("key with space")
        self.assertIn("key=key%20with%20space", seen["url"])


class ExtractMusicUTests(unittest.TestCase):
    def test_from_single_header(self):
        items = ["MUSIC_U=abc; Path=/; HttpOnly"]
        self.assertEqual(qr.extract_music_u(items), "abc")

    def test_ignores_other_cookies_and_empty(self):
        self.assertIsNone(qr.extract_music_u(["NMTID=1", "MUSIC_A=2"]))
        self.assertIsNone(qr.extract_music_u([]))
        self.assertIsNone(qr.extract_music_u(None))

    def test_handles_extra_attributes_and_spaces(self):
        items = ["MUSIC_U = spaced value ; Max-Age=1"]
        self.assertEqual(qr.extract_music_u(items), "spaced value")

    def test_never_logs_cookie(self):
        # 防回归：任何错误消息都不应包含 MUSIC_U 的值。
        secret = "topsecretcookievalue"
        with patch.object(qr, "_fetch", fake_fetch({"code": 803},
                                                   [f"MUSIC_U={secret}; Path=/"])):
            try:
                qr.check_qr_key("key")
            except qr.QRLoginError as exc:
                self.assertNotIn(secret, str(exc))


if __name__ == "__main__":
    unittest.main()
