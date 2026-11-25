"""Тесты автоподбора: кандидаты, оценка, прогон с внедрёнными зависимостями.

Сеть, winws и права администратора не нужны: перезапуск движка, пробы и часы
подменяются параметрами.
"""
import os

import pytest

from core import config, probe, strategy, tuner


def _ok(rtt=20.0):
    return probe.ProbeResult(True, "ok", rtt)


def _timeout():
    return probe.ProbeResult(False, "timeout", 5000.0)


def _leak():
    return probe.ProbeResult(False, "tls_handshake_failure", 300.0)


# --- кандидаты ------------------------------------------------------------

def test_candidates_are_unique_and_numerous():
    candidates = tuner.build_candidates()
    ids = [c.id for c in candidates]
    assert len(ids) == len(set(ids))
    assert len(candidates) >= 12
    assert any(c.id.startswith("hostfakesplit") for c in candidates)


def test_technique_without_fooling_has_single_variant():
    candidates = tuner.build_candidates()
    multi = [c for c in candidates if c.technique.id == "multidisorder"]
    assert len(multi) == 1
    assert multi[0].fooling == "none"


@pytest.mark.parametrize("candidate", tuner.build_candidates(),
                         ids=lambda c: c.id)
def test_candidate_bat_is_parseable(candidate, tmp_path):
    """Кандидат должен проходить тот же парсер, что и штатные стратегии."""
    parsed = strategy.parse_file(
        tuner.materialize(candidate, str(tmp_path)), fooling=candidate.fooling)
    joined = " ".join(parsed["all_args"])
    assert "%BIN%" not in joined and "%LISTS%" not in joined
    assert "%Fooling%" not in joined and "%GameFilter" not in joined
    assert "-" not in parsed["all_args"]
    assert parsed["wf_tcp"]
    assert "--hostlist=lists/list-warp.txt" in parsed["all_args"]


def test_candidate_fooling_is_applied(tmp_path):
    candidate = [c for c in tuner.build_candidates() if c.id == "fake-r1__badseq"][0]
    parsed = strategy.parse_file(
        tuner.materialize(candidate, str(tmp_path)), fooling=candidate.fooling)
    assert "--dpi-desync-fooling=badseq" in parsed["all_args"]


def test_parsed_removes_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tuner.paths, "APP_DIR", str(tmp_path))
    candidate = tuner.build_candidates()[0]
    tuner.parsed(candidate, str(tmp_path))
    leftovers = [f for f in os.listdir(tmp_path) if f.startswith(".tune-")]
    assert leftovers == []


def test_bat_text_is_crlf():
    text = tuner.bat_text(tuner.build_candidates()[0])
    assert "\r\n" in text and "winws.exe" in text


def test_argv_line_has_both_rules():
    line = tuner.argv_line(tuner.build_candidates()[0])
    assert "--wf-tcp=" in line and "--wf-udp=443" in line
    assert "--new" in line
    assert "list-warp.txt" in line


# --- оценка ---------------------------------------------------------------

def test_score_all_ok():
    value, ok_rate, leak_rate, rtt = tuner.score_results([_ok(10), _ok(10)])
    assert ok_rate == 1.0 and leak_rate == 0.0
    assert rtt == 10
    assert value > 90


def test_score_empty():
    assert tuner.score_results([]) == (0.0, 0.0, 0.0, 0.0)


def test_score_penalises_leaks_harder_than_timeout():
    score_leak, _, leak_rate, _ = tuner.score_results([_leak(), _leak()])
    score_timeout, _, _, _ = tuner.score_results([_timeout(), _timeout()])
    assert leak_rate == 1.0
    assert score_leak < score_timeout


def test_score_rtt_penalty_is_capped():
    _, _, _, _ = tuner.score_results([_ok(100000)])
    slow, _, _, _ = tuner.score_results([_ok(100000)])
    assert slow >= 60  # 100 - cap(40)


def test_rank_prefers_clean_over_leaky():
    candidate = tuner.build_candidates()[0]
    leaky = tuner.CandidateResult(candidate, (_ok(),), 110.0, 1.0, 0.4, 10.0)
    clean = tuner.CandidateResult(candidate, (_ok(),), 90.0, 0.9, 0.0, 20.0)
    assert max([leaky, clean], key=tuner._rank) is clean


