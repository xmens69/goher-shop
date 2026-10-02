import os
import base64
import json
import uuid
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

PAYPAL_CLIENT_ID = os.environ["PAYPAL_CLIENT_ID"]
PAYPAL_CLIENT_SECRET = os.environ["PAYPAL_CLIENT_SECRET"]
PAYPAL_ENV = os.environ.get("PAYPAL_ENV", "sandbox").lower()

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

PAYPAL_BASE = (
    "https://api-m.sandbox.paypal.com"
    if PAYPAL_ENV != "live"
    else "https://api-m.paypal.com"
)

# The price is always taken from this server-side list.
# The browser is NOT trusted to decide how much the customer should pay.
PRODUCTS = {
    "30": {"name": "30 кристаллов", "price": Decimal("1.00")},
    "80": {"name": "80 кристаллов", "price": Decimal("2.50")},
    "170": {"name": "170 кристаллов", "price": Decimal("5.00")},
    "360": {"name": "360 кристаллов", "price": Decimal("11.00")},
    "950": {"name": "950 кристаллов", "price": Decimal("25.50")},
    "2000": {"name": "2000 кристаллов", "price": Decimal("55.00")},
}


def telegram(method, data):
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=data,
        timeout=20
    )
    return response.json()


def paypal_access_token():
    response = requests.post(
        f"{PAYPAL_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        headers={
            "Accept": "application/json",
            "Accept-Language": "en_US",
        },
        data={"grant_type": "client_credentials"},
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"PayPal token error {response.status_code}: {response.text}"
        )

    return response.json()["access_token"]


def paypal_request(method, path, token, body=None, request_id=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Prefer": "return=representation",
    }

    if request_id:
        headers["PayPal-Request-Id"] = request_id

    response = requests.request(
        method,
        f"{PAYPAL_BASE}{path}",
        headers=headers,
        json=body,
        timeout=30,
    )

    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text}

    return response, data


def encode_checkout_data(product_code, quantity, player_id, contact):
    payload = {
        "p": product_code,
        "q": quantity,
        "i": player_id,
        "c": contact,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_checkout_data(custom_id):
    padding = "=" * (-len(custom_id) % 4)
    raw = base64.urlsafe_b64decode((custom_id + padding).encode())
    data = json.loads(raw.decode())
    return data


def validate_checkout(data):
    product_code = str(data.get("productCode", ""))
    quantity_raw = data.get("quantity", 1)
    player_id = str(data.get("playerId", "")).strip()
    contact = str(data.get("contact", "")).strip()

    if product_code not in PRODUCTS:
        raise ValueError("Неизвестный товар.")

    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        raise ValueError("Неверное количество товара.")

    if quantity < 1 or quantity > 20:
        raise ValueError("Количество должно быть от 1 до 20.")

    if not player_id or len(player_id) > 50:
        raise ValueError("Проверь Brawl Stars ID.")

    if not contact or len(contact) > 100:
        raise ValueError("Проверь Telegram для связи.")

    product = PRODUCTS[product_code]
    total = product["price"] * quantity

    return product_code, quantity, player_id, contact, product, total


@app.get("/")
def home():
    return open(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "index.html"
        ),
        encoding="utf-8"
    ).read()


@app.get("/paypal-config")
def paypal_config():
    # Client ID is public/browser-safe. The Secret is never returned.
    return jsonify({
        "clientId": PAYPAL_CLIENT_ID,
        "currency": "EUR",
        "environment": PAYPAL_ENV,
    })


