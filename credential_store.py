"""本地凭据存储：Windows DPAPI 用户级加密。

凭据（如网易云 MUSIC_U）绝不写入 settings.json 或日志。加密文件绑定当前
Windows 用户，换用户或换机器无法解密。DPAPI 不可用时本模块明确报错，
由调用方禁用登录下载，而不是退回到明文保存。
"""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from ncm_settings import app_data_dir

_FILE_HEADER = "NCM-cred-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CredentialUnavailable(RuntimeError):
    """当前系统无法提供安全凭据存储。"""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    blob = _DataBlob(len(data), pointer)
    # 防止 buffer 被垃圾回收
    blob._buffer = buffer
    return blob


def _blob_to_bytes(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialUnavailable("DPAPI 仅在 Windows 上可用。")
    try:
        crypt32 = ctypes.windll.crypt32
    except OSError as exc:
        raise CredentialUnavailable(f"无法加载 DPAPI：{exc}") from exc
    blob_in = _blob_from_bytes(data)
    blob_out = _DataBlob()
    ok = crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None,
                                  _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise CredentialUnavailable(f"DPAPI 加密失败（错误码 {ctypes.GetLastError()}）。")
    return _blob_to_bytes(blob_out)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialUnavailable("DPAPI 仅在 Windows 上可用。")
    try:
        crypt32 = ctypes.windll.crypt32
    except OSError as exc:
        raise CredentialUnavailable(f"无法加载 DPAPI：{exc}") from exc
    blob_in = _blob_from_bytes(data)
    blob_out = _DataBlob()
    ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                    _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise CredentialUnavailable(f"DPAPI 解密失败（错误码 {ctypes.GetLastError()}）。")
    return _blob_to_bytes(blob_out)


def credentials_path() -> Path:
    return app_data_dir() / "credentials.bin"


class CredentialStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else credentials_path()

    def available(self) -> bool:
        return os.name == "nt"

    def save(self, values: dict):
        payload = json.dumps(values, ensure_ascii=False).encode("utf-8")
        protected = _protect(payload)
        encoded = base64.b64encode(protected).decode("ascii")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(_FILE_HEADER + "\n" + encoded, encoding="ascii")
        os.replace(temporary, self.path)

    def load(self) -> dict | None:
        if not self.path.is_file():
            return None
        try:
            content = self.path.read_text(encoding="ascii")
            header, _, encoded = content.partition("\n")
            if header.strip() != _FILE_HEADER:
                return None
            payload = _unprotect(base64.b64decode(encoded.strip()))
            values = json.loads(payload.decode("utf-8"))
            return values if isinstance(values, dict) else None
        except (OSError, ValueError, CredentialUnavailable):
            return None

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
