"""Пробы: «трафик реально прошёл или нет» и классификация причины отказа.

Один модуль на три потребителя (этап 2 плана):
* панель доступности в GUI — какие сайты открываются;
* watchdog — жив ли туннель;
* автоподбор стратегии — какая техника десинка работает на этой сети.

Ключевая идея — не «успех/неуспех», а **класс ошибки**:

| класс        | что значит                                                |
|--------------|-----------------------------------------------------------|
| `ok`         | TCP+TLS установились, данные прошли                        |
| `timeout`    | молчание: блокировка по IP, дроп пакетов                   |
| `reset`      | RST сразу после ClientHello: DPI разорвал поток            |
| `refused`    | порт закрыт (сервис не слушает)                            |
| `dns`        | имя не разрешилось                                         |
| `tls_<...>`  | TLS alert: **фейк дошёл до сервера** и испортил поток       |
| `os_<Err>`   | прочие сетевые ошибки                                      |

Для автоподбора важно различать `timeout` и `tls_*`: в первом случае нужен другой
метод обхода, во втором — другой `fooling` (фейк не должен доходить до сервера).
"""
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

DEFAULT_TIMEOUT = 5.0


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    kind: str
    rtt_ms: float
    detail: str = ""

    @property
    def looks_like_leak(self):
        """Похоже, что подделка дошла до сервера и сломала поток."""
        return self.kind == "reset" or self.kind.startswith("tls_")

    def to_dict(self):
        return asdict(self)


def _ms(started):
    return round((time.monotonic() - started) * 1000, 1)


def classify(exc):
    """Исключение → (kind, detail)."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, urllib.error.URLError) and isinstance(reason, BaseException):
        # urllib заворачивает настоящую причину в .reason: без разворота любая
        # сетевая ошибка выглядела бы как os_URLError, и автоподбор не смог бы
        # отличить timeout от TLS alert
        return classify(reason)
    if isinstance(exc, ssl.SSLError):
        reason = getattr(exc, "reason", None) or type(exc).__name__
        return "tls_" + str(reason).replace(" ", "_"), str(exc)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", str(exc)
    if isinstance(exc, ConnectionRefusedError):
        return "refused", str(exc)
    if isinstance(exc, ConnectionResetError):
        return "reset", str(exc)
    if isinstance(exc, socket.gaierror):
        return "dns", str(exc)
    return "os_" + type(exc).__name__, str(exc)


# --------------------------------------------------------------- TLS ----
def probe_tls(host, port=443, timeout=DEFAULT_TIMEOUT, verify=False, sni=None):
    """TLS-проба: устанавливается ли рукопожатие.

    verify=False по умолчанию: цель — факт хендшейка, а не валидность
    сертификата. Иначе ошибка сертификата маскируется под «поломку потока»
    и ломает классификацию (у WARP-endpoint'а свой cert).
    """
    sni = sni or host
    started = time.monotonic()
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            raw.settimeout(timeout)
            with ctx.wrap_socket(raw, server_hostname=sni):
                return ProbeResult(True, "ok", _ms(started))
    except Exception as exc:  # noqa: BLE001 — классифицируем всё
        kind, detail = classify(exc)
        return ProbeResult(False, kind, _ms(started), detail)


# -------------------------------------------------------------- HTTP ----
def probe_http(url, timeout=DEFAULT_TIMEOUT, expect=(200, 204, 301, 302, 403)):
    """HTTP(S)-проба: получен ли вообще ответ.

    Коды из `expect` считаются успехом: 403 у google/gstatic — нормальный
    ответ живого сервера, а не блокировка.
    """
    started = time.monotonic()
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "zapret-warp"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            code = resp.status
            ok = code in expect
            return ProbeResult(ok, "ok" if ok else f"http_{code}", _ms(started), f"HTTP {code}")
    except urllib.error.HTTPError as exc:
        ok = exc.code in expect
        return ProbeResult(
            ok, "ok" if ok else f"http_{exc.code}", _ms(started), f"HTTP {exc.code}"
        )
    except Exception as exc:  # noqa: BLE001
        kind, detail = classify(exc)
        return ProbeResult(False, kind, _ms(started), detail)


# --------------------------------------------------------------- DNS ----
def probe_dns(name="example.com", timeout=DEFAULT_TIMEOUT):
    """Проверка резолва (getaddrinfo не умеет timeout — раним в потоке)."""
    box = {}

    def work():
        try:
            box["addrs"] = socket.getaddrinfo(name, None)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    started = time.monotonic()
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return ProbeResult(False, "timeout", _ms(started), "резолв не уложился в таймаут")
    if "error" in box:
        kind, detail = classify(box["error"])
        return ProbeResult(False, kind, _ms(started), detail)
    addrs = box.get("addrs") or []
    return ProbeResult(bool(addrs), "ok" if addrs else "dns", _ms(started), f"{len(addrs)} адресов")


# ------------------------------------------------------------ target ----
@dataclass(frozen=True)
class Target:
    """Что проверяем. kind: tls | http | dns."""

    name: str
    target: str
    port: int = 443
    kind: str = "tls"
    verify: bool = False

    def probe(self, timeout=DEFAULT_TIMEOUT):
        if self.kind == "http":
            url = self.target if "://" in self.target else "https://" + self.target
            return probe_http(url, timeout=timeout)
        if self.kind == "dns":
            return probe_dns(self.target, timeout=timeout)
        return probe_tls(self.target, self.port, timeout=timeout, verify=self.verify)


# Цели по умолчанию для панели доступности.
# cloudflareclient.com — самый чувствительный индикатор: если он не открывается,
# туннель WARP не поднимется.
DEFAULT_TARGETS = (
    Target("Cloudflare WARP", "cloudflareclient.com", 443, "tls"),
    Target("YouTube", "www.youtube.com", 443, "tls"),
    Target("Telegram", "api.telegram.org", 443, "tls"),
    Target("Discord", "discord.com", 443, "tls"),
    Target("Google 204", "www.gstatic.com/generate_204", kind="http"),
    Target("DNS", "example.com", kind="dns"),
)


def probe_many(targets=DEFAULT_TARGETS, timeout=DEFAULT_TIMEOUT):
    """Прогнать набор целей последовательно: [ (target, result), ... ]."""
    return [(t, t.probe(timeout=timeout)) for t in targets]


# ------------------------------------------------------- Cloudflare -----
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"


def fetch_trace(timeout=DEFAULT_TIMEOUT):
    """https://www.cloudflare.com/cdn-cgi/trace → dict (ip, colo, warp, ...).

    Показывает, идёт ли трафик через туннель: при включённом WARP `warp=on`,
    а `ip` — адрес Cloudflare, а не провайдера.
    """
    started = time.monotonic()
    request = urllib.request.Request(TRACE_URL, headers={"User-Agent": "zapret-warp"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        kind, detail = classify(exc)
        return {"error": kind, "detail": detail, "rtt_ms": _ms(started)}
    info = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    info["rtt_ms"] = _ms(started)
    return info
