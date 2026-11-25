"""Автоподбор стратегии десинка: перебрать кандидатов и выбрать рабочего.

Зачем: в репозитории 24 `.bat`, и пользователь не знает, какой из них «его».
В zapret для этого есть `blockcheck.sh`, в GUI не было ничего — приходилось
перебирать вручную и смотреть, «стало лучше или нет».

Схема (этап 6 плана):

1. Сгенерировать кандидатов: техника × fooling (см. `TECHNIQUES`).
2. Для каждого: перезапустить десинк, дать прогреться, прогнать пробы по целям.
3. Оценить: доля успеха, медиана RTT и **утечки** (`reset`/`tls_*` — фейк дошёл
   до сервера). Утечки штрафуются сильнее, чем медленная, но рабочая техника.
4. Оставить лучшего, экспортировать в `strategies/tuned.bat` и запомнить в конфиге.

Зависимости (перезапуск движка, пробы, часы) передаются параметрами, поэтому
логика проверяется без сети, без winws и без прав администратора.
"""
import os
import statistics
import time
from dataclasses import dataclass
from typing import Optional

from . import config, engine, paths, probe, strategy
from .logs import get as _log_get

# Порты, которые реально использует WARP: 443 (h2) + альтернативные TLS-порты.
WARP_TCP_PORTS = "443,2053,2083,2087,2096,8443"

_TCP_FILTER = (
    '--filter-tcp=' + WARP_TCP_PORTS + ' --hostlist="%LISTS%list-warp.txt"'
)
# UDP-правило одинаковое во всех кандидатах: h3/QUIC-обфускация не зависит от
# выбранной TCP-техники.
_UDP_RULE = (
    '--filter-udp=443 --hostlist="%LISTS%list-warp.txt" --dpi-desync=fake '
    '--dpi-desync-repeats=2 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" '
    '--dpi-desync-any-protocol=1'
)

DEFAULT_FOOLINGS = ("md5sig", "md5sig,badseq", "badseq")
DEFAULT_ATTEMPTS = 2
DEFAULT_TIMEOUT = 5.0
DEFAULT_WARMUP = 2.0
DEFAULT_BUDGET = 180.0

# Цели для подбора: ровно то, что должно открываться через туннель.
TUNE_TARGETS = (
    probe.Target("Cloudflare WARP", "cloudflareclient.com", 443, "tls"),
    probe.Target("YouTube", "www.youtube.com", 443, "tls"),
)


@dataclass(frozen=True)
class Technique:
    """Техника десинка: то, что подставляется в TCP-правило."""

    id: str
    label: str
    tcp_args: str
    uses_fooling: bool = True
    uses_fakes: bool = True


TECHNIQUES = (
    Technique(
        "fake-rnd",
        "fake + рандомизация фейка, 2 повтора, autottl",
        '--dpi-desync=fake --dpi-desync-repeats=2 --dpi-desync-fooling=%Fooling% '
        '--dpi-desync-autottl --dpi-desync-cutoff=n4 '
        '--dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" '
        "--dpi-desync-fake-tls-mod=rnd,dupsid",
    ),
    Technique(
        "fake-r1",
        "fake + рандомизация фейка, 1 повтор",
        '--dpi-desync=fake --dpi-desync-repeats=1 --dpi-desync-fooling=%Fooling% '
        '--dpi-desync-cutoff=n4 '
        '--dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" '
        "--dpi-desync-fake-tls-mod=rnd,dupsid",
    ),
    Technique(
        "fake-multisplit",
        "fake + multisplit по середине домена 2-го уровня",
        '--dpi-desync=fake,multisplit --dpi-desync-split-pos=midsld '
        '--dpi-desync-repeats=2 --dpi-desync-fooling=%Fooling% --dpi-desync-cutoff=n4 '
        '--dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" '
        "--dpi-desync-fake-tls-mod=rnd,dupsid",
    ),
    Technique(
        "hostfakesplit",
        "hostfakesplit altorder=1 (подмена SNI при сборке на DPI)",
        "--dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=altorder=1 "
        "--dpi-desync-hostfakesplit-midhost=midsld "
        "--dpi-desync-fooling=%Fooling% --dpi-desync-cutoff=n4",
    ),
    Technique(
        "multidisorder",
        "multidisorder по полю SNI (без фейков)",
        "--dpi-desync=multidisorder --dpi-desync-split-pos=sniext+1,endhost-2 "
        "--dpi-desync-cutoff=n4",
        uses_fooling=False,
        uses_fakes=False,
    ),
    Technique(
        "fakedsplit",
        "fakedsplit altorder=3 (минимум фейков)",
        "--dpi-desync=fakedsplit --dpi-desync-fakedsplit-mod=altorder=3 "
        "--dpi-desync-split-pos=midsld --dpi-desync-repeats=1 "
        "--dpi-desync-fooling=%Fooling% --dpi-desync-cutoff=n4",
    ),
)


