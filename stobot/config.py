"""Чтение настроек из файла .env.

Все секреты и параметры живут только в .env — в коде их нет.
Так один и тот же код работает и у вас на компьютере, и на VPS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Ошибка в настройках: понятное сообщение, что исправить в .env."""


def _parse_ids(raw: str, name: str) -> frozenset[int]:
    """Превращает строку '123, 456' в набор чисел {123, 456}."""
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.lstrip("-").isdigit():
            raise ConfigError(f"{name}: «{part}» — не похоже на Telegram ID (нужны только цифры)")
        ids.add(int(part))
    return frozenset(ids)


def _parse_bool(raw: str, name: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "да", "on"):
        return True
    if value in ("0", "false", "no", "нет", "off"):
        return False
    raise ConfigError(f"{name}: ожидается true или false, а указано «{raw}»")


@dataclass(frozen=True)
class RosskoConfig:
    """Параметры бизнес-аккаунта Росско. Заполняются мастером настройки rossko_setup."""

    key1: str = ""
    key2: str = ""
    delivery_id: str = ""  # способ доставки (обязателен для поиска и заказа)
    address_id: int | None = None  # адрес доставки (если нужен для способа доставки)
    payment_id: int | None = None  # способ оплаты
    requisite_id: int | None = None  # юрлицо/реквизиты для оплаты (если есть)
    contact_name: str = ""
    contact_phone: str = ""
    delivery_parts: bool = False  # поле delivery_parts из API (уточните у менеджера)

    def missing_for_search(self) -> list[str]:
        names = {
            "ROSSKO_KEY1": self.key1,
            "ROSSKO_KEY2": self.key2,
            "ROSSKO_DELIVERY_ID": self.delivery_id,
        }
        return [k for k, v in names.items() if not v]

    def missing_for_order(self) -> list[str]:
        missing = self.missing_for_search()
        if self.payment_id is None:
            missing.append("ROSSKO_PAYMENT_ID")
        if not self.contact_name:
            missing.append("ROSSKO_CONTACT_NAME")
        if not self.contact_phone:
            missing.append("ROSSKO_CONTACT_PHONE")
        return missing


def _optional_int(raw: str, name: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if not raw.lstrip("-").isdigit():
        raise ConfigError(f"{name}: нужно число, а указано «{raw}»")
    return int(raw)


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    admin_ids: frozenset[int]
    master_ids: frozenset[int]
    supplier: str = "mock"
    test_mode: bool = True
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    normal_delivery_days: int = 3
    currency: str = "₸"
    db_path: Path = Path("data/sto_bot.db")
    log_path: Path = Path("data/logs/bot.log")
    rossko: RosskoConfig = field(default_factory=RosskoConfig, repr=False)
    # Значения, которые нельзя писать в логи (заполняется автоматически)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def __repr__(self) -> str:  # чтобы токен случайно не попал в лог через print(settings)
        return f"Settings(supplier={self.supplier!r}, test_mode={self.test_mode})"


def load_settings(env_file: str | None = ".env", require_token: bool = True) -> Settings:
    """Загружает настройки. При ошибке — ConfigError с понятным текстом."""
    if env_file:
        load_dotenv(env_file)

    def env(name: str, default: str = "") -> str:
        return os.getenv(name, default).strip()

    token = env("TELEGRAM_BOT_TOKEN")
    if require_token and not token:
        raise ConfigError(
            "Не указан TELEGRAM_BOT_TOKEN в .env. Получите токен у @BotFather (см. README)."
        )

    admin_ids = _parse_ids(env("ADMIN_IDS"), "ADMIN_IDS")
    if require_token and not admin_ids:
        raise ConfigError(
            "Не указан ни один админ в ADMIN_IDS. Узнайте свой ID у @userinfobot (см. README)."
        )
    # Админ — тоже мастер: может искать и добавлять в корзину
    master_ids = _parse_ids(env("MASTER_IDS"), "MASTER_IDS") | admin_ids

    supplier = env("SUPPLIER", "mock").lower()
    if supplier not in ("mock", "rossko"):
        raise ConfigError(f"SUPPLIER: допустимо mock или rossko, а указано «{supplier}»")

    days_raw = env("NORMAL_DELIVERY_DAYS", "3")
    if not days_raw.isdigit():
        raise ConfigError(f"NORMAL_DELIVERY_DAYS: нужно целое число дней, а указано «{days_raw}»")

    api_key = env("ANTHROPIC_API_KEY")
    rossko = RosskoConfig(
        key1=env("ROSSKO_KEY1"),
        key2=env("ROSSKO_KEY2"),
        delivery_id=env("ROSSKO_DELIVERY_ID"),
        address_id=_optional_int(env("ROSSKO_ADDRESS_ID"), "ROSSKO_ADDRESS_ID"),
        payment_id=_optional_int(env("ROSSKO_PAYMENT_ID"), "ROSSKO_PAYMENT_ID"),
        requisite_id=_optional_int(env("ROSSKO_REQUISITE_ID"), "ROSSKO_REQUISITE_ID"),
        contact_name=env("ROSSKO_CONTACT_NAME"),
        contact_phone=env("ROSSKO_CONTACT_PHONE"),
        delivery_parts=_parse_bool(env("ROSSKO_DELIVERY_PARTS", "false"), "ROSSKO_DELIVERY_PARTS"),
    )
    if supplier == "rossko" and rossko.missing_for_search():
        raise ConfigError(
            "Не заполнены настройки Росско: "
            + ", ".join(rossko.missing_for_search())
            + ". Запустите rossko_setup.bat — он всё заполнит сам."
        )
    return Settings(
        telegram_token=token,
        admin_ids=admin_ids,
        master_ids=master_ids,
        supplier=supplier,
        test_mode=_parse_bool(env("TEST_MODE", "true"), "TEST_MODE"),
        anthropic_api_key=api_key,
        ai_model=env("AI_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
        normal_delivery_days=int(days_raw),
        currency=env("CURRENCY_SYMBOL", "₸") or "₸",
        db_path=Path(env("DB_PATH", "data/sto_bot.db")),
        log_path=Path(env("LOG_PATH", "data/logs/bot.log")),
        rossko=rossko,
        secrets=tuple(s for s in (token, api_key, rossko.key1, rossko.key2) if s),
    )
