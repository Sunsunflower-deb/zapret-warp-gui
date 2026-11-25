"""Тесты проб: классификация ошибок — ядро автотюнинга и watchdog."""
import socket
import ssl
import urllib.error

from core import probe

# --- классификация --------------------------------------------------------

def test_classify_timeout():
    assert probe.classify(socket.timeout())[0] == "timeout"
    assert probe.classify(TimeoutError())[0] == "timeout"


def test_classify_reset_and_refused():
    assert probe.classify(ConnectionResetError())[0] == "reset"
    assert probe.classify(ConnectionRefusedError())[0] == "refused"


def test_classify_dns():
    assert probe.classify(socket.gaierror("nope"))[0] == "dns"


def test_classify_tls_alert():
    exc = ssl.SSLError(1, "handshake failure")
    kind, _ = probe.classify(exc)
    assert kind.startswith("tls_")


def test_classify_unknown_oserror():
    kind, _ = probe.classify(OSError(10050, "network down"))
    assert kind.startswith("os_")


def test_leak_detection():
    assert probe.ProbeResult(False, "tls_alert", 1.0).looks_like_leak is True
    assert probe.ProbeResult(False, "reset", 1.0).looks_like_leak is True
    assert probe.ProbeResult(False, "timeout", 1.0).looks_like_leak is False
    assert probe.ProbeResult(True, "ok", 1.0).looks_like_leak is False


# --- TLS-проба ------------------------------------------------------------

def test_probe_tls_ok(monkeypatch):
    class FakeCtx:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw, server_hostname=None):
            assert server_hostname == "example.com"
            return raw

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

    monkeypatch.setattr(ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: FakeSock())
    result = probe.probe_tls("example.com")
    assert result.ok and result.kind == "ok"
    assert result.rtt_ms >= 0


def test_probe_tls_verify_off_by_default(monkeypatch):
    seen = {}

    class FakeCtx:
        def __init__(self):
            self.check_hostname = True
            self.verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw, server_hostname=None):
            seen["check_hostname"] = self.check_hostname
            seen["verify_mode"] = self.verify_mode
            return raw

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

    monkeypatch.setattr(ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: FakeSock())
    probe.probe_tls("example.com")
    assert seen["verify_mode"] == ssl.CERT_NONE
    assert seen["check_hostname"] is False


def test_probe_tls_timeout(monkeypatch):
    def boom(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(socket, "create_connection", boom)
    result = probe.probe_tls("example.com", timeout=0.01)
    assert result.ok is False and result.kind == "timeout"


def test_probe_tls_custom_sni(monkeypatch):
    captured = {}

    class FakeCtx:
        def wrap_socket(self, raw, server_hostname=None):
            captured["sni"] = server_hostname
            return raw

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

    monkeypatch.setattr(ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: FakeSock())
    probe.probe_tls("1.2.3.4", sni="cloudflareclient.com")
    assert captured["sni"] == "cloudflareclient.com"


# --- HTTP-проба -----------------------------------------------------------

def test_probe_http_ok(monkeypatch):
    class FakeResp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
    result = probe.probe_http("https://www.gstatic.com/generate_204")
    assert result.ok and result.kind == "ok"


def test_probe_http_403_is_success(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    result = probe.probe_http("https://example.com", expect=(200, 403))
    assert result.ok


def test_probe_http_unexpected_code(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 500, "Server Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    result = probe.probe_http("https://example.com", expect=(200,))
    assert result.ok is False
    assert result.kind == "http_500"


# --- DNS и Target ---------------------------------------------------------

def test_probe_dns_ok(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("1.2.3.4", 0))])
    result = probe.probe_dns("example.com")
    assert result.ok and result.kind == "ok"


def test_probe_dns_failure(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("no")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    result = probe.probe_dns("bad.invalid")
    assert result.ok is False and result.kind == "dns"


def test_target_dispatch(monkeypatch):
    calls = []

    monkeypatch.setattr(probe, "probe_tls",
                        lambda host, port=443, timeout=5.0, verify=False:
                        calls.append(("tls", host)) or probe.ProbeResult(True, "ok", 1.0))
    monkeypatch.setattr(probe, "probe_http",
                        lambda url, timeout=5.0:
                        calls.append(("http", url)) or probe.ProbeResult(True, "ok", 1.0))
    monkeypatch.setattr(probe, "probe_dns",
                        lambda name, timeout=5.0:
                        calls.append(("dns", name)) or probe.ProbeResult(True, "ok", 1.0))

    probe.Target("a", "example.com", 443, "tls").probe()
    probe.Target("b", "example.com/gen_204", kind="http").probe()
    probe.Target("c", "example.com", kind="dns").probe()
    assert [c[0] for c in calls] == ["tls", "http", "dns"]
    assert calls[1][1] == "https://example.com/gen_204"


def test_probe_many_preserves_order(monkeypatch):
    monkeypatch.setattr(probe.Target, "probe",
                        lambda self, timeout=5.0: probe.ProbeResult(True, "ok", 1.0))
    results = probe.probe_many()
    assert [t.name for t, _ in results] == [t.name for t in probe.DEFAULT_TARGETS]


# --- trace ----------------------------------------------------------------

def test_fetch_trace_parses(monkeypatch):
    body = b"fl=abc\nip=104.28.1.2\nts=1\ncolo=FRA\nwarp=on\n"

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
    info = probe.fetch_trace()
    assert info["ip"] == "104.28.1.2"
    assert info["colo"] == "FRA"
    assert info["warp"] == "on"
    assert "rtt_ms" in info


def test_fetch_trace_error(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(socket.timeout()))
    info = probe.fetch_trace()
    assert info["error"] == "timeout"


# --- URLError: настоящая причина внутри .reason ---------------------------

def test_classify_unwraps_urlerror():
    """Регресс: без разворота .reason всё превращалось в os_URLError.

    Именно так Google 204 в живом прогоне показывал `os_URLError` вместо
    реальной причины, и автоподбор не смог бы отличить timeout от TLS alert.
    """
    wrapped = urllib.error.URLError(socket.timeout("timed out"))
    assert probe.classify(wrapped)[0] == "timeout"

    wrapped_tls = urllib.error.URLError(ssl.SSLError(1, "handshake failure"))
    assert probe.classify(wrapped_tls)[0].startswith("tls_")

    wrapped_dns = urllib.error.URLError(socket.gaierror("no host"))
    assert probe.classify(wrapped_dns)[0] == "dns"


def test_classify_urlerror_without_exception_reason():
    exc = urllib.error.URLError("просто строка")
    assert probe.classify(exc)[0] == "os_URLError"


def test_probe_http_timeout_is_timeout(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    result = probe.probe_http("https://www.gstatic.com/generate_204")
    assert result.ok is False
    assert result.kind == "timeout"
