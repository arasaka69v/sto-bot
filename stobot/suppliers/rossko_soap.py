"""Низкоуровневая работа с API Росско: SOAP-запросы и разбор XML-ответов.

API Росско — это SOAP (запросы и ответы в формате XML). Описания методов
(WSDL) скачаны с официального сервера и лежат в docs/rossko/*.wsdl.
Названия всех полей здесь взяты оттуда, ничего не придумано.

Отдельная библиотека для SOAP (zeep) не нужна: запрос — это небольшой XML,
который мы собираем сами, а ответ разбираем стандартным модулем xml.etree.
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from stobot.suppliers.base import SupplierError, SupplierUnavailable

log = logging.getLogger(__name__)

BASE_URL = "https://api.rossko.ru/service/v2.1/"
NS = "https://api.rossko.ru/"  # targetNamespace из WSDL
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TIMEOUT = 30.0
NO_RETRY = {"GetCheckout"}  # методы, которые нельзя повторять автоматически

# Для тестов: подменённый «интернет» (httpx.MockTransport). В работе — None.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class RosskoAuthError(SupplierError):
    """Росско не принял ключи KEY1/KEY2."""


def build_envelope(method: str, params: dict[str, Any]) -> bytes:
    """Собирает SOAP-запрос. params — словарь; вложенные словари и списки
    превращаются во вложенные XML-элементы, None пропускается."""
    ET.register_namespace("soap", SOAP_NS)
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    root = ET.SubElement(body, f"{{{NS}}}{method}")
    _fill(root, params)
    return b'<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(envelope, encoding="utf-8")


def _fill(parent: ET.Element, params: dict[str, Any]) -> None:
    for name, value in params.items():
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            element = ET.SubElement(parent, f"{{{NS}}}{name}")
            if isinstance(item, dict):
                _fill(element, item)
            elif isinstance(item, bool):
                element.text = "true" if item else "false"
            else:
                element.text = str(item)


def _local(tag: str) -> str:
    """'{https://api.rossko.ru/}success' -> 'success'."""
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for c in element:
        if _local(c.tag) == name:
            return c
    return None


def children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [c for c in element if _local(c.tag) == name]


def text(element: ET.Element | None, name: str, default: str = "") -> str:
    found = child(element, name)
    if found is None or found.text is None:
        return default
    return found.text.strip()


def integer(element: ET.Element | None, name: str, default: int = 0) -> int:
    value = text(element, name)
    try:
        return int(value)
    except ValueError:
        return default


def boolean(element: ET.Element | None, name: str) -> bool:
    return text(element, name).lower() == "true"


async def call(method: str, params: dict[str, Any], result_name: str) -> ET.Element:
    """Вызывает метод API и возвращает элемент результата (например, SearchResult).

    Ошибки сети → SupplierUnavailable, неверные ключи → RosskoAuthError.
    Ключи в лог не пишутся.
    """
    url = BASE_URL + method
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{url}"',
    }
    # Заказ при сбое сети НЕ повторяем: он мог дойти, и получился бы второй заказ.
    # Поиск и чтение данных безопасно повторить один раз.
    attempts = 1 if method in NO_RETRY else 2
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            # Новый клиент на каждый запрос — проще и надёжнее для бота, запросов немного
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT) as client:
                response = await client.post(
                    url, content=build_envelope(method, params), headers=headers
                )
            break
        except httpx.HTTPError as e:
            log.warning(
                "rossko %s network error (attempt %d): %s", method, attempt, type(e).__name__
            )
            if attempt == attempts:
                raise SupplierUnavailable(f"Росско не отвечает ({type(e).__name__})") from e
            await asyncio.sleep(1)
    elapsed = time.monotonic() - started
    log.info("rossko %s http=%s %.1fs", method, response.status_code, elapsed)

    if response.status_code >= 500 and b"Fault" not in response.content:
        raise SupplierUnavailable(f"Росско вернул ошибку сервера {response.status_code}")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        raise SupplierUnavailable("Росско вернул непонятный ответ") from e

    body = child(root, "Body")
    fault = child(body, "Fault")
    if fault is not None:
        message = text(fault, "faultstring") or "ошибка SOAP"
        log.error("rossko %s fault: %s", method, message)
        raise SupplierError(f"Росско: {message}")

    response_el = child(body, f"{method}Response")
    result = child(response_el, result_name)
    if result is None:
        raise SupplierUnavailable("В ответе Росско нет результата")

    if not boolean(result, "success"):
        message = text(result, "message")
        if "KEY" in message.upper():
            raise RosskoAuthError(message)
    return result
