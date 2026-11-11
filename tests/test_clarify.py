"""Тесты логики уточнений и распознавания названий."""

import pytest

from stobot.ai.dictionary import DictionaryRecognizer
from stobot.core import clarify
from stobot.core.models import Car
from stobot.core.parts import PARTS, QUESTIONS, PartType, Question

recognizer = DictionaryRecognizer()


@pytest.mark.parametrize(
    ("text", "part"),
    [
        ("граната", "cv_joint"),
        ("калодки перед", "brake_pads"),
        ("подушка двигла", "engine_mount"),
        ("амортизаторы задние", "shock_absorber"),
        ("стойка стабилизатора левая", "stabilizer_link"),
        ("фильтр салона", "cabin_filter"),
        ("масляный фильтр", "oil_filter"),
        ("акб", "battery"),
    ],
)
def test_recognize_slang_and_typos(text, part):
    assert recognizer.recognize_sync(text).part_key == part


def test_unknown_text_is_not_recognized():
    assert recognizer.recognize_sync("привет как дела").part_key is None


def test_answers_from_text():
    result = recognizer.recognize_sync("калодки перед")
    assert result.answers == {"axle": "front"}
    result = recognizer.recognize_sync("граната левая наружная")
    assert result.answers == {"side": "left", "cv_position": "outer"}


def test_nothing_to_ask_for_simple_part():
    state = clarify.start("cabin_filter", {}, None, {})
    assert state.done and state.ask == []


def test_known_from_text_is_not_asked():
    state = clarify.start("brake_pads", {"axle": "front"}, None, {})
    assert state.done


def test_asks_all_missing_at_once():
    state = clarify.start("cv_joint", {}, None, {})
    assert state.ask == ["side", "cv_position"]  # оба вопроса сразу
    state = clarify.start("cv_joint", {"side": "right"}, None, {})
    assert state.ask == ["cv_position"]


def test_car_engine_not_asked_again():
    car = Car(id=1, plate="123ABC01", model="Камри", engine="2AR-FE")
    state = clarify.start("oil_filter", {}, car, {})
    assert state.done
    assert state.answers["engine"] == "2AR-FE"


def test_previous_car_answers_used():
    car = Car(id=1, plate="123ABC01", model="Камри")
    state = clarify.start("engine_mount", {}, car, {"transmission": "at"})
    assert state.ask == ["mount_position"]


def test_request_answers_are_not_reused_from_car():
    # Сторона/ось не запоминаются за машиной — сегодня перед, завтра зад
    assert QUESTIONS["axle"].scope == "request"
    assert QUESTIONS["side"].scope == "request"


def test_single_option_question_not_asked(monkeypatch):
    only_one = Question("kind", "Тип", (("std", "Стандарт"),))
    monkeypatch.setitem(QUESTIONS, "kind", only_one)
    monkeypatch.setitem(PARTS, "test_part", PartType("test_part", "Тест", ("тест",), ("kind",)))
    state = clarify.start("test_part", {}, None, {})
    assert state.done
    assert state.answers["kind"] == "std"


def test_apply_answer_validates():
    state = clarify.start("brake_pads", {}, None, {})
    clarify.apply_answer(state, "axle", "middle")  # такого варианта нет
    assert not state.done
    clarify.apply_answer(state, "side", "left")  # такой вопрос не задавали
    assert "side" not in state.answers
    clarify.apply_answer(state, "axle", "rear")
    assert state.done
    assert state.summary() == "Тормозные колодки, Задние"


def test_state_roundtrip():
    state = clarify.start("cv_joint", {"side": "left"}, None, {})
    again = clarify.ClarifyState.from_dict(state.to_dict())
    assert again == state