@dataclass(frozen=True)
class Candidate:
    """Кандидат = техника + значение fooling."""

    id: str
    technique: Technique
    fooling: str

    @property
    def label(self):
        if self.technique.uses_fooling:
            return f"{self.technique.label} · fooling={self.fooling}"
        return self.technique.label


def build_candidates(foolings=DEFAULT_FOOLINGS):
    """Сгенерировать список кандидатов (техника × fooling)."""
    out = []
    for technique in TECHNIQUES:
        values = foolings if technique.uses_fooling else ("none",)
        for fooling in values:
            out.append(Candidate(
                id=f"{technique.id}__{fooling.replace(',', '+')}",
                technique=technique,
                fooling=fooling,
            ))
    return tuple(out)


def argv_line(candidate):
    """Строка аргументов winws/nfqws для кандидата (без плейсхолдеров путей)."""
    return (
        f"--wf-tcp={WARP_TCP_PORTS} --wf-udp=443 "
        f"{_TCP_FILTER} {candidate.technique.tcp_args} --new {_UDP_RULE}"
    )


def bat_text(candidate):
    """Полный текст .bat — такой же, как штатные стратегии."""
    header = (
        "@echo off\r\n"
        ":: сгенерировано автоподбором zapret-warp (cli.py tune)\r\n"
        f":: {candidate.label}\r\n"
        "set \"BIN=%~dp0..\\bin\\\"\r\n"
        "set \"LISTS=%~dp0..\\lists\\\"\r\n"
        "if not defined Fooling set \"Fooling=md5sig\"\r\n"
        "cd /d \"%BIN%\"\r\n\r\n"
    )
    return header + f'start "zapret-warp" /min "%BIN%winws.exe" {argv_line(candidate)}\r\n'


def materialize(candidate, directory=None):
    """Записать кандидата во временный .bat и вернуть путь.

    Через файл, а не «argv напрямую», чтобы использовался тот же парсер, что и
    для штатных стратегий — иначе подбор проверял бы не то, что потом запустится.
    """
    directory = directory or os.path.join(paths.APP_DIR, "strategies")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f".tune-{candidate.id}.bat")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(bat_text(candidate))
    return path


def parsed(candidate, directory=None):
    """Разобранная стратегия кандидата (argv + fooling) — до запуска."""
    path = materialize(candidate, directory)
    try:
        return strategy.parse_file(path, fooling=candidate.fooling)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------------ оценка --
@dataclass(frozen=True)
class CandidateResult:
    candidate: Candidate
    results: tuple
    score: float
    ok_rate: float
    leak_rate: float
    median_rtt: float
    error: str = ""

    @property
    def ok(self):
        return self.ok_rate > 0 and not self.error

    def line(self):
        marks = "".join("+" if r.ok else "-" for r in self.results)
        leak = f" утечек {round(self.leak_rate * 100)}%" if self.leak_rate else ""
        rtt = f" {self.median_rtt:.0f} мс" if self.median_rtt else ""
        err = f" ошибка: {self.error}" if self.error else ""
        return (f"{self.candidate.id:<34} {marks:<8} score={self.score:6.1f}"
                f"{rtt}{leak}{err}")


def score_results(results):
    """Оценка набора проб: успех важнее скорости, утечка хуже таймаута.

    Утечка (`reset`/`tls_*`) означает, что подделка дошла до сервера и испортила
    поток: такая стратегия не «просто медленная», она ломает соединение.
    """
    if not results:
        return 0.0, 0.0, 0.0, 0.0
    total = len(results)
    ok_rate = sum(1 for r in results if r.ok) / total
    leak_rate = sum(1 for r in results if _is_leak(r)) / total
    rtts = [r.rtt_ms for r in results if r.ok]
    median_rtt = statistics.median(rtts) if rtts else 0.0
    rtt_penalty = min(40.0, median_rtt / 50.0)
    value = round(100.0 * ok_rate - 60.0 * leak_rate - rtt_penalty, 2)
    return value, ok_rate, leak_rate, median_rtt


