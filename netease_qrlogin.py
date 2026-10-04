"""网易云扫码登录：二维码 key 生成、状态轮询与 MUSIC_U 提取。

使用网易云的普通 /api/ 接口（2026-10 实测可用），不依赖加密。
MUSIC_U 只在内存中传递，绝不写入日志或文件；HTTP 访问集中在
_fetch，便于测试替换。
"""
import json
import urllib.parse
import urllib.request

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
UNIKEY_URL = "https://music.163.com/api/login/qrcode/unikey?type=1"
CHECK_URL = "https://music.163.com/api/login/qrcode/client/login?key={}&type=1"
QR_URL_TEMPLATE = "https://music.163.com/login?keyuuid={}"

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


def _fetch(url: str, timeout: float = 10.0) -> tuple[dict, list[str]]:
    """GET 并解析 JSON；返回 (payload, Set-Cookie 头列表)。"""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            set_cookie = list(response.headers.get_all("Set-Cookie") or [])
    except OSError as exc:
        raise QRLoginError(f"网络请求失败：{exc}") from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise QRLoginError("登录接口返回了无法解析的数据。") from exc
    if not isinstance(payload, dict):
        raise QRLoginError("登录接口返回了意外的数据格式。")
    return payload, set_cookie


def create_qr_key() -> str:
    """生成一个二维码登录 key（unikey）。"""
    payload, _ = _fetch(UNIKEY_URL)
    if payload.get("code") != 200 or not payload.get("unikey"):
        raise QRLoginError(f"无法生成登录二维码（错误码 {payload.get('code')}）。")
    return str(payload["unikey"])


def qr_login_url(unikey: str) -> str:
    """二维码内容：网易云 App 扫码后打开并确认登录。"""
    return QR_URL_TEMPLATE.format(unikey)


def check_qr_key(unikey: str) -> dict:
    """查询扫码状态；返回 {code, message, music_u}。

    music_u 只在 QR_SUCCESS 且服务器返回了该 Cookie 时存在。
    """
    payload, set_cookie = _fetch(CHECK_URL.format(urllib.parse.quote(unikey)))
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


def extract_music_u(set_cookie_items: list[str]) -> str | None:
    """从 Set-Cookie 头列表中提取 MUSIC_U 的值。"""
    for item in set_cookie_items or []:
        for pair in item.split(";"):
            name, _, value = pair.strip().partition("=")
            name, value = name.strip(), value.strip()
            if name == "MUSIC_U" and value:
                return value
    return None
