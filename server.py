import os, json, math, datetime as dt
from functools import wraps
from dateutil.relativedelta import relativedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
import requests

APP = Flask(__name__)
APP.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

DATA_FILE = os.path.join("data", "users.json")

# ---------- Helpers de datos ----------
def load_users():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_passwords():
    """Si hay hashes vacíos, setea por defecto y avisa para que los cambien."""
    data = load_users()
    changed = False
    if "admin" in data and not data["admin"].get("password_hash"):
        data["admin"]["password_hash"] = generate_password_hash("blackdog123")
        changed = True
    for k,v in list(data.items()):
        if v.get("role") == "client" and not v.get("password_hash"):
            v["password_hash"] = generate_password_hash("1234")
            changed = True
    if changed:
        save_users(data)
    return changed

# ---------- Auth ----------
class User:
    def __init__(self, key, payload):
        self.id = key
        self.role = payload.get("role")
        self.name = payload.get("name")
        self.token = payload.get("token")
        self.active = payload.get("active", True)
        self.mp_access_token = payload.get("mp_access_token")

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    data = load_users()
    if uid not in data:
        return None
    return User(uid, data[uid])

def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not current_user():
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap

def admin_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        u = current_user()
        if not u or u.role != "admin":
            return redirect(url_for("dashboard"))
        return f(*a, **kw)
    return wrap

@APP.before_request
def inject_user():
    g.user = current_user()

