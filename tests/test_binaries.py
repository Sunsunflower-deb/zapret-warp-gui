"""Проверка возможностей бинарей десинка.

Дешёвая версия «capability probing» из плана (задача 3.1): стратегии ссылаются на
флаги, которых может не быть в старой сборке winws/nfqws. Тогда десинк молча не
стартует («winws завершился с кодом …»), и понять причину по логу трудно.

Тест читает строки из самого бинаря: если апстримный бинарь заменят на старый,
здесь будет понятная ошибка, а не загадочное падение при запуске.
"""
import os

import pytest

from core import paths

WINWS_FLAGS = [
    "--dpi-desync-fake-tls",
    "--dpi-desync-fake-tls-mod",   # rnd/dupsid — маскировка фейка
    "--dpi-desync-fooling",        # %Fooling%
    "--dpi-desync-repeats",
    "--dpi-desync-autottl",
    "--dpi-desync-cutoff",
    "--dpi-desync-fake-quic",
    "--hostlist",
    "--wf-tcp",
    "--wf-udp",
]

# Режимы, на которые ссылаются стратегии/рекомендации
WINWS_MODES = ["hostfakesplit", "multisplit", "multidisorder", "fakedsplit"]

NFQWS_FLAGS = [
    "--dpi-desync-fake-tls-mod",
    "--dpi-desync-autottl",
    "--dpi-desync-cutoff",
    "--filter-ssid",          # профили по Wi-Fi на Linux
    "--hostlist-auto",
]


def _binary(*names):
    for name in names:
        path = os.path.join(paths.BIN_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def _readable_strings(path):
    """Байты бинаря или None, если он упакован UPX (строки недоступны)."""
    data = open(path, "rb").read()
    if b"UPX!" in data:
        return None
    return data


@pytest.mark.skipif(os.name != "nt", reason="проверяем Windows-бинарь winws.exe")
def test_winws_supports_used_flags():
    path = _binary("winws.exe")
    if not path:
        pytest.skip("winws.exe отсутствует в bin/")
    data = _readable_strings(path)
    if data is None:
        pytest.skip("winws.exe упакован UPX — строки недоступны")
    missing = [f for f in WINWS_FLAGS if f.encode() not in data]
    assert not missing, f"winws.exe не знает флаги: {missing}"


@pytest.mark.skipif(os.name != "nt", reason="проверяем Windows-бинарь winws.exe")
def test_winws_supports_used_modes():
    path = _binary("winws.exe")
    if not path:
        pytest.skip("winws.exe отсутствует в bin/")
    data = _readable_strings(path)
    if data is None:
        pytest.skip("winws.exe упакован UPX — строки недоступны")
    missing = [m for m in WINWS_MODES if m.encode() not in data]
    assert not missing, f"winws.exe не знает режимы: {missing}"


def test_nfqws_supports_used_flags():
    path = _binary("nfqws")
    if not path:
        pytest.skip("nfqws отсутствует в bin/ (нормально на Windows-сборке)")
    data = _readable_strings(path)
    if data is None:
        pytest.skip("nfqws упакован UPX — строки недоступны; проверка только запуском "
                    "(полноценный capability probing — задача 3.1 плана)")
    missing = [f for f in NFQWS_FLAGS if f.encode() not in data]
    assert not missing, f"nfqws не знает флаги: {missing}"


def test_desync_binary_exists():
    path = paths.desync_binary()
    assert os.path.isfile(path), f"нет бинаря десинка: {path}"
