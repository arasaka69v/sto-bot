"""Как выглядят сообщения бота: текст и кнопки.

Здесь только оформление. Решения (что искать, что заказать) — в app.py и сервисах.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from stobot.core.checkout import CheckReport, ConfirmResult
from stobot.core.clarify import ClarifyState
from stobot.core.models import Car, CartItem, CheckStatus, Offer, Order
from stobot.core.parts import QUESTIONS
from stobot.core.replies import Button, Reply
from stobot.core.search import SearchResult
from stobot.texts import days, esc, money

# Казахстан живёт по UTC+5. Фиксированное смещение вместо часовых поясов —
# чтобы на Windows не понадобился дополнительный пакет tzdata.
LOCAL_OFFSET = timedelta(hours=5)


def local_time(utc_text: str) -> str:
    """'2026-11-11 09:20:00' (UTC из SQLite) -> '11.11 14:20'."""
    try:
        moment = datetime.strptime(utc_text, "%Y-%m-%d %H:%M:%S") + LOCAL_OFFSET
    except ValueError:
        return utc_text
    return moment.strftime("%d.%m %H:%M")


def offer_line(offer: Offer) -> str:
    """Бренд + артикул + пометка «оригинал»."""
    original = " · <i>оригинал</i>" if offer.is_original else ""
    return f"<b>{esc(offer.brand)}</b> {esc(offer.article)}{original}"


def car_line(car: Car | None) -> str:
    return f"🚗 {esc(car.title)}" if car else "🚗 без машины"


# --- Поиск ---


def search_reply(
    result: SearchResult,
    snapshot_ids: list[int],
    car: Car | None,
    normal_days: int,
    currency: str,
    analogs_snapshot: int | None,
) -> Reply:
    title = "аналоги" if result.is_analogs else "артикул"
    lines = [f"🔎 {title} <b>{esc(result.article)}</b>"]
    if car:
        lines.append(f"Добавлять для: {car_line(car)}")
    lines.append("")

    buttons: list[list[Button]] = []
    for n, (offer, snap_id) in enumerate(zip(result.offers, snapshot_ids, strict=True), 1):
        star = "⭐ " if result.best is not None and offer == result.best else ""
        lines.append(f"{star}<b>{n}.</b> {offer_line(offer)}")
        lines.append(esc(offer.name))
        if offer.stock > 0:
            stock = f"📦 {offer.stock} шт · 🚚 {days(offer.delivery_days)}"
        else:
            stock = "❌ нет в наличии"
        lines.append(f"💰 <b>{money(offer.price, currency)}</b> · {stock}")
        if offer.promo:
            lines.append(f"🔥 {esc(offer.promo)}")
        if offer.multiplicity > 1:
            lines.append(f"📦 продаётся по {offer.multiplicity} шт")
        if offer.note:
            lines.append(f"ℹ️ {esc(offer.note)}")
        lines.append("")
        if offer.stock > 0:
            buttons.append([Button(f"🛒 В корзину №{n} — {offer.brand}", f"add:{snap_id}")])

    if result.best is not None:
        lines.append(f"⭐ — самый выгодный: дешевле всех с доставкой до {days(normal_days)}")
    elif result.offers:
        lines.append(f"Нет вариантов в наличии с доставкой до {days(normal_days)}.")
    if result.total_found > len(result.offers):
        lines.append(f"Показано {len(result.offers)} из {result.total_found}.")

    if result.can_show_analogs and analogs_snapshot is not None:
        buttons.append([Button("🔁 Показать аналоги", f"an:{analogs_snapshot}")])
    return Reply("\n".join(lines).strip(), buttons)


# --- Корзина ---


def cart_reply(
    items: list[CartItem], total: Decimal, is_admin: bool, currency: str, edit: bool = False
) -> Reply:
    if not items:
        return Reply("🛒 Корзина пуста.\nПришлите артикул, чтобы найти деталь.", edit=edit)

    lines = [f"🛒 <b>Общая корзина</b> ({len(items)} поз.)", ""]
    buttons: list[list[Button]] = []
    for n, item in enumerate(items, 1):
        lines.append(f"<b>{n}.</b> {offer_line(item.offer)}")
        lines.append(esc(item.offer.name))
        lines.append(
            f"{item.qty} × {money(item.offer.price, currency)} = "
            f"<b>{money(item.total, currency)}</b>"
        )
        lines.append(f"👤 {esc(item.added_by_name)} · {car_line(item.car)}")
        lines.append("")
        buttons.append(
            [
                Button("➖", f"q-:{item.id}"),
                Button(f"№{n}: {item.qty} шт", "noop"),
                Button("➕", f"q+:{item.id}"),
                Button("🗑", f"del:{item.id}"),
            ]
        )
    lines.append(f"<b>Итого: {money(total, currency)}</b>")
    lines.append("<i>Цены на момент добавления. Перед заказом бот проверит их заново.</i>")

    buttons.append([Button("🔄 Обновить", "cart:r")])
    if is_admin:
        buttons.append([Button("✅ Оформить заказ", "co")])
    return Reply("\n".join(lines), buttons, edit=edit)


# --- Оформление ---


def check_reply(report: CheckReport, test_mode: bool, currency: str) -> Reply:
    lines = ["📋 <b>Проверка перед заказом</b>", ""]
    for c in report.checks:
        item, cur = c.item, c.current
        head = f"{offer_line(item.offer)} × {item.qty}"
        if c.status == CheckStatus.OK and cur:
            lines.append(f"✅ {head} — {money(cur.price * item.qty, currency)}")
        elif c.status == CheckStatus.PRICE_CHANGED and cur:
            arrow = "📈" if cur.price > item.offer.price else "📉"
            lines.append(
                f"{arrow} {head} — цена изменилась: {money(item.offer.price, currency)} → "
                f"<b>{money(cur.price, currency)}</b>"
            )
        elif c.status == CheckStatus.NOT_ENOUGH and cur:
            lines.append(
                f"⚠️ {head} — в наличии только {cur.stock} шт, закажем {c.order_qty}"
                f" по {money(cur.price, currency)}"
            )
        else:
            lines.append(f"❌ {head} — закончилось, НЕ закажем (останется в корзине)")
        if cur and cur.delivery_days != item.offer.delivery_days and c.will_order:
            lines.append(f"    🚚 срок теперь: {days(cur.delivery_days)}")

    lines.append("")
    if not report.to_order:
        lines.append("Заказывать нечего: всё из корзины закончилось.")
        return Reply("\n".join(lines), [[Button("🔄 Проверить заново", "co")]])

    lines.append(f"<b>К заказу: {len(report.to_order)} поз. на {money(report.total, currency)}</b>")
    if not report.has_changes:
        lines.append("Изменений нет.")
    if test_mode:
        lines.append(
            "\n🧪 <i>Тестовый режим: заказ не уйдёт поставщику, бот только покажет его.</i>"
        )
    buttons = [
        [Button("✅ Подтвердить заказ", f"co:ok:{report.session_id}")],
        [Button("🔄 Проверить заново", "co"), Button("❌ Отмена", f"co:no:{report.session_id}")],
    ]
    return Reply("\n".join(lines), buttons)


def confirm_reply(result: ConfirmResult, currency: str) -> Reply:
    recheck = [[Button("🔄 Проверить заново", "co")]]
    if result.message_key == "cart_changed":
        return Reply("Корзину изменили после проверки. Проверьте заново.", recheck, edit=True)
    if result.message_key == "expired":
        return Reply(
            "Проверка устарела (прошло больше 15 минут). Проверьте заново.", recheck, edit=True
        )
    if result.message_key == "already_used":
        return Reply("Этот заказ уже оформлен. Смотрите /orders.", edit=True)
    if result.message_key == "empty":
        return Reply("Заказывать нечего: всё из корзины закончилось.", edit=True)

    order_lines = [
        f"• {offer_line(ln.offer)} × {ln.qty} по {money(ln.offer.price, currency)}"
        for ln in result.lines
    ]
    skipped = [f"• {offer_line(c.item.offer)}" for c in result.skipped]

    if result.message_key == "test_mode":
        text = [
            "🧪 <b>ТЕСТОВЫЙ РЕЖИМ — заказ НЕ отправлен.</b>",
            "Вот что ушло бы поставщику:",
            "",
            *order_lines,
            "",
            f"<b>Итого: {money(result.total, currency)}</b>",
            "",
            "Корзина не изменилась. Чтобы заказывать по-настоящему, "
            "поставьте TEST_MODE=false в .env и перезапустите бота.",
        ]
        return Reply("\n".join(text), edit=True)

    placed = result.placed
    assert placed is not None
    text = [
        "✅ <b>Заказ оформлен!</b>",
        f"Номер у поставщика: <b>{esc(placed.supplier_order_id)}</b>",
        f"Статус: {esc(placed.status)}",
        "",
        *order_lines,
        "",
        f"<b>Сумма: {money(result.total, currency)}</b>",
    ]
    if placed.rejected:
        text += ["", "⚠️ Поставщик НЕ принял (остались в корзине):"]
        text += [
            f"• <b>{esc(brand)}</b> {esc(article)} — {esc(reason)}"
            for brand, article, reason in placed.rejected
        ]
    if skipped:
        text += ["", "Остались в корзине (не было в наличии):", *skipped]
    return Reply("\n".join(text), edit=True)


# --- Заказы ---


def orders_reply(orders: list[Order], currency: str, car: Car | None = None) -> Reply:
    if car:
        title = f"📦 <b>Что заказывали для {esc(car.title)}</b>"
    else:
        title = "📦 <b>Последние заказы</b>"
    if not orders:
        return Reply(f"{title}\n\nЗаказов пока нет.")
    lines = [title, ""]
    for order in orders:
        lines.append(
            f"<b>{esc(order.supplier_order_id)}</b> · {local_time(order.created_at)}"
            f" · {esc(order.status)}"
        )
        if not car:
            lines.append(f"{len(order.lines)} поз. на {money(order.total, currency)}")
        for ln in order.lines:
            where = f" ({esc(ln['car'])})" if ln["car"] and not car else ""
            lines.append(f"  • {offer_line(ln['offer'])} × {ln['qty']}{where}")
        lines.append("")
    return Reply("\n".join(lines).strip())


# --- Машины ---


def car_reply(car: Car, answers: dict[str, str], is_current: bool) -> Reply:
    status = " — <b>текущая</b>" if is_current else ""
    lines = [f"🚗 <b>{esc(car.title)}</b>{status}", ""]
    lines.append(f"VIN: <code>{esc(car.vin)}</code>" if car.vin else "VIN: —")
    # Необязательные поля показываем, только если они заполнены — меньше лишнего
    if car.plate:
        lines.append(f"Госномер: {esc(car.plate)}")
    if car.engine:
        lines.append(f"Двигатель: {esc(car.engine)}")
    if car.year:
        lines.append(f"Год: {car.year}")
    for key, value in answers.items():
        if key in QUESTIONS:
            lines.append(f"{QUESTIONS[key].title}: {esc(QUESTIONS[key].label(value))}")
    if is_current:
        lines.append("\nВсё, что вы добавите в корзину, привяжется к этой машине.")
    edit_row = [] if car.vin else [Button("✏️ Указать VIN", f"carf:vin:{car.id}")]
    if not car.plate:
        edit_row.append(Button("✏️ Госномер", f"carf:plate:{car.id}"))
    buttons = [edit_row] if edit_row else []
    buttons.append(
        [Button("🚫 Отвязать машину", "car:off")]
        if is_current
        else [Button("✅ Сделать текущей", f"car:{car.id}")]
    )
    return Reply("\n".join(lines), buttons)


# --- Уточнения ---


def clarify_reply(
    session_id: int, state: ClarifyState, car: Car | None, edit: bool = False
) -> Reply:
    lines = [f"🔧 Понял: <b>{esc(state.part.title)}</b>"]
    if car:
        lines.append(car_line(car))
    lines += ["", "Уточните, чтобы подобрать точно:"]
    buttons: list[list[Button]] = []
    for key in state.ask:
        question = QUESTIONS[key]
        chosen = state.answers.get(key)
        shown = f"<b>{esc(question.label(chosen))}</b> ✅" if chosen else "?"
        lines.append(f"• {question.title}: {shown}")
        if question.free_text:
            buttons.append(
                [Button(f"✏️ Указать: {question.title.lower()}", f"clt:{session_id}:{key}")]
            )
        else:
            buttons.append(
                [
                    Button(
                        ("✅ " if chosen == value else "") + label, f"cl:{session_id}:{key}:{value}"
                    )
                    for value, label in question.options
                ]
            )
    return Reply("\n".join(lines), buttons, edit=edit)


def _part_summary(part_key: str, answers: dict[str, str]) -> str:
    """«Тормозные колодки, Передние»."""
    return ClarifyState(part_key=part_key, car_id=None, answers=answers).summary()


def no_catalog_reply(part_key: str, answers: dict[str, str], car: Car | None) -> Reply:
    """Каталога по VIN ещё нет: просим артикул без лишних вопросов."""
    lines = [f"🔧 Понял: <b>{esc(_part_summary(part_key, answers))}</b>"]
    if car:
        lines.append(car_line(car))
    lines += [
        "",
        "📖 Подобрать артикул по названию пока не могу — каталог по VIN ещё не подключён.",
        "Пришлите <b>артикул</b> (с коробки, со старой детали или из каталога) — "
        "найду цену и наличие.",
    ]
    return Reply("\n".join(lines))


def ask_vin_text(part_key: str) -> str:
    title = _part_summary(part_key, {})
    return (
        f"🔧 Понял: <b>{esc(title)}</b>\n\n"
        "Пришлите <b>VIN</b> машины (17 символов) — подберу деталь по нему.\n"
        "Или пришлите артикул, если он есть."
    )


def catalog_not_found_reply(state: ClarifyState, car: Car | None, edit: bool = False) -> Reply:
    lines = [f"🔧 <b>{esc(state.summary())}</b>"]
    if car:
        lines.append(car_line(car))
    lines += [
        "",
        "📖 Каталог не нашёл эту деталь для этой машины.",
        "Пришлите <b>артикул</b>, если он есть, — найду цену и наличие.",
    ]
    return Reply("\n".join(lines), edit=edit)
