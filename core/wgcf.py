"""Встроенная регистрация WARP-ключа через wgcf.

Регистрация идёт по HTTPS к api.cloudflareclient.com. На «жёстких» сетях
доступен только через обфускацию nfqws (домен cloudflareclient.com уже в
списках Simple Fake), поэтому сначала запускается nfqws.
"""
import os
import subprocess
import time
import urllib.request

from . import config, engine, paths

WGCF_VERSION = "v2.2.32"


def binary():
    return os.path.join(paths.BIN_DIR, "wgcf.exe" if os.name == "nt" else "wgcf")


def _asset_name():
    if os.name == "nt":
        return f"wgcf_{WGCF_VERSION[1:]}_windows_amd64.exe"
    return f"wgcf_{WGCF_VERSION[1:]}_linux_amd64"


def _url():
    return (f"https://github.com/ViRb3/wgcf/releases/download/"
            f"{WGCF_VERSION}/{_asset_name()}")


def ensure_binary():
    """Вернуть путь к wgcf, скачав его при необходимости."""
    p = binary()
    if os.path.isfile(p):
        return p
    print("Скачивание wgcf:", _url())
    urllib.request.urlretrieve(_url(), p)
    os.chmod(p, 0o755)
    return p


def run_key(license_key="", force=False):
    """Получить WARP-ключ: nfqws → wgcf register → wgcf generate."""
    wgcf = ensure_binary()
    os.makedirs(paths.WGCF_DIR, exist_ok=True)

    account_file = os.path.join(paths.WGCF_DIR, "wgcf-account.toml")
    if not os.path.isfile(account_file) or force:
        if force and os.path.isfile(account_file):
            os.remove(account_file)
        # nfqws должен работать: он обфусцирует api.cloudflareclient.com
        if not engine.is_running():
            print("Запуск nfqws (обфускация регистрации)…")
            cfg = config.load()
            engine.start(cfg["strategy"], cfg["interface"],
                         cfg["gamefilter_tcp"], cfg["gamefilter_udp"])
            time.sleep(3)
        print("Регистрация WARP-аккаунта (wgcf register)…")
        subprocess.run([wgcf, "register", "--accept-tos"],
                       cwd=paths.WGCF_DIR, check=True)
    else:
        print("Аккаунт уже есть:", account_file)
        print("Пропускаю регистрацию (--force для новой).")

    if license_key:
        print("Привязка license key:", license_key)
        subprocess.run([wgcf, "update", "--license-key", license_key],
                       cwd=paths.WGCF_DIR, check=True)

    print("Генерация WireGuard-профиля (wgcf generate)…")
    subprocess.run([wgcf, "generate"], cwd=paths.WGCF_DIR, check=True)

    print("Готово:")
    print("  аккаунт:", os.path.join(paths.WGCF_DIR, "wgcf-account.toml"))
    print("  профиль:", os.path.join(paths.WGCF_DIR, "wgcf-profile.conf"))
    print("Совет: license_key из wgcf-account.toml позволяет привязать другие "
          "устройства: cli.py key --license-key <KEY>")