# ---------- MP API ----------
def mp_search(access_token, date_from=None, date_to=None, limit=100):
    """
    Busca pagos aprobados por fecha (rango opcional). Devuelve lista de pagos normalizada.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "sort": "date_created",
        "criteria": "desc",
        "limit": min(limit, 200),
        "status": "approved",
    }
    if date_from: params["begin_date"] = date_from
    if date_to: params["end_date"] = date_to

    url = "https://api.mercadopago.com/v1/payments/search"
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    raw = r.json().get("results", [])
    out = []
    for it in raw:
        out.append({
            "estado": it.get("status"),
            "fecha": it.get("date_created"),
            "id": it.get("id"),
            "monto": it.get("transaction_amount", 0),
            "nombre": (it.get("payer") or {}).get("first_name")
        })
    return out

def normalize_date(s):
    # "2025-10-14T11:29:32.000-04:00" -> date, local naive
    try:
        # Solo usamos la parte de fecha (YYYY-MM-DD)
        return s[:10]
    except Exception:
        return ""

# ---------- Rutas públicas / Login ----------
@APP.route("/login", methods=["GET", "POST"])
def login():
    weak = ensure_passwords()
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        password = request.form.get("password", "").strip()
        data = load_users()

        # Admin: se loguea con token "admin"
        if token == "admin" and "admin" in data:
            ah = data["admin"].get("password_hash", "")
            if ah and check_password_hash(ah, password):
                session["uid"] = "admin"
                return redirect(url_for("dashboard"))
            flash("Credenciales inválidas para admin", "err")
            return render_template("login.html", weak_passwords=weak)

        # Client: busca por token
        for k, v in data.items():
            if v.get("role") == "client" and v.get("token") == token:
                if not v.get("active", True):
                    flash("Tu negocio está suspendido. Contactá al administrador.", "err")
                    return render_template("login.html", weak_passwords=weak)
                if v.get("password_hash") and check_password_hash(v["password_hash"], password):
                    session["uid"] = k
                    return redirect(url_for("dashboard"))
        flash("Token o contraseña incorrectos.", "err")
    return render_template("login.html", weak_passwords=weak)

@APP.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@APP.route("/")
def home():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))

# ---------- Dashboard + Métricas ----------
@APP.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    if u.role == "admin":
        # Admin: mostrar métricas del primer negocio activo (o vacío si no hay)
        data = load_users()
        client = None
        for k, v in data.items():
            if v.get("role") == "client" and v.get("active", True):
                client = User(k, v)
                break
        if not client:
            flash("No hay negocios activos para mostrar métricas.", "err")
            return render_template("dashboard.html", daily=dict(total=0,count=0),
                                   weekly=dict(total=0,count=0),
                                   monthly=dict(total=0,count=0),
                                   daily_breakdown=[])
        u = client  # usar el primero encontrado (simple)
    # Cliente o admin con cliente seleccionado
    try:
        today = dt.date.today()
        start_week = today - dt.timedelta(days=today.weekday())
        start_month = today.replace(day=1)

        def fetch_range(start_date, end_date):
            # Mercado Pago espera ISO con TZ; usamos fechas sin hora y pedimos más items
            df = start_date.isoformat()+"T00:00:00.000-00:00"
            dt_ = end_date.isoformat()+"T23:59:59.000-00:00"
            return mp_search(u.mp_access_token, df, dt_, limit=200)

        # Hoy / semana / mes
        pays_today = fetch_range(today, today)
        pays_week  = fetch_range(start_week, today)
        pays_month = fetch_range(start_month, today)

        def agg(arr):
            total = sum(float(p.get("monto",0)) for p in arr)
            return {"total": total, "count": len(arr)}

        daily = agg(pays_today)
        weekly = agg(pays_week)
        monthly = agg(pays_month)

        # breakdown últimos 14 días
        daily_breakdown = []
        for i in range(13, -1, -1):
            d = today - dt.timedelta(days=i)
            dd = fetch_range(d, d)
            daily_breakdown.append({
                "date": d.isoformat(),
                "total": sum(float(p.get("monto",0)) for p in dd),
                "count": len(dd)
            })
    except Exception as e:
        flash(f"Error al consultar métricas: {e}", "err")
        daily = weekly = monthly = {"total":0,"count":0}
        daily_breakdown = []

    return render_template("dashboard.html",
                           daily=daily, weekly=weekly, monthly=monthly,
                           daily_breakdown=daily_breakdown)

# ---------- Pagos recientes ----------
@APP.route("/payments")
@login_required
def payments():
    u = current_user()
    items = []
    try:
        items = mp_search(u.mp_access_token, limit=50)
        # formatear fecha breve
        for p in items:
            p["fecha"] = p.get("fecha","")[:19].replace("T"," ")
    except Exception as e:
        flash(f"Error al consultar pagos: {e}", "err")
    return render_template("payments.html", payments=items)

# ---------- Cambio de contraseña ----------
@APP.route("/change-password", methods=["GET","POST"])
@login_required
def change_password():
    u = current_user()
    if request.method == "POST":
        cur = request.form.get("current","")
        new = request.form.get("new","")
        new2 = request.form.get("new2","")
        if new != new2:
            flash("Las nuevas contraseñas no coinciden.", "err")
            return render_template("change_password.html")
        data = load_users()
        entry = data.get(u.id)
        if not entry or not check_password_hash(entry.get("password_hash",""), cur):
            flash("Contraseña actual incorrecta.", "err")
            return render_template("change_password.html")
        entry["password_hash"] = generate_password_hash(new)
        save_users(data)
        flash("Contraseña actualizada ✅", "ok")
        return redirect(url_for("dashboard"))
    return render_template("change_password.html")

# ---------- Admin: ABM de negocios ----------
@APP.route("/admin/users", methods=["GET","POST"])
@admin_required
def admin_users():
    data = load_users()
    # no tocar admin acá
    view_users = {k: v for k,v in data.items() if k!="admin"}
    form = {}
    if request.method == "POST":
        _id = request.form["id"].strip()
        name = request.form["name"].strip()
        token = request.form["token"].strip()
        mp_at = request.form["mp_access_token"].strip()
        pw = request.form.get("password","").strip()
        active = request.form.get("active","true") == "true"

        if not _id or not name or not token or not mp_at:
            flash("Completá todos los campos requeridos.", "err")
            return render_template("admin_users.html", users=view_users, form=request.form)

        payload = data.get(_id, {"role":"client"})
        payload.update({
            "role": "client",
            "name": name,
            "token": token,
            "mp_access_token": mp_at,
            "active": active
        })
        if pw:
            payload["password_hash"] = generate_password_hash(pw)
        elif not payload.get("password_hash"):
            payload["password_hash"] = generate_password_hash("1234")  # fallback

        data[_id] = payload
        save_users(data)
        flash("Negocio guardado ✅", "ok")
        return redirect(url_for("admin_users"))

    # GET
    # Mapeo ligero para la tabla
    mapped = {}
    for k,v in view_users.items():
        mapped[k] = {
            "role": v.get("role"),
            "name": v.get("name"),
            "token": v.get("token"),
            "active": v.get("active", True)
        }
    return render_template("admin_users.html", users=mapped, form=form)

# ---------- API para el ESP32 (y alias) ----------
def api_payments_logic(token):
    data = load_users()
    # buscar negocio por token
    client = None
    for k,v in data.items():
        if v.get("role")=="client" and v.get("token")==token:
            if not v.get("active", True):
                return []
            client = v
            break
    if not client:
        return []
    items = mp_search(client.get("mp_access_token"), limit=5)
    # la app del ESP espera keys: estado, fecha, id, monto, nombre
    return items

@APP.route("/api/payments")
def api_payments():
    token = request.args.get("token","").strip()
    try:
        return jsonify(api_payments_logic(token))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/pagos")
def pagos_alias():
    # alias para compatibilidad con el firmware
    token = request.args.get("token","").strip()
    try:
        return jsonify(api_payments_logic(token))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(DATA_FILE):
        raise SystemExit("Falta data/users.json (crealo con la semilla que te pasé).")
    # inicializa hashes por defecto si están vacíos
    ensure_passwords()
    APP.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
