"""快期凭证由 Windows 凭据管理器保存，不写入项目文件或页面状态。"""

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path


class CredentialError(ValueError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    def __init__(self, root: Path):
        identity = str(root.resolve()).casefold().encode("utf-8")
        self._target = "QfTqSdk/" + hashlib.sha256(identity).hexdigest()[:32]

    @staticmethod
    def _api():
        if os.name != "nt":
            raise CredentialError("当前系统不支持 Windows 凭据保存。")
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def load(self):
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self._target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialError("Windows 无法读取已保存的账号密码。")
        try:
            item = pointer.contents
            password = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
            try:
                result = (item.UserName or "", password.decode("utf-16-le"))
            except UnicodeError:
                raise CredentialError("已保存的密码无法读取，请重新输入。") from None
            if not all(result):
                raise CredentialError("已保存的账号密码不完整，请重新输入。")
            return result
        finally:
            if pointer.contents.CredentialBlobSize:
                ctypes.memset(pointer.contents.CredentialBlob, 0,
                              pointer.contents.CredentialBlobSize)
            api.CredFree(pointer)

    def save(self, user, password):
        if (not isinstance(user, str) or not isinstance(password, str)
                or not user or not password or "\0" in user or len(user) > 256):
            raise CredentialError("账号密码无法保存，请检查输入。")
        payload = password.encode("utf-16-le")
        if len(payload) > 2560:
            raise CredentialError("密码长度超过 Windows 保存限制。")
        buffer = ctypes.create_string_buffer(payload)
        item = _Credential(Type=1, TargetName=self._target, UserName=user, Persist=2,
                           CredentialBlobSize=len(payload),
                           CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE)))
        try:
            if not self._api().CredWriteW(ctypes.byref(item), 0):
                raise CredentialError("Windows 无法保存账号密码，请检查本机凭据服务。")
        finally:
            ctypes.memset(buffer, 0, len(buffer))

    def forget(self):
        if not self._api().CredDeleteW(self._target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError("Windows 无法删除已保存凭证，请稍后重试。")


class SavedLogin:
    """两个窗口共用；只在连接成功后保存，密码不返回前端。"""

    def __init__(self, root: Path, *, store=None):
        self._store = store if store is not None else WindowsCredentialStore(root)
        self._user, self._saved, self._issue, self._pending = "", False, "", None
        try:
            saved = self._store.load()
            if saved:
                self._user, self._saved = saved[0], True
        except Exception:
            self._issue = "无法读取 Windows 保存的凭证，请手动输入。"

    def info(self):
        return {"user": self._user, "saved": self._saved, "issue": self._issue}

    def resolve(self, user, password):
        if not isinstance(user, str) or not isinstance(password, str) or not user.strip():
            raise ValueError("请填写快期账号和密码。")
        user = user.strip()
        if password:
            return user, password
        if self._saved and user == self._user:
            try:
                saved = self._store.load()
                if saved and saved[0] == user:
                    return saved
            except Exception:
                pass
        raise ValueError("该账号没有可用的已保存密码，请重新输入。")

    def prepare(self, user, password, remember):
        if type(remember) is not bool:
            raise ValueError("记住密码选项无效。")
        self.discard()
        if remember:
            self._pending = (user, password)
        else:
            self.forget()

    def confirm(self):
        pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            self._store.save(*pending)
            self._user, self._saved, self._issue = pending[0], True, ""
        except Exception:
            self._issue = "连接已成功，但 Windows 未能保存凭证；下次仍需手动输入。"

    def discard(self):
        self._pending = None

    def forget(self):
        self.discard()
        try:
            self._store.forget()
        except Exception:
            raise CredentialError("删除已保存凭证未完成，请稍后重试。") from None
        self._user, self._saved, self._issue = "", False, ""