def _is_leak(result):
    if hasattr(result, "looks_like_leak"):
        return bool(result.looks_like_leak)
    kind = getattr(result, "kind", "")
    return kind == "reset" or str(kind).startswith("tls_")


# ------------------------------------------------------------------ прогон --
def _real_prepare(candidate, warmup):
    """Перезапустить десинк на кандидате (нужны права администратора/root)."""
    engine.stop()
    parsed_strategy = parsed(candidate)
    engine.start_parsed(parsed_strategy)
    time.sleep(warmup)


def _real_probe(target, timeout):
    return target.probe(timeout=timeout)


def evaluate(candidate, *, prepare=None, probe_fn=None, targets=None, attempts=1,
             timeout=DEFAULT_TIMEOUT, warmup=DEFAULT_WARMUP):
    """Прогнать одного кандидата: перезапуск + attempts × пробы по целям."""
    prepare = prepare or (lambda cand: _real_prepare(cand, warmup))
    probe_fn = probe_fn or _real_probe
    targets = targets or TUNE_TARGETS
    results = []
    error = ""
    try:
        prepare(candidate)
    except Exception as exc:  # noqa: BLE001 — кандидат мог не запуститься
        return CandidateResult(candidate, (), -1000.0, 0.0, 0.0, 0.0, str(exc))
    for _ in range(max(1, attempts)):
        for target in targets:
            try:
                results.append(probe_fn(target, timeout))
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
    value, ok_rate, leak_rate, median_rtt = score_results(results)
    return CandidateResult(candidate, tuple(results), value, ok_rate, leak_rate,
                           median_rtt, error)


@dataclass(frozen=True)
class TuneResult:
    best: Optional[CandidateResult]
    results: tuple
    elapsed: float
    stopped_by_budget: bool = False

    @property
    def worked(self):
        return [r for r in self.results if r.ok]


def tune(*, candidates=None, attempts=DEFAULT_ATTEMPTS, timeout=DEFAULT_TIMEOUT,
         warmup=DEFAULT_WARMUP, budget=DEFAULT_BUDGET, prepare=None, probe_fn=None,
         targets=None, clock=time.monotonic, progress=None):
    """Перебрать кандидатов и вернуть лучшего.

    progress(result) вызывается после каждого кандидата (для CLI/GUI).
    По исчерпании budget перебор останавливается: пользователь ждёт, а не
    смотрит на прогресс-бар десять минут.
    """
    log = _log_get("tuner")
    candidates = tuple(candidates or build_candidates())
    started = clock()
    results = []
    stopped = False
    for candidate in candidates:
        if budget and (clock() - started) > budget:
            stopped = True
            log.warning("бюджет времени исчерпан: проверено %s из %s",
                        len(results), len(candidates))
            break
        result = evaluate(candidate, prepare=prepare, probe_fn=probe_fn,
                          targets=targets, attempts=attempts, timeout=timeout,
                          warmup=warmup)
        results.append(result)
        log.info("кандидат %s: score=%.1f", candidate.id, result.score)
        if progress:
            progress(result)
    best = max(results, key=_rank) if results else None
    return TuneResult(best, tuple(results), round(clock() - started, 1), stopped)


def _rank(result):
    """Ключ сортировки: сначала без утечек, потом выше score, потом выше успех.

    Два подводных камня, на которых уже спотыкались (см. тесты):
    * `max()` сравнивает кортежи, поэтому score возвращается как есть, а не
      `-score`, иначе лучшим оказывается самый плохой кандидат;
    * флаг утечек должен быть 1 для чистого и 0 для «текущего», иначе
      max() выбирает именно утекающего.
    """
    return (1 if result.leak_rate == 0 else 0, result.score, result.ok_rate)


# ---------------------------------------------------------------- экспорт --
TUNED_NAME = "tuned.bat"


def export(candidate, directory=None):
    """Записать кандидата как обычную стратегию `tuned.bat`."""
    directory = directory or os.path.join(paths.APP_DIR, "strategies")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, TUNED_NAME)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(bat_text(candidate))
    return path


def apply(candidate, cfg=None, directory=None):
    """Экспортировать победителя и выбрать его стратегией в конфиге."""
    path = export(candidate, directory)
    cfg = dict(cfg or config.load())
    cfg["strategy"] = os.path.basename(path)
    cfg["fooling"] = candidate.fooling
    config.save(cfg)
    return path
