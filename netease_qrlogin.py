"""网易云扫码登录：二维码 key 生成、状态轮询与 MUSIC_U 提取。

按社区事实标准实现（NeteaseCloudMusicApi 4.32.0 的 login_qr_key /
login_qr_create / login_qr_check，2026-10 核对源码）：

- 请求用 **POST 表单**到普通 /api/ 接口，带 iPhone 客户端 UA 与设备 Cookie；
- **type=3 表示 App「扫一扫」原生确认**（type=1 会打开网页登录页，
  这正是旧版扫出登录页的原因）；
- 二维码内容为 `https://music.163.com/login?codekey=<unikey>`。

MUSIC_U 只在内存中传递，绝不写入日志或文件；HTTP 访问集中在 _fetch，
便于测试替换。
"""
import json
import random
import string
import time
import urllib.parse
import urllib.request

USER_AGENT = "NeteaseMusic 9.0.90/5038 (iPhone; iOS 16.2; zh_CN)"
UNIKEY_URL = "https://music.163.com/api/login/qrcode/unikey"
CHECK_URL = "https://music.163.com/api/login/qrcode/client/login"
QR_URL_TEMPLATE = "https://music.163.com/login?codekey={}"
QR_TYPE = 3

# 二维码状态码（网易云约定）
QR_EXPIRED = 800
QR_WAITING = 801
QR_SCANNED = 802
QR_SUCCESS = 803

QR_STATUS_LABELS = {
    QR_EXPIRED: "二维码已过期，请点击“刷新二维码”。",
    QR_WAITING: "等待扫码：打开网易云音乐 App，扫一扫登录。",
    QR_SCANNED: "已扫码，请在手机上确认登录。",
    QR_SUCCESS: "扫码成功，正在验证登录状态…",
}


class QRLoginError(RuntimeError):
    """扫码登录接口错误，message 面向用户显示。"""


def _device_cookie() -> str:
    """构造 iPhone 客户端设备 Cookie（参照实现的 api 加密请求头）。"""
    hex_chars = "0123456789ABCDEF"
    device_id = "".join(random.choice(hex_chars) for _ in range(52))
    header = {
        "osver": "16.2",
        "deviceId": device_id,
        "os": "iPhone OS",
        "appver": "9.0.90",
        "versioncode": "140",
        "mobilename": "",
        "buildver": str(int(time.time())),
        "resolution": "1920x1080",
        "__csrf": "",
        "channel": "distribution",
        "requestId": f"{random.randint(10 ** 9, 10 ** 10 - 1)}0{random.randint(100, 999)}",
    }
    return "; ".join(f"{key}={value}" for key, value in header.items())


def _fetch(url: str, payload: dict, timeout: float = 10.0) -> tuple[dict, list[str]]:
    """POST 表单并解析 JSON；返回 (payload, Set-Cookie 头列表)。"""
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Cookie": _device_cookie(),
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            set_cookie = list(response.headers.get_all("Set-Cookie") or [])
    except OSError as exc:
        raise QRLoginError(f"网络请求失败：{exc}") from exc
    try:
        result = json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise QRLoginError("登录接口返回了无法解析的数据。") from exc
    if not isinstance(result, dict):
        raise QRLoginError("登录接口返回了意外的数据格式。")
    return result, set_cookie


def create_qr_key() -> str:
    """生成一个二维码登录 key（unikey，type=3：App 原生确认）。"""
    payload, _ = _fetch(UNIKEY_URL, {"type": QR_TYPE})
    if payload.get("code") != 200 or not payload.get("unikey"):
        raise QRLoginError(f"无法生成登录二维码（错误码 {payload.get('code')}）。")
    return str(payload["unikey"])


def qr_login_url(unikey: str) -> str:
    """二维码内容：网易云 App 扫码后原生确认登录。"""
    return QR_URL_TEMPLATE.format(unikey)


def check_qr_key(unikey: str) -> dict:
    """查询扫码状态；返回 {code, message, music_u}。

    music_u 只在 QR_SUCCESS 且服务器返回了该 Cookie 时存在。
    """
    payload, set_cookie = _fetch(CHECK_URL, {"key": unikey, "type": QR_TYPE})
    code = int(payload.get("code") or 0)
    result = {
        "code": code,
        "message": str(payload.get("message") or payload.get("msg") or ""),
        "music_u": None,
    }
    if code == QR_SUCCESS:
        result["music_u"] = extract_music_u(set_cookie)
        if not result["music_u"]:
            raise QRLoginError("扫码成功但未取到登录凭据，请重试。")
    return result


def extract_music_u(set_cookie_items: list[str] | None) -> str | None:
    """从 Set-Cookie 头列表中提取 MUSIC_U 的值。"""
    for item in set_cookie_items or []:
        for pair in item.split(";"):
            name, _, value = pair.strip().partition("=")
            name, value = name.strip(), value.strip()
            if name == "MUSIC_U" and value:
                return value
    return None
