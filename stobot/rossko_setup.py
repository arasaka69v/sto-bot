"""Мастер настройки Росско: python -m stobot.rossko_setup (или rossko_setup.bat).

Что делает:
1. Спрашивает ключи KEY1 и KEY2 (их выдаёт менеджер Росско).
2. Сам узнаёт у Росско (метод GetCheckoutDetails) ваши способы доставки,
   адреса, способы оплаты и юрлица — и даёт выбрать номером.
3. Спрашивает контакт для заказов (имя и телефон).
4. Делает пробный поиск, чтобы убедиться, что всё работает.
5. Записывает всё в .env и включает SUPPLIER=rossko.

Ключи вводятся только здесь, на вашем компьютере, и хранятся только в .env.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

from stobot.suppliers import rossko_soap as soap
from stobot.suppliers.base import SupplierError
from stobot.suppliers.rossko_soap import RosskoAuthError

ENV_PATH = Path(".env")


def ask(prompt: str, current: str = "") -> str:
    hint = f" [Enter — оставить «{current}»]" if current else ""
    while True:
        value = input(f"{prompt}{hint}: ").strip()
        if value:
            return value
        if current:
            return current
        print("  Нужно что-то ввести.")


def choose(
    title: str, options: list[tuple[str, str]], current: str = "", allow_none: str = ""
) -> str | None:
    """Выбор из списка номером. Один вариант — выбираем сами."""
    print(f"\n{title}:")
    if not options:
        print("  Росско не прислал вариантов — пропускаем.")
        return None
    if len(options) == 1 and not allow_none:
        print(f"  Единственный вариант: {options[0][1]} — выбран.")
        return options[0][0]
    if allow_none:
        print(f"  0. {allow_none}")
    for n, (value, label) in enumerate(options, 1):
        mark = "  ← сейчас" if value == current else ""
        print(f"  {n}. {label}{mark}")
    while True:
        raw = input("Введите номер: ").strip()
        if not raw and current:
            return current
        if raw == "0" and allow_none:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("  Нет такого номера, попробуйте ещё раз.")


def address_label(address) -> str:
    parts = [soap.text(address, k) for k in ("city", "street", "house", "office")]
    return ", ".join(p for p in parts if p) or "адрес без описания"


async def main() -> int:
    print("=" * 50)
    print(" Настройка Росско для СТО-бота")
    print("=" * 50)
    if not ENV_PATH.exists():
        print("Нет файла .env. Сначала запустите install.bat.")
        return 1
    env = dotenv_values(ENV_PATH)

    print("\nКлючи API выдаёт ваш менеджер Росско (KEY1 и KEY2 — длинные строки).")
    key1 = ask("KEY1", env.get("ROSSKO_KEY1") or "")
    key2 = ask("KEY2", env.get("ROSSKO_KEY2") or "")
    auth = {"KEY1": key1, "KEY2": key2}

    print("\nСпрашиваю у Росско настройки вашего аккаунта...")
    try:
        details = await soap.call("GetCheckoutDetails", auth, "CheckoutDetailsResult")
    except RosskoAuthError as e:
        print(f"❌ Росско не принял ключи: {e}")
        print("Проверьте KEY1 и KEY2 у менеджера Росско и запустите настройку снова.")
        return 1
    except SupplierError as e:
        print(f"❌ Не удалось связаться с Росско: {e}. Проверьте интернет и повторите.")
        return 1
    if not soap.boolean(details, "success"):
        print(f"❌ Росско ответил: {soap.text(details, 'message') or 'без пояснения'}")
        return 1
    print("✅ Ключи приняты.")

    deliveries = [
        (soap.text(d, "id"), soap.text(d, "name"))
        for d in soap.children(soap.child(details, "DeliveryType"), "delivery")
    ]
    delivery_id = choose("Способ доставки", deliveries, env.get("ROSSKO_DELIVERY_ID") or "")
    if not delivery_id:
        print("❌ Без способа доставки Росско не ищет и не принимает заказы. Уточните у менеджера.")
        return 1

    # Адреса, для которых доступен выбранный способ доставки
    addresses = []
    for a in soap.children(soap.child(details, "DeliveryAddress"), "address"):
        ids = [el.text for el in soap.children(soap.child(soap.child(a, "Delivery"), "ids"), "id")]
        if not ids or delivery_id in ids:
            addresses.append((soap.text(a, "id"), address_label(a)))
    address_id = (
        choose(
            "Адрес доставки",
            addresses,
            env.get("ROSSKO_ADDRESS_ID") or "",
            allow_none="без адреса (например, самовывоз)",
        )
        if addresses
        else None
    )

    payments = [
        (soap.text(p, "id"), soap.text(p, "name"))
        for p in soap.children(soap.child(details, "PaymentType"), "payment")
    ]
    payment_id = choose("Способ оплаты", payments, env.get("ROSSKO_PAYMENT_ID") or "")

    companies = [
        (
            soap.text(c, "id"),
            " — ".join(x for x in (soap.text(c, "name"), soap.text(c, "requisite")) if x),
        )
        for c in soap.children(soap.child(details, "CompanyList"), "company")
    ]
    requisite_id = (
        choose("Юрлицо (реквизиты для оплаты)", companies, env.get("ROSSKO_REQUISITE_ID") or "")
        if companies
        else None
    )

    print("\nКонтакт для заказов (его увидит Росско):")
    contact_name = ask("Имя ответственного", env.get("ROSSKO_CONTACT_NAME") or "")
    contact_phone = ask("Телефон", env.get("ROSSKO_CONTACT_PHONE") or "")

    print("\nПробный поиск 04465-33471 ...")
    try:
        result = await soap.call(
            "GetSearch",
            {**auth, "text": "04465-33471", "delivery_id": delivery_id, "address_id": address_id},
            "SearchResult",
        )
        parts = soap.children(soap.child(result, "PartsList"), "Part")
        if parts:
            print(f"✅ Поиск работает: найдено деталей — {len(parts)}.")
        else:
            print(
                f"ℹ️ Росско ответил: {soap.text(result, 'message') or 'ничего не найдено'}. "
                "Это нормально, если этой детали просто нет."
            )
    except SupplierError as e:
        print(f"⚠️ Пробный поиск не удался: {e}. Настройки всё равно сохраню.")

    values = {
        "SUPPLIER": "rossko",
        "ROSSKO_KEY1": key1,
        "ROSSKO_KEY2": key2,
        "ROSSKO_DELIVERY_ID": delivery_id,
        "ROSSKO_ADDRESS_ID": address_id or "",
        "ROSSKO_PAYMENT_ID": payment_id or "",
        "ROSSKO_REQUISITE_ID": requisite_id or "",
        "ROSSKO_CONTACT_NAME": contact_name,
        "ROSSKO_CONTACT_PHONE": contact_phone,
    }
    for key, value in values.items():
        set_key(str(ENV_PATH), key, value, quote_mode="never")

    test_mode = (dotenv_values(ENV_PATH).get("TEST_MODE") or "true").lower()
    print("\n" + "=" * 50)
    print("✅ Готово! Настройки Росско записаны в .env")
    if test_mode in ("true", "1", "yes", "да"):
        print("🧪 Сейчас включён тестовый режим: поиск — настоящий, а заказы")
        print("   НЕ отправляются. Когда проверите — поставьте в .env TEST_MODE=false.")
    print("Запускайте бота: start.bat")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(1)
