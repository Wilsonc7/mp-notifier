from flask import Flask, jsonify, request
from datetime import datetime
import requests
import os
import json

app = Flask(__name__)

# =========================================================
# 🔧 CONFIGURACIÓN BASE
# =========================================================
ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "APP_USR-7815066182538811-101317-a99416f9647435ea507fe1c029c4315d-62679300")
PAYMENTS_FILE = "payments.json"

# =========================================================
# 🧾 GESTIÓN LOCAL DE PAGOS
# =========================================================
def load_payments():
    if not os.path.exists(PAYMENTS_FILE):
        return []
    with open(PAYMENTS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

def save_payments(data):
    with open(PAYMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================================================
# 🔄 CONSULTA DE PAGOS A MERCADO PAGO
# =========================================================
def get_recent_payments():
    url = "https://api.mercadopago.com/v1/payments/search"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    params = {
        "sort": "date_created",
        "criteria": "desc",
        "limit": 10
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return []
    data = response.json().get("results", [])
    payments = []

    for item in data:
        if item.get("status") == "approved":
            payer = item.get("payer", {}).get("first_name", "Desconocido")
            amount = item.get("transaction_amount", 0)
            date_created = item.get("date_created", "")
            date_local = datetime.strptime(date_created[:19], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")
            payments.append({
                "id": item.get("id"),
                "nombre": payer,
                "monto": amount,
                "estado": item.get("status"),
                "fecha_local": date_local
            })
    return payments

# =========================================================
# 🔐 ENDPOINT: /api/payments?token=XXXX
# =========================================================
@app.route("/api/payments", methods=["GET"])
def api_payments():
    token = request.args.get("token", "DEFAULT")
    all_payments = get_recent_payments()
    if not all_payments:
        return jsonify({"payments": []})

    # Cargar histórico local
    local_data = load_payments()

    # Registrar nuevas
    for p in all_payments:
        if p["id"] not in [x["id"] for x in local_data]:
            p["token"] = token
            local_data.insert(0, p)

    save_payments(local_data)

    # Filtrar por token (cada negocio ve solo sus pagos)
    pagos_filtrados = [x for x in local_data if x.get("token") == token]
    return jsonify(pagos_filtrados)

# =========================================================
# 🧹 ENDPOINT: BORRAR HISTORIAL (opcional)
# =========================================================
@app.route("/api/clear", methods=["POST"])
def clear_all():
    save_payments([])
    return jsonify({"status": "ok", "message": "Historial borrado"})

# =========================================================
# 🚀 TEST PAGE
# =========================================================
@app.route("/")
def home():
    return """
    <html><body style='font-family:Arial;text-align:center;background:#111;color:#eee;padding:40px'>
    <h2>💰 MP Notifier API</h2>
    <p>Servidor funcionando correctamente ✅</p>
    <p>Ejemplo: <a href='/api/payments?token=BLACKDOG-ESP32-LOCAL'>/api/payments?token=BLACKDOG-ESP32-LOCAL</a></p>
    </body></html>
    """

# =========================================================
# 🏁 MAIN
# =========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
