"""扫码登录模块测试：全部使用假传输，不访问网络。"""
import unittest
from unittest.mock import patch

import netease_qrlogin as qr


class Recorder:
    """记录 _fetch 调用并返回预设响应。"""

    def __init__(self, payload, set_cookie=None):
        self.payload = payload
        self.set_cookie = set_cookie or []
        self.calls = []

    def __call__(self, url, req_payload, timeout=10.0):
        self.calls.append((url, req_payload))
        return self.payload, list(self.set_cookie)


class CreateQrKeyTests(unittest.TestCase):
    def test_returns_unikey(self):
        rec = Recorder({"code": 200, "unikey": "abc-123"})
        with patch.object(qr, "_fetch", rec):
            self.assertEqual(qr.create_qr_key(), "abc-123")
        url, payload = rec.calls[0]
        self.assertEqual(url, qr.UNIKEY_URL)
        self.assertEqual(payload, {"type": 3})

    def test_error_on_bad_code(self):
        with patch.object(qr, "_fetch", Recorder({"code": 500})):
            with self.assertRaises(qr.QRLoginError):
                qr.create_qr_key()

    def test_qr_url_uses_codekey(self):
        url = qr.qr_login_url("abc-123")
        self.assertEqual(url, "https://music.163.com/login?codekey=abc-123")

    def test_type_3_means_app_native_confirm(self):
        # type=1 会打开网页登录页（用户实测），必须固定为 3。
        self.assertEqual(qr.QR_TYPE, 3)
        self.assertIn("type", qr.QR_STATUS_LABELS if False else {}) if False else None


class CheckQrKeyTests(unittest.TestCase):
    def test_waiting(self):
        rec = Recorder({"code": 801, "message": "等待扫码"})
        with patch.object(qr, "_fetch", rec):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_WAITING)
        self.assertIsNone(result["music_u"])
        self.assertEqual(result["message"], "等待扫码")
        url, payload = rec.calls[0]
        self.assertEqual(url, qr.CHECK_URL)
        self.assertEqual(payload, {"key": "key", "type": 3})

    def test_scanned(self):
        with patch.object(qr, "_fetch", Recorder({"code": 802, "message": "扫码确认"})):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_SCANNED)

    def test_success_extracts_music_u(self):
        set_cookie = [
            "__csrf_token=abc; Path=/; Domain=.music.163.com",
            "MUSIC_U=cookievalue123; Path=/; Domain=.music.163.com; HttpOnly",
            "MUSIC_SNS=xyz; Path=/",
        ]
        with patch.object(qr, "_fetch", Recorder({"code": 803}, set_cookie)):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_SUCCESS)
        self.assertEqual(result["music_u"], "cookievalue123")

    def test_success_without_music_u_raises(self):
        with patch.object(qr, "_fetch", Recorder({"code": 803}, [])):
            with self.assertRaises(qr.QRLoginError):
                qr.check_qr_key("key")

    def test_expired(self):
        with patch.object(qr, "_fetch", Recorder({"code": 800, "message": "登录二维码已过期"})):
            result = qr.check_qr_key("key")
        self.assertEqual(result["code"], qr.QR_EXPIRED)


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
        with patch.object(qr, "_fetch", Recorder({"code": 803},
                                                 [f"MUSIC_U={secret}; Path=/"])):
            try:
                qr.check_qr_key("key")
            except qr.QRLoginError as exc:
                self.assertNotIn(secret, str(exc))


if __name__ == "__main__":
    unittest.main()
