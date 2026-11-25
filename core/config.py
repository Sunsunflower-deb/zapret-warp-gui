"""Конфигурация приложения (JSON)."""
import json
import os

from . import paths

DEFAULTS = {
    # WARP-only Simple Fake: минимальный десинк (только Cloudflare WARP),
    # TCP h2 (обходит троттлинг/блок QUIC UDP-443 на «жёстких» сетях),
    # режим без DoH (DoH-домен может резаться по SNI до поднятия туннеля).
    "strategy": "warp_simple_fake.bat",
    "interface": "any",
    "gamefilter_tcp": False,
    "gamefilter_udp": False,
    # Значение плейсхолдера %Fooling% в стратегиях.
    # "auto" = по платформе: md5sig на Windows, "ts,md5sig" на Linux.
    # `ts` работает только при включённых TCP timestamps (в Windows они
    # выключены по умолчанию), а без работающего fooling фейковый пакет
    # доходит до реального сервера и ломает TLS-рукопожатие.
    # Явное значение ("ts", "md5sig", "badseq", "md5sig,badseq") — способ
    # откатиться, если на конкретной сети работает только старый вариант.
    "fooling": "auto",
    "warp_enabled": True,
    "warp_mode": "warp",
    "warp_protocol": "MASQUE",
    "warp_masque": "h2-only",
    "warp_endpoint": "",
    "warp_user": "",
}


def load():
    cfg = dict(DEFAULTS)
    if os.path.isfile(paths.CONFIG_PATH):
        try:
            with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except (OSError, ValueError):
            pass
    return cfg


def save(cfg):
    with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
