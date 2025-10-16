from flask import Flask, jsonify
import os
import requests

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

@app.route("/")
def home():
    return "Servidor MP Notifier activo ✅"

@app.route("/pagos", methods=["GET"])
def get_pagos():
    if not ACCESS_TOKEN:
        return jsonify({"error": "ACCESS_TOKEN no configurado"}), 500

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    url = "https://api.mercadopago.com/v1/payments/search?sort=date_created&criteria=desc&limit=10"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()

        pagos = []
        for pago in data.get("results", []):
            if pago.get("status") == "approved":
                pagos.append({
                    "id": pago.get("id"),
                    "estado": pago.get("status"),
                    "monto": pago.get("transaction_amount"),
                    "fecha": pago.get("date_created"),
                    "nombre": pago.get("payer", {}).get("first_name", "Desconocido")
                })

        return jsonify(pagos), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
