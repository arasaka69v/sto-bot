"""Общие заготовки для тестов: база в памяти, mock-поставщик, пользователи."""

from __future__ import annotations

import asyncio

import pytest

from stobot.ai.dictionary import DictionaryRecognizer
from stobot.catalog.stub import StubCatalog
from stobot.core.app import BotApp
from stobot.core.models import User
from stobot.storage.db import connect
from stobot.suppliers.mock import MockSupplier

ADMIN = User(id=1, name="Админ", is_admin=True, is_master=True)
MASTER = User(id=2, name="Мастер Ерлан", is_master=True)
STRANGER = User(id=99, name="Чужой")


def run(coro):
    """Запускает асинхронную функцию в синхронном тесте."""
    return asyncio.run(coro)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def make_app(conn, test_mode: bool = False) -> BotApp:
    return BotApp(
        conn=conn,
        supplier=MockSupplier(),
        recognizer=DictionaryRecognizer(),
        catalog=StubCatalog(),
        admin_ids=frozenset({ADMIN.id}),
        test_mode=test_mode,
    )


@pytest.fixture
def app(conn):
    return make_app(conn, test_mode=False)


@pytest.fixture
def test_mode_app(conn):
    return make_app(conn, test_mode=True)


def find_action(response, prefix: str) -> str:
    """Находит в ответе первую кнопку, чья команда начинается с prefix."""
    for reply in response.replies:
        for row in reply.buttons:
            for button in row:
                if button.action.startswith(prefix):
                    return button.action
    raise AssertionError(f"Нет кнопки {prefix!r}")
