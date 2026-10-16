import importlib
import subprocess
import sys
from pathlib import Path

import pytest


class MemoryStore:
    def __init__(self):
        self.value = None
        self.fail = False

    def load(self):
        if self.fail:
            raise OSError("private-storage-response")
        return self.value

    def save(self, user, password):
        if self.fail:
            raise OSError("private-storage-response")
        self.value = (user, password)

    def forget(self):
        if self.fail:
            raise OSError("private-storage-response")
        self.value = None


def test_windows_vault_roundtrip_survives_new_instance_without_project_files(tmp_path):
    module = importlib.import_module("qf.credentials")
    store = module.WindowsCredentialStore(tmp_path)
    try:
        assert store.load() is None
        store.save("offline-user", "离线-password-123")
        assert module.WindowsCredentialStore(tmp_path).load() == (
            "offline-user", "离线-password-123")
        child = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", "-c",
             "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[2]); "
             "from qf.credentials import WindowsCredentialStore; "
             "value = WindowsCredentialStore(Path(sys.argv[1])).load(); "
             "raise SystemExit(0 if value == ('offline-user', '离线-password-123') else 1)",
             str(tmp_path), str(Path(__file__).resolve().parents[1])],
            capture_output=True, text=True, timeout=10,
        )
        assert child.returncode == 0
        assert child.stdout == child.stderr == ""
        assert list(tmp_path.iterdir()) == []
        assert module.WindowsCredentialStore(tmp_path / "other").load() is None
    finally:
        store.forget()
    assert store.load() is None
    store.forget()


def test_saved_login_confirms_success_and_does_not_expose_password(tmp_path):
    module = importlib.import_module("qf.credentials")
    store = MemoryStore()
    login = module.SavedLogin(tmp_path, store=store)
    login.prepare("offline-user", "private-password", True)
    assert store.load() is None
    login.confirm()
    restored = module.SavedLogin(tmp_path, store=store)
    assert restored.info()["user"] == "offline-user" and restored.info()["saved"]
    assert "private-password" not in str(restored.info())
    assert restored.resolve("offline-user", "") == ("offline-user", "private-password")
    with pytest.raises(ValueError):
        restored.resolve("different-user", "")
    restored.forget()
    assert store.load() is None
    assert restored.info()["user"] == "" and not restored.info()["saved"]


def test_failed_login_and_forget_cannot_later_save_pending_password(tmp_path):
    module = importlib.import_module("qf.credentials")
    store = MemoryStore()
    login = module.SavedLogin(tmp_path, store=store)
    login.prepare("u", "private-password", True)
    login.discard()
    login.confirm()
    assert store.value is None


def test_failed_replacement_keeps_previous_login_and_unchecking_removes_it(tmp_path):
    module = importlib.import_module("qf.credentials")
    store = MemoryStore()
    store.save("known-user", "known-password")
    login = module.SavedLogin(tmp_path, store=store)
    login.prepare("wrong-user", "wrong-password", True)
    login.discard()
    login.confirm()
    assert store.value == ("known-user", "known-password")
    credentials = login.resolve("known-user", "")
    login.prepare(*credentials, False)
    login.confirm()
    assert credentials == ("known-user", "known-password")
    assert store.value is None and not login.info()["saved"]
    login.prepare("u", "private-password", True)
    login.forget()
    login.confirm()
    assert store.value is None


def test_storage_failure_is_explicit_and_does_not_fall_back_to_files(tmp_path):
    module = importlib.import_module("qf.credentials")
    store = MemoryStore()
    store.fail = True
    login = module.SavedLogin(tmp_path, store=store)
    assert login.info()["issue"]
    login.prepare("u", "private-password", True)
    login.confirm()
    assert login.info()["issue"] and not login.info()["saved"]
    assert "private-" not in str(login.info())
    assert list(Path(tmp_path).iterdir()) == []
