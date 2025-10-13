from flask import Flask, request, jsonify
import requests, time, threading

app = Flask(__name__)

# ⚠️ Reemplazá esto por tu Access Token de producción de Mercado Pago
ACCESS_TOKEN = "TU_ACCESS_TOKEN_DE_PRODUCCION"

# Endpoint para consultar los pagos más recientes
MP_URL = "https://api.mercadopago.com/v1/payments/search?sort=date_created&criteria=desc&limit=5"

def consultar_pagos():
    """Consulta cada 20 segundos los últimos pagos recibidos"""
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
                    pago = data["results"][0]
                    nombre = pago.get("payer", {}).get("first_name", "Desconocido")
                    monto = pago.get("transaction_amount", 0)
                    estado = pago.get("status", "desconocido")
                    print(f"✅ Pago detectado: {nombre} - ${monto} - Estado: {estado}")
            else:
                print(f"❌ Error {r.status_code}: {r.text}")
        except Exception as e:
            print("⚠️ Error de conexión:", e)
        time.sleep(20)

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe notificaciones de Mercado Pago"""
    data = request.get_json()
    print("📩 Webhook recibido:", data)
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def home():
    return jsonify({"msg": "Servidor de notificaciones activo ✅"}), 200

if __name__ == "__main__":
    threading.Thread(target=consultar_pagos, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
