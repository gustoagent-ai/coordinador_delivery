# server.py
import os
import logging
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_ID")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

GRAPH_URL = "https://graph.facebook.com/v19.0"

# --------------------------------------------------
# Utils
# --------------------------------------------------

def send_text(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(
        f"{GRAPH_URL}/{PHONE_ID}/messages",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=10
    )


def extract_valid_number(text: str) -> str | None:
    """
    SOLO acepta formato: 569XXXXXXXX (11 dígitos)
    """
    if not text:
        return None

    match = re.search(r'\b(569\d{8})\b', text)
    return match.group(1) if match else None


def download_media(media_id: str) -> bytes | None:
    try:
        r = requests.get(
            f"{GRAPH_URL}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )
        r.raise_for_status()
        media_url = r.json()["url"]

        media = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )
        media.raise_for_status()
        return media.content
    except Exception:
        logging.exception("Error descargando media")
        return None


def upload_media(image_bytes: bytes) -> str | None:
    try:
        r = requests.post(
            f"{GRAPH_URL}/{PHONE_ID}/media",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            files={"file": ("image.jpg", image_bytes, "image/jpeg")},
            data={"messaging_product": "whatsapp"},
            timeout=10
        )
        r.raise_for_status()
        return r.json()["id"]
    except Exception:
        logging.exception("Error subiendo media")
        return None


def send_image(to: str, media_id: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id}
    }
    requests.post(
        f"{GRAPH_URL}/{PHONE_ID}/messages",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=10
    )


# --------------------------------------------------
# Webhook
# --------------------------------------------------

@app.route("/webhook", methods=["GET"])
def verify():
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = msg["from"]

        image = msg.get("image")
        text = msg.get("text", {}).get("body")

        # 1️⃣ Validación imagen
        if not image:
            send_text(
                sender,
                "❌ Debes enviar una IMAGEN junto al número de destino.\nEjemplo: 56912345678"
            )
            return jsonify(ok=True), 200

        # 2️⃣ Validación texto
        if not text:
            send_text(
                sender,
                "❌ Debes enviar el NÚMERO de destino junto a la imagen.\nEjemplo: 56912345678"
            )
            return jsonify(ok=True), 200

        # 3️⃣ Validación número
        destination = extract_valid_number(text)
        if not destination:
            send_text(
                sender,
                "❌ Formato inválido.\nUsa solo: 569XXXXXXXX (11 dígitos)"
            )
            return jsonify(ok=True), 200

        # 4️⃣ Procesamiento
        image_bytes = download_media(image["id"])
        if not image_bytes:
            send_text(sender, "❌ Error al procesar la imagen.")
            return jsonify(ok=True), 200

        new_media_id = upload_media(image_bytes)
        if not new_media_id:
            send_text(sender, "❌ Error al subir la imagen.")
            return jsonify(ok=True), 200

        send_image(destination, new_media_id)

        send_text(sender, f"✅ Imagen enviada correctamente a {destination}")

    except Exception:
        logging.exception("Error procesando webhook")
        # Evitamos bucle infinito
    return jsonify(ok=True), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