# --- прогон ---------------------------------------------------------------

def test_evaluate_counts_calls():
    calls = {"prepare": 0, "probe": 0}

    def prepare(candidate):
        calls["prepare"] += 1

    def probe_fn(target, timeout):
        calls["probe"] += 1
        return _ok()

    result = tuner.evaluate(tuner.build_candidates()[0], prepare=prepare,
                            probe_fn=probe_fn, attempts=3)
    assert calls["prepare"] == 1
    assert calls["probe"] == 3 * len(tuner.TUNE_TARGETS)
    assert result.ok_rate == 1.0
    assert result.candidate.id


def test_evaluate_handles_prepare_failure():
    def prepare(candidate):
        raise RuntimeError("winws.exe завершился с кодом 1")

    result = tuner.evaluate(tuner.build_candidates()[0], prepare=prepare,
                            probe_fn=lambda t, to: _ok())
    assert result.score < 0
    assert "кодом 1" in result.error
    assert result.ok is False


def test_evaluate_handles_probe_exception():
    result = tuner.evaluate(
        tuner.build_candidates()[0], prepare=lambda c: None,
        probe_fn=lambda t, to: (_ for _ in ()).throw(RuntimeError("сеть упала")))
    assert "сеть упала" in result.error


def test_evaluate_result_line():
    result = tuner.evaluate(tuner.build_candidates()[0],
                            prepare=lambda c: None,
                            probe_fn=lambda t, to: _ok())
    line = result.line()
    assert result.candidate.id in line
    assert "score=" in line


def test_tune_picks_working_candidate():
    current = {}

    def prepare(candidate):
        current["c"] = candidate

    def probe_fn(target, timeout):
        if "hostfakesplit" in current["c"].id:
            return _ok(30.0)
        return _timeout()

    result = tuner.tune(prepare=prepare, probe_fn=probe_fn, attempts=1)
    assert result.best is not None
    assert result.best.candidate.id.startswith("hostfakesplit")
    assert len(result.worked) >= 1
    assert result.stopped_by_budget is False


def test_tune_reports_no_winner():
    result = tuner.tune(candidates=tuner.build_candidates()[:3],
                        prepare=lambda c: None,
                        probe_fn=lambda t, to: _timeout(), attempts=1)
    assert result.best is not None
    assert result.best.ok is False
    assert result.worked == []


def test_tune_respects_budget():
    state = {"t": 0.0}

    def clock():
        return state["t"]

    def prepare(candidate):
        state["t"] += 100.0  # каждый кандидат «съедает» 100 секунд

    result = tuner.tune(clock=clock, budget=50.0, prepare=prepare,
                        probe_fn=lambda t, to: _ok(), attempts=1,
                        candidates=tuner.build_candidates()[:5])
    assert result.stopped_by_budget is True
    assert len(result.results) == 1


def test_tune_progress_callback():
    seen = []
    tuner.tune(candidates=tuner.build_candidates()[:2],
               prepare=lambda c: None, probe_fn=lambda t, to: _ok(),
               attempts=1, progress=seen.append)
    assert len(seen) == 2


# --- экспорт --------------------------------------------------------------

def test_export_writes_parseable_strategy(tmp_path):
    candidate = [c for c in tuner.build_candidates() if c.id == "hostfakesplit__md5sig"][0]
    path = tuner.export(candidate, str(tmp_path))
    assert os.path.isfile(path)
    assert os.path.basename(path) == tuner.TUNED_NAME
    parsed = strategy.parse_file(path, fooling="md5sig")
    assert "hostfakesplit" in " ".join(parsed["all_args"])


def test_apply_sets_config(tmp_path, config_path):
    candidate = tuner.build_candidates()[0]
    path = tuner.apply(candidate, cfg={"strategy": "warp_simple_fake.bat"},
                       directory=str(tmp_path))
    assert os.path.isfile(path)
    cfg = config.load()
    assert cfg["strategy"] == tuner.TUNED_NAME
    assert cfg["fooling"] == candidate.fooling