@app.post("/telegram-webhook")
def telegram_webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if secret != WEBHOOK_SECRET:
        return "Unauthorized", 401

    update = request.get_json(silent=True) or {}
    message = update.get("message")

    if message:
        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        if text == "/start":
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "🛒 Добро пожаловать в Goher Shop!\n\n"
                        "Здесь ты сможешь получать информацию "
                        "о своих заказах."
                    )
                }
            )

        elif text == "/shop":
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "🛒 Добро пожаловать в Goher Shop!\n\n"
                        "Нажми кнопку ниже, чтобы открыть магазин:"
                    ),
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "🛍️ Открыть магазин",
                                    "url": (
                                        "https://goher-shop-production.up.railway.app"
                                    )
                                }
                            ]
                        ]
                    }
                }
            )

        elif text == "/pay":
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "💳 Оплата заказа\n\n"
                        "Открой Goher Shop и выбери товар. "
                        "Оплата производится через PayPal."
                    )
                }
            )

        elif text == "/id":
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": f"🆔 Ваш Telegram ID:\n{chat_id}"
                }
            )

    return jsonify({"ok": True})


@app.post("/api/paypal/create-order")
def paypal_create_order():
    try:
        data = request.get_json(silent=True) or {}
        product_code, quantity, player_id, contact, product, total = (
            validate_checkout(data)
        )

        custom_id = encode_checkout_data(
            product_code,
            quantity,
            player_id,
            contact,
        )

        amount = f"{total:.2f}"

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": custom_id,
                    "description": f"Goher Shop — {product['name']}",
                    "items": [
                        {
                            "name": product["name"],
                            "quantity": str(quantity),
                            "unit_amount": {
                                "currency_code": "EUR",
                                "value": f"{product['price']:.2f}",
                            },
                        }
                    ],
                    "amount": {
                        "currency_code": "EUR",
                        "value": amount,
                        "breakdown": {
                            "item_total": {
                                "currency_code": "EUR",
                                "value": amount,
                            }
                        },
                    },
                }
            ],
        }

        token = paypal_access_token()

        response, result = paypal_request(
            "POST",
            "/v2/checkout/orders",
            token,
            payload,
            request_id=str(uuid.uuid4()),
        )

        if response.status_code not in (200, 201):
            return jsonify({
                "ok": False,
                "error": result,
            }), 502

        return jsonify({
            "ok": True,
            "id": result["id"],
        })

    except (ValueError, InvalidOperation) as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    except Exception as exc:
        app.logger.exception("PayPal create order failed")
        return jsonify({
            "ok": False,
            "error": "Не удалось создать PayPal заказ.",
            "details": str(exc) if PAYPAL_ENV != "live" else None,
        }), 500


