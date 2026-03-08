# server.py

import os
import logging
import re
import time
import requests

from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_ID")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

GRAPH_URL = "https://graph.facebook.com/v19.0"

DELIVERY_CODE = "DELIVERYGUSTO"
SESSION_DURATION = 300

delivery_sessions = {}

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


def extract_valid_number(text: str):

    if not text:
        return None

    match = re.search(r"\b569\d{8}\b", text)

    return match.group(0) if match else None


def download_media(media_id: str):

    try:

        r = requests.get(
            f"{GRAPH_URL}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )

        r.raise_for_status()

        media_url = r.json().get("url")

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


def upload_media(image_bytes):

    try:

        r = requests.post(
            f"{GRAPH_URL}/{PHONE_ID}/media",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            files={"file": ("image.jpg", image_bytes, "image/jpeg")},
            data={"messaging_product": "whatsapp"},
            timeout=10
        )

        r.raise_for_status()

        return r.json().get("id")

    except Exception:

        logging.exception("Error subiendo media")
        return None


# --------------------------------------------------
# Delivery Session
# --------------------------------------------------

def activate_delivery(sender):

    expire_time = time.time() + SESSION_DURATION

    delivery_sessions[sender] = expire_time

    send_text(
        sender,
        "📦 *Modo entrega activado*\n\n"
        "Tienes 5 minutos para enviar la foto.\n\n"
        "Formato:\n"
        "[imagen] + 569XXXXXXXX"
    )


def session_active(sender):

    expire = delivery_sessions.get(sender)

    if not expire:
        return False

    if time.time() > expire:
        del delivery_sessions[sender]
        return False

    return True


# --------------------------------------------------
# Webhook
# --------------------------------------------------

@app.route("/webhook", methods=["GET"])
def verify():

    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == VERIFY_TOKEN
    ):

        logging.info("Webhook verificado correctamente")

        return request.args.get("hub.challenge"), 200

    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json(silent=True)

    try:

        entry = data.get("entry", [])

        if not entry:
            return jsonify(ok=True), 200

        changes = entry[0].get("changes", [])

        if not changes:
            return jsonify(ok=True), 200

        value = changes[0].get("value", {})

        if "messages" not in value:
            return jsonify(ok=True), 200

        msg = value["messages"][0]

        sender = msg.get("from")

        image = msg.get("image")

        text = None

        if image and "caption" in image:
            text = image.get("caption")

        else:
            text = msg.get("text", {}).get("body")

        logging.info("Mensaje recibido de %s : %s", sender, text)

        # --------------------------------------------------
        # CLIENTE ABRE SEGUIMIENTO
        # --------------------------------------------------

        if text and text.upper().startswith("SEGUIMIENTO"):

            send_text(
                sender,
                "👋 Hola!\n\n"
                "Te avisaremos por aquí cuando tu pedido sea entregado 📦"
            )

            return jsonify(ok=True), 200

        # --------------------------------------------------
        # ACTIVACIÓN DELIVERY
        # --------------------------------------------------

        if text and text.strip().upper() == DELIVERY_CODE:

            activate_delivery(sender)

            return jsonify(ok=True), 200

        # --------------------------------------------------
        # VALIDAR SESIÓN REPARTIDOR
        # --------------------------------------------------

        if not session_active(sender):
            return jsonify(ok=True), 200

        # --------------------------------------------------
        # VALIDACIONES
        # --------------------------------------------------

        if not image:

            send_text(
                sender,
                "❌ Debes enviar una imagen del pedido.\n\nFormato:\n[imagen] + 569XXXXXXXX"
            )

            return jsonify(ok=True), 200

        if not text:

            send_text(
                sender,
                "❌ Debes incluir el número del cliente.\nEjemplo:\n56912345678"
            )

            return jsonify(ok=True), 200

        destination = extract_valid_number(text)

        if not destination:

            send_text(
                sender,
                "❌ Número inválido.\nUsa formato:\n569XXXXXXXX"
            )

            return jsonify(ok=True), 200

        # --------------------------------------------------
        # PROCESAMIENTO
        # --------------------------------------------------

        image_bytes = download_media(image["id"])

        if not image_bytes:

            send_text(sender, "❌ Error descargando la imagen.")
            return jsonify(ok=True), 200

        new_media_id = upload_media(image_bytes)

        if not new_media_id:

            send_text(sender, "❌ Error subiendo la imagen.")
            return jsonify(ok=True), 200

        send_image(destination, new_media_id)

        send_text(
            destination,
            "📦 Tu pedido fue entregado.\nAdjuntamos comprobante."
        )

        send_text(
            sender,
            f"✅ Entrega registrada correctamente.\nCliente: {destination}"
        )

        logging.info("Imagen enviada a %s", destination)

    except Exception:

        logging.exception("Error procesando webhook")

    return jsonify(ok=True), 200


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(host="0.0.0.0", port=port)
