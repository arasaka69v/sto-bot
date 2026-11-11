"""«Мозг» бота: принимает команды, текст и нажатия кнопок — возвращает ответы.

Этот модуль НЕ знает про Telegram. Адаптер (adapters/telegram) превращает
сообщение Telegram в вызов handle_command / handle_text / handle_action,
а ответ Response — обратно в сообщения Telegram. Для WhatsApp нужен
только новый адаптер.
"""

from __future__ import annotations

import logging
import sqlite3

from stobot import texts
from stobot.ai.base import PartRecognizer
from stobot.catalog.base import VinCatalog
from stobot.core import cars as car_parsing
from stobot.core import clarify, views
from stobot.core.cart import CartService
from stobot.core.checkout import CheckoutService
from stobot.core.models import Car, User
from stobot.core.parts import QUESTIONS
from stobot.core.replies import Button, Notification, Reply, Response
from stobot.core.search import SearchResult, SearchService, looks_like_article
from stobot.storage.repositories import (
    CarRepo,
    CartRepo,
    JsonSessionRepo,
    OrderRepo,
    SnapshotRepo,
    UserStateRepo,
)
from stobot.suppliers.base import OrderRejected, Supplier, SupplierError, SupplierUnavailable

log = logging.getLogger(__name__)


class BotApp:
    def __init__(
        self,
        conn: sqlite3.Connection,
        supplier: Supplier,
        recognizer: PartRecognizer,
        catalog: VinCatalog,
        admin_ids: frozenset[int],
        test_mode: bool,
        normal_delivery_days: int = 3,
        currency: str = "₸",
    ):
        self.supplier = supplier
        self.recognizer = recognizer
        self.catalog = catalog
        self.admin_ids = admin_ids
        self.test_mode = test_mode
        self.normal_days = normal_delivery_days
        self.currency = currency

        self.cars = CarRepo(conn)
        self.snapshots = SnapshotRepo(conn)
        self.state = UserStateRepo(conn)
        self.sessions = JsonSessionRepo(conn)
        self.orders = OrderRepo(conn)
        self.cart = CartService(CartRepo(conn, self.cars))
        self.search = SearchService(supplier, normal_delivery_days)
        self.checkout = CheckoutService(supplier, self.cart, self.sessions, self.orders, test_mode)
        self.snapshots.cleanup()

    # ================================================================
    #  Точки входа (их вызывает адаптер мессенджера)
    # ================================================================

    async def handle_command(self, user: User, command: str, args: str = "") -> Response:
        if not user.is_master:
            return Response.text(texts.NO_ACCESS.format(user_id=user.id))
        command = command.lower().lstrip("/")
        handlers = {
            "start": self._help,
            "help": self._help,
            "search": lambda u, a: self._search_article(u, a),
            "cart": lambda u, a: self._show_cart(u),
            "car": self._car_command,
            "orders": self._orders_command,
            "checkout": lambda u, a: self._checkout_start(u),
            "cancel": self._cancel,
        }
        handler = handlers.get(command)
        if handler is None:
            return Response.text(texts.UNKNOWN_COMMAND)
        return await self._safe(handler(user, args.strip()))

    async def handle_text(self, user: User, text: str) -> Response:
        if not user.is_master:
            return Response.text(texts.NO_ACCESS.format(user_id=user.id))
        return await self._safe(self._route_text(user, text.strip()))

    async def handle_action(self, user: User, action: str) -> Response:
        """Нажатие кнопки. action — строка вида "add:15"."""
        if not user.is_master:
            return Response(popup="Нет доступа")
        return await self._safe(self._route_action(user, action))

    async def _safe(self, coro) -> Response:
        """Превращает ошибки поставщика в понятный мастеру текст."""
        try:
            return await coro
        except SupplierUnavailable:
            log.warning("supplier unavailable", exc_info=True)
            return Response.text(texts.SUPPLIER_DOWN)

    # ================================================================
    #  Текст
    # ================================================================

    async def _route_text(self, user: User, text: str) -> Response:
        if not text:
            return Response.text(texts.HELP)

        # 1. Бот ждёт от этого пользователя ответ (VIN, двигатель…)
        pending = self.state.pending(user.id)
        if pending:
            return await self._handle_pending(user, pending, text)

        # 2. «что заказывали для 123ABC01»
        plate = car_parsing.parse_orders_query(text)
        if plate:
            return await self._orders_command(user, plate)

        # 3. Артикул
        if looks_like_article(text):
            return await self._search_article(user, text)

        # 4. «Камри 123ABC01» — привязка машины
        car_args = car_parsing.parse_car_in_text(text)
        if car_args:
            return await self._car_command(user, text)

        # 5. Название детали
        return await self._search_by_name(user, text)

    async def _handle_pending(self, user: User, pending: str, text: str) -> Response:
        self.state.set_pending(user.id, None)
        kind, *rest = pending.split(":")

        if kind == "car":  # car:<поле>:<id машины>
            field, car_id = rest[0], int(rest[1])
            value: str | int | None = text.strip()
            if field == "vin":
                value = str(value).upper().replace(" ", "")
                if len(value) != 17:
                    self.state.set_pending(user.id, pending)
                    return Response.text(
                        f"В VIN должно быть 17 символов, а здесь {len(value)}. "
                        "Пришлите ещё раз или /cancel."
                    )
            if field == "year":
                if not str(value).isdigit() or not 1950 <= int(str(value)) <= 2100:
                    self.state.set_pending(user.id, pending)
                    return Response.text("Год — это 4 цифры, например 2015. Ещё раз или /cancel.")
                value = int(str(value))
            self.cars.update_field(car_id, field, value)
            return self._car_card(user, car_id, prefix="✅ Сохранил.\n\n")

        if kind == "cl":  # cl:<сессия>:<вопрос> — ответ текстом на уточнение
            session_id, key = int(rest[0]), rest[1]
            return await self._clarify_answer(user, session_id, key, text, edit=False)

        return await self._route_text(user, text)

    # ================================================================
    #  Кнопки
    # ================================================================

    async def _route_action(self, user: User, action: str) -> Response:
        kind, _, arg = action.partition(":")
        if kind == "noop":
            return Response()
        if kind == "add":
            return await self._add_to_cart(user, int(arg))
        if kind == "an":
            return await self._show_analogs(user, int(arg))
        if kind == "cart":
            return await self._show_cart(user, edit=(arg == "r"))
        if kind in ("q+", "q-"):
            return self._change_qty(user, int(arg), +1 if kind == "q+" else -1)
        if kind == "del":
            return self._delete_item(user, int(arg))
        if kind == "co":
            if not arg:
                return await self._checkout_start(user)
            sub, _, session = arg.partition(":")
            if sub == "ok":
                return await self._checkout_confirm(user, int(session))
            return Response.text("Заказ отменён. Корзина не изменилась.", edit=True)
        if kind == "car":
            if arg == "off":
                return await self._car_command(user, "off")
            self.state.set_current_car(user.id, int(arg))
            return self._car_card(user, int(arg))
        if kind == "carf":  # редактирование поля машины: carf:vin:5
            field, _, car_id = arg.partition(":")
            self.state.set_pending(user.id, f"car:{field}:{car_id}")
            prompts = {
                "vin": "Пришлите VIN (17 символов).",
                "engine": "Пришлите двигатель, например 2AR-FE или 2.5.",
                "year": "Пришлите год выпуска, например 2015.",
            }
            return Response.text(prompts.get(field, "Пришлите значение.") + "\n/cancel — отмена")
        if kind == "cl":  # cl:<сессия>:<вопрос>:<значение>
            session, key, value = arg.split(":", 2)
            return await self._clarify_answer(user, int(session), key, value, edit=True)
        if kind == "clt":  # clt:<сессия>:<вопрос> — ответ будет текстом
            session, key = arg.split(":", 1)
            self.state.set_pending(user.id, f"cl:{session}:{key}")
            title = QUESTIONS[key].title.lower() if key in QUESTIONS else "значение"
            return Response.text(f"Напишите {title}, например 2AR-FE или 2.5.\n/cancel — отмена")
        log.warning("unknown action %s", action)
        return Response(popup="Кнопка устарела")

    # ================================================================
    #  Команды
    # ================================================================

    async def _help(self, user: User, args: str = "") -> Response:
        return Response.text(texts.HELP)

    async def _cancel(self, user: User, args: str = "") -> Response:
        self.state.set_pending(user.id, None)
        return Response.text(texts.CANCELLED)

    def _current_car(self, user: User) -> Car | None:
        car_id = self.state.current_car_id(user.id)
        return self.cars.get(car_id) if car_id else None

    # --- Поиск ---

    async def _search_article(self, user: User, article: str) -> Response:
        if not article:
            return Response.text("Пришлите артикул, например: <code>/search 04465-33471</code>")
        result = await self.search.by_article(article)
        if not result.offers:
            text = texts.NOT_FOUND.format(article=texts.esc(article))
            if car_parsing.is_kz_plate(article):
                text += (
                    f"\n\nЕсли это госномер — привяжите машину: "
                    f"<code>/car Модель {texts.esc(article)}</code>"
                )
            return Response.text(text)
        return Response(replies=[self._search_reply(user, result)])

    async def _show_analogs(self, user: User, snapshot_id: int) -> Response:
        offer = self.snapshots.get(snapshot_id)
        if offer is None:
            return Response.text(texts.OFFER_EXPIRED)
        result = await self.search.analogs(offer.article, offer.brand)
        if len(result.offers) <= 1:
            return Response.text(f"Аналогов для {texts.esc(offer.article)} не нашлось.")
        return Response(replies=[self._search_reply(user, result)])

    def _search_reply(self, user: User, result: SearchResult) -> Reply:
        snapshot_ids = [self.snapshots.save(o) for o in result.offers]
        # Аналоги ищем от оригинала, если он есть, иначе от первого варианта
        base = next((o for o in result.offers if o.is_original), result.offers[0])
        analogs_snapshot = snapshot_ids[result.offers.index(base)]
        return views.search_reply(
            result,
            snapshot_ids,
            self._current_car(user),
            self.normal_days,
            self.currency,
            analogs_snapshot,
        )

    async def _search_by_name(self, user: User, text: str) -> Response:
        recognition = await self.recognizer.recognize(text)
        log.info(
            "recognize text_len=%d part=%s source=%s",
            len(text),
            recognition.part_key,
            recognition.source,
        )
        if recognition.part_key is None:
            return Response.text(
                "🤔 Не понял, что за деталь.\n"
                "Пришлите <b>артикул</b> или напишите по-другому, например: "
                "<i>колодки передние</i>, <i>граната левая</i>."
            )
        car = self._current_car(user)
        car_answers = self.cars.answers(car.id) if car else {}
        state = clarify.start(recognition.part_key, recognition.answers, car, car_answers)
        if state.done:
            return await self._clarify_finish(user, state, car, edit=False)
        session_id = self.sessions.create_clarify(user.id, state.to_dict())
        return Response(replies=[views.clarify_reply(session_id, state, car)])

    async def _clarify_answer(
        self, user: User, session_id: int, key: str, value: str, edit: bool
    ) -> Response:
        data = self.sessions.get_clarify(session_id)
        if data is None:
            return Response.text("Уточнение устарело. Напишите деталь заново.")
        state = clarify.apply_answer(clarify.ClarifyState.from_dict(data), key, value)
        self.sessions.update_clarify(session_id, state.to_dict())
        car = self.cars.get(state.car_id) if state.car_id else None

        # Ответы «про машину» (двигатель, КПП) запоминаем сразу
        if car and key in state.answers and QUESTIONS[key].scope == "car":
            if key == "engine":
                self.cars.update_field(car.id, "engine", state.answers[key])
                car = self.cars.get(car.id)
            else:
                self.cars.save_answer(car.id, key, state.answers[key])

        if not state.done:
            return Response(replies=[views.clarify_reply(session_id, state, car, edit=edit)])
        return await self._clarify_finish(user, state, car, edit=edit)

    async def _clarify_finish(
        self, user: User, state: clarify.ClarifyState, car: Car | None, edit: bool
    ) -> Response:
        log.info("clarify done part=%s answers=%s", state.part_key, state.answers)
        if self.catalog.is_available():
            articles = await self.catalog.find_articles(state.part_key, state.answers, car)
            if articles:
                response = Response()
                for article in articles[:3]:
                    response.replies += (await self._search_article(user, article)).replies
                return response
        has_car_questions = any(QUESTIONS[k].scope == "car" for k in state.part.questions)
        return Response(replies=[views.clarify_done_reply(state, car, has_car_questions, edit)])

    # --- Корзина ---

    async def _add_to_cart(self, user: User, snapshot_id: int) -> Response:
        offer = self.snapshots.get(snapshot_id)
        if offer is None:
            return Response.text(texts.OFFER_EXPIRED)
        car = self._current_car(user)
        result = self.cart.add(offer, user, car.id if car else None)
        items = self.cart.items()
        total = self.cart.total(items)
        log.info(
            "cart add user=%s offer=%s qty=%s car=%s",
            user.id,
            offer.offer_id,
            result.item.qty,
            car.plate if car else None,
        )

        text = (
            f"✅ В корзине: {views.offer_line(offer)} × {result.item.qty}\n"
            f"{views.car_line(car)}\n\n"
            f"Всего в корзине: {len(items)} поз. на {texts.money(total, self.currency)}"
        )
        if result.limited_by_stock:
            text += f"\n⚠️ Больше нет: на складе только {offer.stock} шт."
        reply = Reply(text, [[Button("🛒 Открыть корзину", "cart")]])
        # Сообщаем админам (кроме того, кто добавил)
        note = Reply(
            f"🛒 {texts.esc(user.name)} добавил(а): {views.offer_line(offer)} × 1\n"
            f"{views.car_line(car)}",
            [[Button("Открыть корзину", "cart")]],
        )
        notifications = [Notification(a, note) for a in self.admin_ids if a != user.id]
        return Response(replies=[reply], notifications=notifications, popup="Добавлено в корзину")

    async def _show_cart(self, user: User, edit: bool = False) -> Response:
        items = self.cart.items()
        reply = views.cart_reply(
            items, self.cart.total(items), user.is_admin, self.currency, edit=edit
        )
        return Response(replies=[reply])

    def _cart_edit(self, user: User, popup: str | None = None) -> Response:
        items = self.cart.items()
        reply = views.cart_reply(
            items, self.cart.total(items), user.is_admin, self.currency, edit=True
        )
        return Response(replies=[reply], popup=popup)

    def _change_qty(self, user: User, item_id: int, delta: int) -> Response:
        _, hint = self.cart.change_qty(item_id, delta)
        log.info("cart qty user=%s item=%s delta=%s", user.id, item_id, delta)
        return self._cart_edit(user, popup=hint)

    def _delete_item(self, user: User, item_id: int) -> Response:
        removed = self.cart.remove(item_id)
        log.info("cart delete user=%s item=%s removed=%s", user.id, item_id, removed)
        return self._cart_edit(user, popup="Удалено" if removed else "Уже удалено")

    # --- Заказ ---

    async def _checkout_start(self, user: User) -> Response:
        if not user.is_admin:
            return Response.text(texts.ADMIN_ONLY)
        report = await self.checkout.check(user)
        if report is None:
            return Response.text("🛒 Корзина пуста — заказывать нечего.")
        return Response(replies=[views.check_reply(report, self.test_mode, self.currency)])

    async def _checkout_confirm(self, user: User, session_id: int) -> Response:
        if not user.is_admin:
            return Response.text(texts.ADMIN_ONLY)
        try:
            result = await self.checkout.confirm(session_id, user)
        except SupplierUnavailable:
            log.error("order: supplier unavailable", exc_info=True)
            return Response.text(
                "😕 Поставщик не ответил на заказ. Корзина не тронута.\n"
                "⚠️ Перед повтором загляните в личный кабинет поставщика: "
                "если заказ всё-таки появился там — не отправляйте второй раз."
            )
        except OrderRejected as e:
            log.error("order rejected: %s", e)
            return Response.text(f"❌ Поставщик отклонил заказ: {texts.esc(str(e))}")
        except SupplierError:
            log.exception("order failed")
            return Response.text(texts.INTERNAL_ERROR)

        reply = views.confirm_reply(result, self.currency)
        response = Response(replies=[reply])
        if result.message_key == "sent" and result.placed:
            # Сообщаем мастерам, что их позиции заказаны
            for master_id in {ln.added_by_id for ln in result.lines if ln.added_by_id}:
                if master_id == user.id:
                    continue
                mine = [ln for ln in result.lines if ln.added_by_id == master_id]
                lines = "\n".join(f"• {views.offer_line(ln.offer)} × {ln.qty}" for ln in mine)
                number = texts.esc(result.placed.supplier_order_id)
                text = f"📦 Ваши позиции заказаны (№ {number}):\n{lines}"
                response.notifications.append(Notification(master_id, Reply(text)))
        return response

    # --- Машины ---

    def _car_card(self, user: User, car_id: int, prefix: str = "") -> Response:
        car = self.cars.get(car_id)
        if car is None:
            return Response.text("Машина не найдена.")
        is_current = self.state.current_car_id(user.id) == car_id
        reply = views.car_reply(car, self.cars.answers(car_id), is_current)
        reply.text = prefix + reply.text
        return Response(replies=[reply])

    async def _car_command(self, user: User, args: str) -> Response:
        if args.lower() in ("off", "нет", "отвязать", "-"):
            self.state.set_current_car(user.id, None)
            return Response.text("🚫 Машина отвязана. Новые позиции пойдут без машины.")

        if not args:
            car = self._current_car(user)
            recent = [c for c in self.cars.recent() if not car or c.id != car.id]
            buttons = [[Button(f"🚗 {c.title}", f"car:{c.id}")] for c in recent]
            head = f"Текущая машина: <b>{texts.esc(car.title)}</b>" if car else "Машина не выбрана."
            text = f"{head}\n\nЧтобы выбрать или добавить: <code>/car Камри 123ABC01</code>" + (
                "\nИли нажмите на машину ниже:" if recent else ""
            )
            reply = Reply(text, buttons)
            if car:
                card = views.car_reply(car, self.cars.answers(car.id), True)
                return Response(replies=[card, reply])
            return Response(replies=[reply])

        parsed = car_parsing.parse_car_args(args)
        if parsed is None:
            # Может, указали только номер уже известной машины
            existing = self.cars.find_by_plate(args)
            if existing:
                self.state.set_current_car(user.id, existing.id)
                return self._car_card(user, existing.id)
            return Response.text("Не понял номер. Пример: <code>/car Камри 123ABC01</code>")
        model, plate = parsed
        existing = self.cars.find_by_plate(plate)
        if existing is None and not model:
            return Response.text(
                f"Машины {texts.esc(plate)} ещё нет. Укажите модель: "
                f"<code>/car Камри {texts.esc(plate)}</code>"
            )
        car = self.cars.create_or_update(plate, model)
        self.state.set_current_car(user.id, car.id)
        log.info("car selected user=%s plate=%s", user.id, car.plate)
        return self._car_card(user, car.id)

    # --- История ---

    async def _orders_command(self, user: User, args: str) -> Response:
        if args:
            car = self.cars.find_by_plate(args)
            if car is None:
                return Response.text(f"Машины {texts.esc(args)} нет в базе.")
            orders = self.orders.for_car(car.id)
            return Response(replies=[views.orders_reply(orders, self.currency, car)])

        orders = self.orders.recent()
        await self._refresh_statuses(orders)
        return Response(replies=[views.orders_reply(orders, self.currency)])

    async def _refresh_statuses(self, orders) -> None:
        """Обновляет статусы заказов у поставщика (если он умеет их отдавать)."""
        if not self.supplier.supports_order_status:
            return
        ids = [o.supplier_order_id for o in orders if o.supplier == self.supplier.name]
        if not ids:
            return
        try:
            statuses = await self.supplier.order_statuses(ids)
        except SupplierError:
            log.warning("cannot refresh order statuses", exc_info=True)
            return  # покажем последние сохранённые статусы
        for order in orders:
            new = statuses.get(order.supplier_order_id)
            if new and new != order.status:
                self.orders.update_status(order.id, new)
                order.status = new
