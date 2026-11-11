"""Разбор текста про машины и госномера."""

from __future__ import annotations

import re

from stobot.storage.repositories import normalize_plate

# Современный казахстанский номер: 123ABC01 (3 цифры, 2–3 буквы, 2 цифры региона)
KZ_PLATE_RE = re.compile(r"^\d{3}[A-Z]{2,3}\d{2}$")


def is_kz_plate(text: str) -> bool:
    return bool(KZ_PLATE_RE.match(normalize_plate(text)))


def looks_like_plate(token: str) -> bool:
    """Более мягкая проверка для /car: есть и буквы, и цифры, длина 4–10."""
    plate = normalize_plate(token)
    return (
        4 <= len(plate) <= 10
        and any(c.isdigit() for c in plate)
        and any(c.isalpha() for c in plate)
    )


def parse_car_args(args: str) -> tuple[str, str] | None:
    """'Камри 123ABC01' -> ('Камри', '123ABC01'). Номер — последнее слово.

    Номер иногда пишут с пробелами: 'Камри 123 ABC 01' — это тоже понимаем.
    """
    words = args.split()
    if not words:
        return None
    # Пробуем взять номер из 3, 2 или 1 последних слов
    for n in (3, 2, 1):
        if len(words) < n:
            continue
        candidate = "".join(words[-n:])
        if is_kz_plate(candidate) or (n == 1 and looks_like_plate(candidate)):
            model = " ".join(words[:-n])
            return model, normalize_plate(candidate)
    return None


def parse_car_in_text(text: str) -> tuple[str, str] | None:
    """Простой текст «Камри 123ABC01»: модель на кириллице/латинице + казахстанский номер."""
    parsed = parse_car_args(text)
    if parsed is None:
        return None
    model, plate = parsed
    if not model or not is_kz_plate(plate):
        return None
    # В модели должна быть хотя бы одна буква и не должно быть «служебных» слов
    if not re.search(r"[A-Za-zА-Яа-яЁё]", model) or len(model) > 30:
        return None
    return model, plate


_ORDERS_FOR_CAR_RE = re.compile(r"заказ\w*\s+(?:для|на|по)?\s*(.+)$", re.IGNORECASE)


def parse_orders_query(text: str) -> str | None:
    """«что заказывали для 123ABC01» -> '123ABC01'."""
    match = _ORDERS_FOR_CAR_RE.search(text.strip().rstrip("?"))
    if not match:
        return None
    parsed = parse_car_args(match.group(1))
    return parsed[1] if parsed else None
