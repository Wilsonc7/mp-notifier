from flask import Flask, jsonify, request, render_template_string, redirect, url_for, session
from datetime import datetime
import os, json

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "superclave")  # para sesiones seguras

DATA_FILE = "transfers.json"
USERS_FILE = "users.json"

# ===================== UTILIDADES =====================

def load_json(file, default):
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump(default, f, indent=2)
        return default
    with open(file, "r") as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# ===================== API DE PAGOS =====================

@app.route("/api/payments")
def get_payments():
    token = request.args.get("token")
    data = load_json(DATA_FILE, {})
    if token and token in data:
        return jsonify(data[token])
    return jsonify([])

@app.route("/api/save", methods=["POST"])
def save_payment():
    data = load_json(DATA_FILE, {})
    body = request.get_json(force=True)
    token = body.get("token", "BlackDog-ESP32-LOCAL")

    if token not in data:
        data[token] = []

    nuevo = {
        "id": body.get("id", str(int(datetime.now().timestamp()))),
        "monto": body.get("monto", 0),
        "nombre": body.get("nombre", "Desconocido"),
        "estado": body.get("estado", "approved"),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Evita duplicados
    if not any(t["id"] == nuevo["id"] for t in data[token]):
        data[token].insert(0, nuevo)
        save_json(DATA_FILE, data)
        print(f"💰 Nueva transferencia [{token}]: ${nuevo['monto']} - {nuevo['nombre']}")

    return jsonify({"ok": True})

# ===================== LOGIN =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_json(USERS_FILE, {"admin": "blackdog123"})
    if request.method == "POST":
        user = request.form.get("user")
        password = request.form.get("password")
        if user in users and users[user] == password:
            session["user"] = user
            return redirect(url_for("admin_panel"))
        return render_template_string(LOGIN_HTML, error="❌ Usuario o contraseña incorrectos")
    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===================== PANEL ADMIN =====================

@app.route("/admin")
def admin_panel():
    if "user" not in session:
        return redirect(url_for("login"))

    data = load_json(DATA_FILE, {})
    html = render_template_string(ADMIN_HTML, negocios=data, usuario=session["user"])
    return html

@app.route("/admin/clear/<token>")
def clear_business(token):
    if "user" not in session:
        return redirect(url_for("login"))
    data = load_json(DATA_FILE, {})
    if token in data:
        del data[token]
        save_json(DATA_FILE, data)
    return redirect(url_for("admin_panel"))

@app.route("/admin/clear_all")
def clear_all():
    if "user" not in session:
        return redirect(url_for("login"))
    save_json(DATA_FILE, {})
    return redirect(url_for("admin_panel"))

# ===================== HTML =====================

LOGIN_HTML = """
<!DOCTYPE html>
<html><head><meta charset='UTF-8'>
<title>Login MP Notifier</title>
<style>
body{background:#111;color:#eee;font-family:Arial;text-align:center;margin-top:80px}
form{display:inline-block;padding:20px;background:#222;border-radius:10px}
input{display:block;margin:10px auto;padding:8px;width:200px;border:none;border-radius:5px}
button{background:#0f8;color:#000;padding:8px 20px;border:none;border-radius:6px;cursor:pointer}
.error{color:#f44;margin-top:10px}
</style></head><body>
<h2>🔐 Iniciar sesión</h2>
<form method='POST'>
<input name='user' placeholder='Usuario'>
<input type='password' name='password' placeholder='Contraseña'>
<button type='submit'>Entrar</button>
{% if error %}<div class='error'>{{error}}</div>{% endif %}
</form>
</body></html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html><head><meta charset='UTF-8'>
<title>Panel Admin - MP Notifier</title>
<style>
body{background:#111;color:#eee;font-family:Arial;text-align:center;padding:20px}
table{width:95%;margin:auto;border-collapse:collapse}
th,td{border:1px solid #444;padding:6px}
th{background:#333;color:#0f8}
tr:nth-child(even){background:#1a1a1a}
a,button{color:#0f8;text-decoration:none}
.logout{position:absolute;top:10px;right:20px}
</style></head><body>
<h2>💼 Panel de Administración</h2>
<div class='logout'><a href='/logout'>Cerrar sesión</a></div>
<p>Usuario: {{usuario}}</p>
{% if negocios %}
{% for token, transfers in negocios.items() %}
<h3>{{token}}</h3>
<a href='/admin/clear/{{token}}' onclick="return confirm('¿Borrar todas las transferencias de {{token}}?')">🗑️ Borrar este negocio</a>
<table>
<tr><th>Fecha</th><th>Monto</th><th>Nombre</th><th>Estado</th></tr>
{% for t in transfers %}
<tr><td>{{t.fecha}}</td><td>${{t.monto}}</td><td>{{t.nombre}}</td><td>{{t.estado}}</td></tr>
{% endfor %}
</table>
{% endfor %}
{% else %}
<p>No hay transferencias registradas.</p>
{% endif %}
<br><br>
<a href='/admin/clear_all' onclick="return confirm('¿Borrar TODO?')">🗑️ Borrar todo</a>
</body></html>
"""

# ===================== MAIN =====================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Servidor iniciado en puerto {port}")
    app.run(host="0.0.0.0", port=port)
