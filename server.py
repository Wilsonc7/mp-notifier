from flask import Flask, jsonify, request
import requests
import os

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Servidor MP Notifier funcionando correctamente"})

@app.route('/pagos', methods=['GET'])
def pagos():
    try:
        url = "https://api.mercadopago.com/v1/payments/search"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }
        params = {
            "sort": "date_created",
            "criteria": "desc",
            "limit": 10
        }

        r = requests.get(url, headers=headers, params=params)
        data = r.json()

        pagos = []
        for result in data.get("results", []):
            if result.get("status") == "approved":
                pago = {
                    "id": result.get("id"),
                    "estado": result.get("status"),
                    "monto": result.get("transaction_amount"),
                    "fecha": result.get("date_created"),
                    "nombre": result.get("payer", {}).get("first_name", "Desconocido")
                }
                pagos.append(pago)

        return jsonify(pagos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
