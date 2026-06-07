import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sector_selector import parse_deepseek_response


def test_parse_deepseek_normal():
    raw = '{"picks":[{"code":"002812","name":"Enjie","reason":"PVDF leader"},{"code":"002407","name":"Dofluoride","reason":"LiPF6"},{"code":"002460","name":"Ganfeng","reason":"Lithium salt"}]}'
    out = parse_deepseek_response(raw)
    assert "picks" in out
    assert len(out["picks"]) == 3


def test_parse_deepseek_markdown_fence():
    raw = '```json\n{"picks":[{"code":"002812","name":"Enjie","reason":"PVDF"},{"code":"002407","name":"Dofluoride","reason":"LiPF6"},{"code":"002460","name":"Ganfeng","reason":"Lithium"}]}\n```'
    out = parse_deepseek_response(raw)
    assert "picks" in out


def test_parse_deepseek_error_keyword():
    raw = '{"error":"concept not found"}'
    out = parse_deepseek_response(raw)
    assert "error" in out


def test_parse_deepseek_wrong_count():
    raw = '{"picks":[{"code":"002812","name":"x","reason":"y"}]}'
    out = parse_deepseek_response(raw)
    assert "error" in out


def test_parse_deepseek_bad_json():
    raw = 'not json at all'
    out = parse_deepseek_response(raw)
    assert "error" in out


def test_parse_deepseek_invalid_code():
    raw = '{"picks":[{"code":"abc","name":"x","reason":"y"},{"code":"002407","name":"a","reason":"b"},{"code":"002460","name":"c","reason":"d"}]}'
    out = parse_deepseek_response(raw)
    assert "error" in out
