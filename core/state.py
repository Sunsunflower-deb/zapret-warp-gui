"""Единое состояние приложения: один источник правды для GUI, CLI и watchdog.

Раньше каждый потребитель сам дёргал `tasklist`, `warp-cli status` и проверял
подстроки. Отсюда расхождения («процесс жив, а туннель нет») и мигание консоли.
Теперь состояние собирается в одном месте, а потребители его только читают.
"""
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import config, engine, probe, strategy, warp


@dataclass(frozen=True)
class Reachability:
    """Одна проверка доступности."""

    name: str
    ok: bool
    kind: str
    rtt_ms: float

    def __str__(self):
        mark = "OK" if self.ok else "!!"
        return f"{self.name}: [{mark}] {self.kind} {self.rtt_ms:.0f} мс"


@dataclass(frozen=True)
class AppState:
    """Снимок состояния. Иммутабельный, чтобы его можно было безопасно
    передавать между потоками."""

    engine_running: bool = False
    engine_pid: Optional[int] = None
    strategy: str = ""
    fooling: str = ""
    warp_enabled: bool = True
    warp_state: warp.WarpState = warp.WarpState.UNKNOWN
    warp_line: str = ""
    exit_ip: str = ""
    warp_flag: str = ""
    colo: str = ""
    reachability: tuple = field(default_factory=tuple)
    last_error: str = ""
    updated_at: float = 0.0

    @property
    def warp_connected(self):
        return self.warp_state is warp.WarpState.CONNECTED

    @property
    def healthy(self):
        """Десинк работает, нужный туннель подключён и хотя бы часть проб проходит."""
        if not self.engine_running:
            return False
        if self.warp_enabled and not self.warp_connected:
            return False
        if not self.reachability:
            return True
        return sum(1 for r in self.reachability if r.ok) >= len(self.reachability) / 2

    @property
    def leaks(self):
        """Пробы, которые выглядят как «фейк дошёл до сервера»."""
        return [r for r in self.reachability if r.kind == "reset" or r.kind.startswith("tls_")]

    def summary_lines(self):
        """Короткий человекочитаемый отчёт (для CLI и лога)."""
        lines = [
            "DPI-десинк: " + ("запущен" if self.engine_running else "остановлен")
            + (f" (pid {self.engine_pid})" if self.engine_pid else ""),
            "Стратегия:  " + (self.strategy or "—") + " | fooling: " + (self.fooling or "—"),
            "WARP:       " + self.warp_state.value + (f" ({self.warp_line})" if self.warp_line else ""),
        ]
        if self.exit_ip:
            extra = " | ".join(
                x for x in (
                    "colo " + self.colo if self.colo else "",
                    "warp=" + self.warp_flag if self.warp_flag else "",
                ) if x
            )
            lines.append("Выходной IP: " + self.exit_ip + (f"  ({extra})" if extra else ""))
        if self.reachability:
            lines.append("Доступность:")
            for item in self.reachability:
                lines.append("  " + str(item))
        if self.last_error:
            lines.append("Ошибка: " + self.last_error)
        return lines


def collect(cfg=None, targets=None, do_probe=True, timeout=probe.DEFAULT_TIMEOUT):
    """Собрать текущее состояние (без потоков — вызывающий сам решает, где)."""
    cfg = cfg or config.load()
    fooling = strategy.resolve_fooling(cfg.get("fooling"))
    state = AppState(
        engine_running=engine.is_running(),
        engine_pid=engine.desync_pid(),
        strategy=str(cfg.get("strategy") or ""),
        fooling=fooling,
        updated_at=time.time(),
    )
    errors = []

    if warp.installed():
        try:
            warp_state, warp_line = warp.state(cfg)
        except Exception as exc:  # noqa: BLE001
            warp_state, warp_line = warp.WarpState.UNKNOWN, str(exc)
            errors.append("warp status: " + str(exc))
    else:
        warp_state, warp_line = warp.WarpState.UNKNOWN, "warp-cli не установлен"

    reach = ()
    exit_ip = warp_flag = colo = ""
    if do_probe:
        results = []
        for target, result in probe.probe_many(targets or probe.DEFAULT_TARGETS, timeout=timeout):
            results.append(Reachability(target.name, result.ok, result.kind, result.rtt_ms))
        reach = tuple(results)
        trace = probe.fetch_trace(timeout=timeout)
        if "error" in trace:
            errors.append("trace: " + str(trace.get("error")) + " " + str(trace.get("detail", "")))
        else:
            exit_ip = trace.get("ip", "")
            warp_flag = trace.get("warp", "")
            colo = trace.get("colo", "")

    return AppState(
        engine_running=state.engine_running,
        engine_pid=state.engine_pid,
        strategy=state.strategy,
        fooling=state.fooling,
        warp_enabled=bool(cfg.get("warp_enabled", True)),
        warp_state=warp_state,
        warp_line=warp_line,
        exit_ip=exit_ip,
        warp_flag=warp_flag,
        colo=colo,
        reachability=reach,
        last_error="; ".join(x for x in errors if x),
        updated_at=state.updated_at,
    )


class Monitor:
    """Фоновый поток: периодически собирает AppState и кладёт в очередь.

    Очередь всегда содержит только последнее состояние — GUI не должен
    разгребать накопившиеся устаревшие снимки.
    """

    def __init__(self, collector=None, interval=30.0):
        self._collector = collector or collect
        self._interval = max(1.0, float(interval))
        self._stop = threading.Event()
        self._thread = None
        self.queue = queue.Queue(maxsize=1)
        self._last = None

    @property
    def last(self):
        return self._last

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="zapret-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout=5.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._thread = None

    def tick(self):
        """Собрать состояние один раз (используется тестами и CLI)."""
        try:
            state = self._collector()
        except Exception as exc:  # noqa: BLE001 — поток не должен умирать
            state = AppState(last_error=str(exc), updated_at=time.time())
        self._last = state
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(state)
        except queue.Full:
            pass
        return state

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)
