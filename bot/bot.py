import os
import requests

from flask import Flask, request, jsonify, send_from_directory 
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def telegram(method, data):
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=data,
        timeout=20
    )
    return response.json()


@app.get("/")
def home():
    return open(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "index.html"
        ),
        encoding="utf-8"
    ).read()


@app.post("/telegram-webhook")
def telegram_webhook():

    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

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
                    "text":
                        "🛒 Добро пожаловать в Goher Shop!\n\n"
                        "Здесь ты сможешь получать информацию "
                        "о своих заказах."
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


@app.post("/order")
def create_order():

    data = request.get_json(silent=True) or {}

    product = data.get("product", "Не указан")
    quantity = data.get("quantity", 1)
    price = data.get("price", 0)
    player_id = data.get("playerId", "Не указан")
    contact = data.get("contact", "Не указан")

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
            "parse_mode": "HTML"
        }
    )

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "error": result
        }), 500

    return jsonify({
        "ok": True,
        "message": "Заказ отправлен"
    })

telegram(
    "setWebhook",
    {
        "url": "https://goher-shop-production.up.railway.app/telegram-webhook",
        "secret_token": WEBHOOK_SECRET
    }
    )
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
      )