@app.post("/api/paypal/capture-order/<order_id>")
def paypal_capture_order(order_id):
    if not order_id or len(order_id) > 100:
        return jsonify({
            "ok": False,
            "error": "Неверный PayPal Order ID.",
        }), 400

    try:
        token = paypal_access_token()

        # Get the order first so the server can verify the server-created
        # product/price data before sending the capture request.
        get_response, order_data = paypal_request(
            "GET",
            f"/v2/checkout/orders/{order_id}",
            token,
        )

        if not get_response.ok:
            return jsonify({
                "ok": False,
                "error": order_data,
            }), 502

        purchase_units = order_data.get("purchase_units") or []
        if not purchase_units:
            return jsonify({
                "ok": False,
                "error": "PayPal заказ не содержит товар.",
            }), 400

        custom_id = purchase_units[0].get("custom_id", "")
        checkout = decode_checkout_data(custom_id)

        product_code = str(checkout.get("p", ""))
        quantity = int(checkout.get("q", 0))
        player_id = str(checkout.get("i", "")).strip()
        contact = str(checkout.get("c", "")).strip()

        if product_code not in PRODUCTS or quantity < 1 or quantity > 20:
            raise ValueError("Данные заказа недействительны.")

        product = PRODUCTS[product_code]
        expected_total = product["price"] * quantity

        paypal_amount = (
            purchase_units[0]
            .get("amount", {})
            .get("value", "")
        )

        if Decimal(str(paypal_amount)) != expected_total:
            return jsonify({
                "ok": False,
                "error": "Сумма PayPal заказа не совпадает.",
            }), 400

        capture_response, capture_data = paypal_request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            token,
            {},
            request_id=str(uuid.uuid4()),
        )

        if capture_response.status_code not in (200, 201):
            return jsonify({
                "ok": False,
                "error": capture_data,
            }), 502

        if capture_data.get("status") != "COMPLETED":
            return jsonify({
                "ok": False,
                "error": "Платёж не завершён.",
                "paypal": capture_data,
            }), 400

        capture_id = None
        captured_amount = None

        for unit in capture_data.get("purchase_units", []):
            for payment in unit.get("payments", {}).get("captures", []):
                if payment.get("status") == "COMPLETED":
                    capture_id = payment.get("id")
                    captured_amount = (
                        payment.get("amount", {}).get("value")
                    )
                    break
            if capture_id:
                break

        if Decimal(str(captured_amount or "0")) != expected_total:
            return jsonify({
                "ok": False,
                "error": "Проверка суммы платежа не пройдена.",
            }), 400

        text = (
            "🛒 <b>ОПЛАЧЕННЫЙ ЗАКАЗ — GOHER SHOP</b>\n\n"
            f"💎 Товар: {product['name']}\n"
            f"📦 Количество: {quantity}\n"
            f"💰 Сумма: {expected_total:.2f} €\n\n"
            f"🎮 Brawl Stars ID:\n"
            f"<code>{player_id}</code>\n\n"
            f"💬 Telegram покупателя:\n"
            f"{contact}\n\n"
            f"💳 PayPal Order ID:\n"
            f"<code>{order_id}</code>\n\n"
            f"🧾 Capture ID:\n"
            f"<code>{capture_id or 'не указан'}</code>"
        )

        telegram_result = telegram(
            "sendMessage",
            {
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "HTML",
            }
        )

        if not telegram_result.get("ok"):
            app.logger.error(
                "Payment completed but Telegram notification failed: %s",
                telegram_result
            )

        return jsonify({
            "ok": True,
            "status": "COMPLETED",
            "orderId": order_id,
            "captureId": capture_id,
            "message": "Оплата прошла успешно. Заказ отправлен продавцу.",
        })

    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return jsonify({
            "ok": False,
            "error": "Не удалось проверить данные заказа.",
            "details": str(exc) if PAYPAL_ENV != "live" else None,
        }), 400

    except Exception as exc:
        app.logger.exception("PayPal capture failed")
        return jsonify({
            "ok": False,
            "error": "Не удалось завершить оплату.",
            "details": str(exc) if PAYPAL_ENV != "live" else None,
        }), 500


# Старый endpoint оставлен для совместимости.
# Он больше не является способом оплаты: он только создаёт обычный заказ.
@app.post("/order")
def create_order():
    try:
        data = request.get_json(silent=True) or {}

        product = str(data.get("product", "Не указан"))
        quantity = data.get("quantity", 1)
        price = data.get("price", 0)
        player_id = str(data.get("playerId", "Не указан"))
        contact = str(data.get("contact", "Не указан"))

        text = (
            "🛒 <b>НОВЫЙ ЗАКАЗ — GOHER SHOP</b>\n\n"
            f"💎 Товар: {product}\n"
            f"📦 Количество: {quantity}\n"
            f"💰 Сумма: {price} €\n\n"
            f"🎮 Brawl Stars ID:\n"
            f"<code>{player_id}</code>\n\n"
            f"💬 Telegram покупателя:\n"
            f"{contact}"
        )

        result = telegram(
            "sendMessage",
            {
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "HTML",
            }
        )

        if not result.get("ok"):
            return jsonify({
                "ok": False,
                "error": result,
            }), 500

        return jsonify({
            "ok": True,
            "message": "Заказ отправлен",
        })

    except Exception as exc:
        app.logger.exception("Legacy order failed")
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


# Register the Telegram webhook when the application starts.
try:
    webhook_result = telegram(
        "setWebhook",
        {
            "url": "https://goher-shop-production.up.railway.app/telegram-webhook",
            "secret_token": WEBHOOK_SECRET,
        }
    )
    app.logger.info("Telegram webhook: %s", webhook_result)
except Exception:
    app.logger.exception("Could not set Telegram webhook at startup")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
                                )
        
