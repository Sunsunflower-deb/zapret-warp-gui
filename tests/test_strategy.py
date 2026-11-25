"""Тесты парсера стратегий: реальные .bat из репозитория, а не синтетика.

Каждый тест здесь соответствует конкретной правке P0 из плана (этап 1):
1.1 — плейсхолдер %Fooling%;
1.5 — мёртвые ipset-правила;
1.6 — GameFilter и «портовые» артефакты;
1.7 — артефакты .bat (service.bat, ~dp0bin\\, отдельный «-»).
"""
import os

import pytest

from core import paths, strategy

ALL = strategy.list_strategies()


def _arg(args, prefix):
    """Все значения аргументов с данным префиксом."""
    return [a[len(prefix):] for a in args if a.startswith(prefix)]


def test_strategies_found():
    assert ALL, "в strategies/ не найдено ни одного .bat"
    assert "warp_simple_fake.bat" in ALL


def test_no_case_collision():
    """Имена не должны различаться только регистром.

    Иначе на Windows (регистронезависимая ФС) git теряет одну из стратегий:
    было general_SIMPLE_FAKE.bat и general_simple_fake.bat — на диске
    оставался только один файл, и «вторая» стратегия молча ломалась.
    """
    lowered = [n.lower() for n in ALL]
    duplicates = {n for n in lowered if lowered.count(n) > 1}
    assert not duplicates, f"коллизия регистра в strategies/: {duplicates}"


@pytest.mark.parametrize("name", ALL)
def test_every_strategy_parses(name):
    p = strategy.parse(name, fooling="md5sig")
    assert p["all_args"], "пустой argv"
    assert p["wf_tcp"] or p["wf_udp"], "нет --wf-tcp/--wf-udp"
    joined = " ".join(p["all_args"])
    assert "%BIN%" not in joined and "%LISTS%" not in joined
    assert "%Fooling%" not in joined
    assert "%GameFilter" not in joined


@pytest.mark.parametrize("name", ALL)
def test_no_artifact_dash(name):
    """Отдельный токен «-» из апстримных .bat не должен доходить до winws."""
    p = strategy.parse(name, fooling="md5sig")
    assert "-" not in p["all_args"]


@pytest.mark.parametrize("name", ALL)
def test_fooling_is_substituted(name):
    """Все --dpi-desync-fooling должны получить значение из конфига.

    Литеральный `ts` в стратегиях — это и есть баг: он не работает на
    Windows. После подстановки в argv не должно остаться ни одного `ts`.
    Стратегии, где исторически стоит md5sig/badseq, не трогаем.
    """
    p = strategy.parse(name, fooling="badseq")
    values = _arg(p["all_args"], "--dpi-desync-fooling=")
    assert "ts" not in values, values
    assert all(v in ("badseq", "md5sig") for v in values), values


