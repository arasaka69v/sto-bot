"""ИИ-модуль (без реального API) и скрытие секретов в логах."""

import json
import logging
from types import SimpleNamespace

from stobot.ai.claude import ClaudeRecognizer, _schema
from stobot.logging_setup import SecretFilter
from tests.conftest import run


def fake_response(data: dict, stop_reason: str = "end_turn"):
    block = SimpleNamespace(type="text", text=json.dumps(data))
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def make_recognizer(response=None, error=None):
    rec = ClaudeRecognizer(api_key="test-key", model="claude-opus-5-5")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return response

    rec.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return rec, calls


def test_dictionary_first_ai_not_called():
    rec, calls = make_recognizer()
    assert run(rec.recognize("граната")).part_key == "cv_joint"
    assert calls == []  # словарь справился — ИИ не тратим


def test_ai_used_when_dictionary_fails():
    answers = {k: "unknown" for k in _schema()["properties"]["answers"]["properties"]}
    answers["axle"] = "front"
    answers["side"] = "left"  # для колодок сторону не спрашиваем — отбросится
    rec, calls = make_recognizer(fake_response({"part_key": "brake_pads", "answers": answers}))
    result = run(rec.recognize("тормозухи на передок"))
    assert result.part_key == "brake_pads"
    assert result.answers == {"axle": "front"}
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_ai_unknown_and_errors_are_safe():
    rec, _ = make_recognizer(fake_response({"part_key": "unknown", "answers": {}}))
    assert run(rec.recognize("абракадабра")).part_key is None
    rec, _ = make_recognizer(error=RuntimeError("сеть упала"))
    assert run(rec.recognize("абракадабра")).part_key is None
    rec, _ = make_recognizer(fake_response({}, stop_reason="refusal"))
    assert run(rec.recognize("абракадабра")).part_key is None


def test_schema_cannot_return_article():
    schema = _schema()
    assert set(schema["properties"]) == {"part_key", "answers"}
    assert schema["additionalProperties"] is False


def test_secret_filter_hides_token():
    record = logging.LogRecord(
        "x", logging.INFO, "", 0, "url=%s", ("https://api/bot123:SECRET/get",), None
    )
    SecretFilter(("123:SECRET",)).filter(record)
    assert record.getMessage() == "url=https://api/bot***/get"
