from flask import Flask, request, jsonify
import requests, time, threading, json, os
from datetime import datetime

app = Flask(__name__)

# ✅ Access Token de PRODUCCIÓN de Mercado Pago
ACCESS_TOKEN = "APP_USR-7815066182538811-101317-a99416f9647435ea507fe1c029c4315d-62679300"

# URL para consultar los pagos más recientes
MP_URL = "https://api.mercadopago.com/v1/payments/search?sort=date_created&criteria=desc&limit=5"
ARCHIVO_PAGOS = "pagos.json"


def guardar_pago(pago):
    """Guarda los pagos detectados en un archivo JSON local."""
    try:
        # Crea el archivo si no existe
        if not os.path.exists(ARCHIVO_PAGOS):
            with open(ARCHIVO_PAGOS, "w") as f:
                json.dump([], f)

        with open(ARCHIVO_PAGOS, "r") as f:
            historial = json.load(f)

        # Verificar si el pago ya fue registrado
        if any(p["id"] == pago["id"] for p in historial):
            return

        historial.append(pago)

        with open(ARCHIVO_PAGOS, "w") as f:
            json.dump(historial, f, indent=4)

        print(f"💾 Pago guardado: ID {pago['id']} - ${pago['monto']} - {pago['nombre']}")

    except Exception as e:
        print("⚠️ Error guardando pago:", e)


def consultar_pagos():
    """Consulta los últimos pagos cada 20 segundos."""
    while True:
        try:
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }
            r = requests.get(MP_URL, headers=headers)
            if r.status_code == 200:
                data = r.json()
                if "results" in data and len(data["results"]) > 0:
                    pago_api = data["results"][0]
                    pago = {
                        "id": pago_api.get("id"),
                        "nombre": pago_api.get("payer", {}).get("first_name", "Desconocido"),
                        "monto": pago_api.get("transaction_amount", 0),
                        "estado": pago_api.get("status", "desconocido"),
                        "fecha": pago_api.get("date_created", "")
                    }
                    print(f"✅ Pago detectado: {pago['nombre']} - ${pago['monto']} - Estado: {pago['estado']}")
                    guardar_pago(pago)
            else:
                print(f"❌ Error {r.status_code}: {r.text}")
        except Exception as e:
            print("⚠️ Error de conexión:", e)
        time.sleep(20)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe notificaciones directas desde Mercado Pago."""
    data = request.get_json()
    print("📩 Webhook recibido:", data)
    if "data" in data and "id" in data["data"]:
        guardar_pago({
            "id": data["data"]["id"],
            "nombre": "Desde webhook",
            "monto": 0,
            "estado": data.get("action", "desconocido"),
            "fecha": datetime.now().isoformat()
        })
    return jsonify({"status": "ok"}), 200


@app.route("/pagos", methods=["GET"])
def ver_pagos():
    """Devuelve el historial de pagos almacenado."""
    try:
        if os.path.exists(ARCHIVO_PAGOS):
            with open(ARCHIVO_PAGOS, "r") as f:
                historial = json.load(f)
            return jsonify(historial), 200
        else:
            return jsonify({"msg": "No hay pagos registrados aún"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def home():
    return jsonify({"msg": "Servidor de notificaciones activo ✅"}), 200


if __name__ == "__main__":
    threading.Thread(target=consultar_pagos, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