def test_default_fooling_depends_on_os(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert strategy.default_fooling() == "md5sig"
    monkeypatch.setattr(os, "name", "posix")
    assert "ts" in strategy.default_fooling()


def test_resolve_fooling():
    assert strategy.resolve_fooling(None) == strategy.default_fooling()
    assert strategy.resolve_fooling("") == strategy.default_fooling()
    assert strategy.resolve_fooling("auto") == strategy.default_fooling()
    assert strategy.resolve_fooling("AUTO") == strategy.default_fooling()
    assert strategy.resolve_fooling("ts") == "ts"
    assert strategy.resolve_fooling(" md5sig,badseq ") == "md5sig,badseq"


# --- 1.6 GameFilter -------------------------------------------------------

def test_gamefilter_off_leaves_no_dead_port_rule():
    """Раньше на месте игрового правила оставался --filter-udp=12."""
    p = strategy.parse("general_simple_fake.bat", False, False, fooling="md5sig")
    args = p["all_args"]
    assert "--filter-udp=12" not in args
    assert not [a for a in args if a.startswith("--filter-udp=") and a.endswith("=12")]
    # ни одного пустого/мусорного фильтра
    for prefix in ("--filter-tcp=", "--filter-udp=", "--wf-tcp=", "--wf-udp="):
        assert all(v.strip() for v in _arg(args, prefix))


def test_gamefilter_on_adds_ports():
    p = strategy.parse("general_simple_fake.bat", True, True, fooling="md5sig")
    joined = " ".join(p["all_args"])
    assert strategy.GAME_FILTER_PORTS in joined


def test_gamefilter_tcp_only():
    p = strategy.parse("general_simple_fake.bat", True, False, fooling="md5sig")
    joined = " ".join(p["all_args"])
    assert strategy.GAME_FILTER_PORTS in joined


# --- 1.5 мёртвые ipset-правила -------------------------------------------

def test_dead_ipset_rules_removed():
    """ipset-all.txt пуст -> правила, где ipset был единственным скоупом, уходят."""
    p = strategy.parse("general_simple_fake.bat", False, False, fooling="md5sig")
    args = p["all_args"]
    assert not [a for a in args if "ipset-all" in a]
    # правило без hostlist-скоупа нельзя оставить без --ipset: оно задурило бы весь трафик
    assert "--filter-tcp=80,443,8443" not in args


def test_ipset_rule_kept_when_list_has_addresses(tmp_lists):
    (tmp_lists / "ipset-all.txt").write_text("104.16.0.0/12\n", encoding="utf-8")
    cmd = ('--filter-tcp=80,443,8443 --ipset="lists/ipset-all.txt" '
           "--dpi-desync=fake")
    out = strategy._prune_dead_ipset(cmd)
    assert "--ipset=" in out
    assert "--filter-tcp=80,443,8443" in out


def test_ipset_rule_dropped_when_only_comments(tmp_lists):
    (tmp_lists / "ipset-all.txt").write_text("# пусто\n\n", encoding="utf-8")
    cmd = '--filter-tcp=80,443,8443 --ipset="lists/ipset-all.txt" --dpi-desync=fake'
    assert strategy._prune_dead_ipset(cmd).strip() == ""


def test_ipset_kept_when_hostlist_scopes_rule(tmp_lists):
    (tmp_lists / "ipset-all.txt").write_text("", encoding="utf-8")
    cmd = ('--filter-tcp=443 --hostlist="lists/list-warp.txt" '
           '--ipset="lists/ipset-all.txt" --dpi-desync=fake')
    out = strategy._prune_dead_ipset(cmd)
    assert "--hostlist=" in out
    assert "--ipset=" not in out


def test_has_entries(tmp_path):
    empty = tmp_path / "e.txt"
    empty.write_text("", encoding="utf-8")
    assert strategy.has_entries(str(empty)) is False
    comments = tmp_path / "c.txt"
    comments.write_text("# hi\n\n", encoding="utf-8")
    assert strategy.has_entries(str(comments)) is False
    data = tmp_path / "d.txt"
    data.write_text("1.2.3.4\n", encoding="utf-8")
    assert strategy.has_entries(str(data)) is True
    assert strategy.has_entries(str(tmp_path / "missing.txt")) is False


# --- 1.1/1.3/1.4 WARP-стратегия ------------------------------------------

def test_warp_strategy_masking_params():
    """Параметры маскировки: без статического фейка «как есть», без 8 повторов."""
    p = strategy.parse("warp_simple_fake.bat", fooling="md5sig")
    args = p["all_args"]
    assert "--dpi-desync-repeats=8" not in args
    assert "--dpi-desync-repeats=2" in args
    assert "--dpi-desync-fake-tls-mod=rnd,dupsid" in args
    assert "--dpi-desync-cutoff=n4" in args
    assert "--dpi-desync-autottl" in args
    assert "--dpi-desync-fooling=md5sig" in args
    assert "--hostlist=lists/list-warp.txt" in args


def test_warp_strategy_splits_early():
    """Разрез в 1-м байте — измеренный рабочий вариант (docs/measurements.md).

    На сети с SNI-блокировкой, которая не собирает поток:
      разрез 1-3 байта -> 8/8, без разреза -> 0/8, разрез >=10 -> 0/8.
    Поэтому первый сегмент не должен быть распознаваем как TLS.
    """
    p = strategy.parse("warp_simple_fake.bat", fooling="md5sig")
    args = p["all_args"]
    assert "--dpi-desync-split-pos=1" in args
    modes = [a for a in args if a.startswith("--dpi-desync=")]
    assert any("multisplit" in m for m in modes), modes


def test_warp_strategy_scoped_to_tunnel_hosts():
    """В WARP-стратегии все hostlist ссылаются только на list-warp."""
    p = strategy.parse("warp_simple_fake.bat", fooling="md5sig")
    hostlists = set(_arg(p["all_args"], "--hostlist="))
    assert hostlists == {"lists/list-warp.txt"}


def test_list_warp_is_narrow():
    """В WARP-хостлисте не должно быть широкого cloudflare.com."""
    path = os.path.join(paths.LISTS_DIR, "list-warp.txt")
    with open(path, encoding="utf-8") as fh:
        hosts = [ln.strip() for ln in fh if ln.strip()]
    assert "cloudflareclient.com" in hosts
    assert "cloudflare.com" not in hosts


# --- ошибки ---------------------------------------------------------------

def test_parse_missing_strategy():
    with pytest.raises(FileNotFoundError):
        strategy.parse("no_such_strategy.bat")


def test_parse_file_without_winws(tmp_path):
    bad = tmp_path / "bad.bat"
    bad.write_text("@echo off\necho nothing\n", encoding="utf-8")
    with pytest.raises(ValueError):
        strategy.parse_file(str(bad))


def test_parse_file_quotes_are_stripped(tmp_path):
    bat = tmp_path / "s.bat"
    bat.write_text(
        'start "x" /min "%BIN%winws.exe" --wf-tcp=443 '
        '--filter-tcp=443 --hostlist="%LISTS%list-warp.txt"',
        encoding="utf-8",
    )
    p = strategy.parse_file(str(bat), fooling="md5sig")
    assert "--hostlist=lists/list-warp.txt" in p["all_args"]
    assert p["wf_tcp"] == "443"

def test_list_strategies_hides_tuner_temp_files(tmp_path, monkeypatch):
    """Временные файлы автоподбора не должны попадать в список стратегий."""
    (tmp_path / "visible.bat").write_text("@echo off\n", encoding="utf-8")
    (tmp_path / ".tune-hidden__md5sig.bat").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(paths, "STRATEGIES_DIR", str(tmp_path))
    names = strategy.list_strategies()
    assert "visible.bat" in names
    assert all(not n.startswith(".") for n in names)
