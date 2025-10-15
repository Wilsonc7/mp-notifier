import os, io, csv, json, datetime as dt
from functools import wraps
from collections import defaultdict
from flask import (
    Flask, request, jsonify, render_template, redirect,
    url_for, session, flash, send_from_directory, make_response
)
import requests

# =========================
# Config básica
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# Caché en memoria: { biz_id: {"ts": datetime, "rows": [..] } }
CACHE_SECONDS = 60
payments_cache = {}

# =========================
# Utilidades
# =========================
def load_users():
    if not os.path.exists(USERS_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "admin": {
                    "password": "blackdog123",
                    "role": "admin",
                    "name": "BlackDog Admin",
                    "active": True
                },
                "BlackDog": {
                    "password": "1234",
                    "role": "client",
                    "name": "BlackDog Store",
                    "token": "BlackDog-ESP32-LOCAL",
                    "mp_access_token": os.environ.get("MP_ACCESS_TOKEN", ""),
                    "active": True
                }
            }, f, ensure_ascii=False, indent=2)
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def current_user():
    return session.get("user")

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def require_role(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login"))
            if u["role"] != role:
                flash("No tenés permiso para ver esto.", "err")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

def is_admin():
    u = current_user()
    return bool(u and u["role"] == "admin")

def effective_business_id():
    if is_admin() and session.get("impersonate"):
        return session["impersonate"]
    return session.get("business_id")

def to_date(s):
    try:
        # MercadoPago iso-like, traer Z -> +00:00
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return dt.date.today()

def str_date(d):
    return d.strftime("%Y-%m-%d")

# =========================
# Mercado Pago + caché
# =========================
def _mp_fetch_all(access_token, limit=200):
    """Pide a MP hasta 'limit' más recientes y normaliza."""
    if not access_token:
        return []
    url = "https://api.mercadopago.com/v1/payments/search"
    params = {
        "sort": "date_created",
        "criteria": "desc",
        "limit": min(limit, 200)
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=25)
        if r.status_code != 200:
            app.logger.warning("MP error %s: %s", r.status_code, r.text)
            return []
        data = r.json() or {}
        out = []
        for it in data.get("results", []):
            out.append({
                "id": str(it.get("id")),
                "estado": it.get("status"),
                "monto": float(it.get("transaction_amount", 0) or 0),
                "fecha": it.get("date_created"),
                "nombre": (it.get("payer", {}) or {}).get("first_name")
            })
        return out
    except Exception as e:
        app.logger.exception("MP list error: %s", e)
        return []

def get_cached_payments(biz_id, access_token):
    """Devuelve rows cacheadas (<= CACHE_SECONDS) o refresca desde MP."""
    now = dt.datetime.utcnow()
    c = payments_cache.get(biz_id)
    if c and (now - c["ts"]).total_seconds() < CACHE_SECONDS:
        return c["rows"]
    rows = _mp_fetch_all(access_token, limit=200)
    payments_cache[biz_id] = {"ts": now, "rows": rows}
    return rows

# =========================
# Filtros, métricas y paginación
# =========================
def filter_by_range(rows, rng="30", frm=None, to=None):
    """rng: 'today' | '7' | '30' | 'custom' (usa frm/to YYYY-MM-DD)."""
    today = dt.date.today()
    if rng == "today":
        start = today
        end = today
    elif rng in ("7", "30"):
        days = int(rng)
        start = today - dt.timedelta(days=days-1)
        end = today
    elif rng == "custom" and frm and to:
        try:
            start = dt.datetime.strptime(frm, "%Y-%m-%d").date()
            end = dt.datetime.strptime(to, "%Y-%m-%d").date()
        except Exception:
            start, end = today - dt.timedelta(days=29), today
    else:
        # default últimos 30 días
        start, end = today - dt.timedelta(days=29), today

    def within(r):
        d = to_date(r.get("fecha", ""))
        return start <= d <= end

    filt = [x for x in rows if within(x)]
    return filt, start, end

def compute_metrics(rows):
    rows = [r for r in rows if r.get("estado") == "approved"]
    today = dt.date.today()
    start_week = today - dt.timedelta(days=today.weekday())
    start_month = today.replace(day=1)

    def sum_count(since_date):
        total = 0.0
        count = 0
        for r in rows:
            d = to_date(r.get("fecha", ""))
            if d >= since_date:
                total += float(r.get("monto", 0) or 0)
                count += 1
        return round(total, 2), count

    total_today, count_today = sum_count(today)
    total_week, count_week = sum_count(start_week)
    total_month, count_month = sum_count(start_month)

    # serie 14 días para charts
    daily = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        d = to_date(r.get("fecha", ""))
        if (today - d).days <= 13:
            daily[d]["total"] += float(r.get("monto", 0) or 0)
            daily[d]["count"] += 1

    series = []
    for i in range(13, -1, -1):
        d = today - dt.timedelta(days=i)
        info = daily[d]
        series.append({
            "date": d.strftime("%d/%m"),
            "total": round(info["total"], 2),
            "count": info["count"]
        })

    return {
        "today": {"total": total_today, "count": count_today},
        "week": {"total": total_week, "count": count_week},
        "month": {"total": total_month, "count": count_month},
        "series": series
    }

def paginate(rows, page=1, per_page=25):
    page = max(int(page or 1), 1)
    start = (page - 1) * per_page
    end = start + per_page
    total = len(rows)
    pages = max((total + per_page - 1) // per_page, 1)
    return rows[start:end], page, pages, total

# =========================
# Auth
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    token = request.form.get("token", "").strip()
    password = request.form.get("password", "").strip()
    users = load_users()

    # admin login con "admin" en campo token
    if token.lower() == "admin":
        admin = users.get("admin")
        if not admin or not admin.get("active", True):
            flash("Admin deshabilitado.", "err")
            return redirect(url_for("login"))
        if password != admin.get("password"):
            flash("Contraseña incorrecta.", "err")
            return redirect(url_for("login"))
        session.clear()
        session["user"] = {"id": "admin", "role": "admin", "name": admin.get("name", "Admin")}
        flash("Sesión iniciada correctamente ✅", "ok")
        return redirect(url_for("admin_dashboard"))

    # login por token de negocio
    for biz_id, u in users.items():
        if biz_id == "admin":
            continue
        if not u.get("active", True):
            continue
        if u.get("token") == token and password == u.get("password"):
            session.clear()
            session["user"] = {"id": biz_id, "role": u.get("role", "client"), "name": u.get("name", biz_id)}
            session["business_id"] = biz_id
            flash("Sesión iniciada correctamente ✅", "ok")
            return redirect(url_for("dashboard"))

    flash("Credenciales inválidas.", "err")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =========================
# Panel (cliente o admin impersonando)
# =========================
@app.route("/")
@login_required
def dashboard():
    users = load_users()
    biz_id = effective_business_id()
    if is_admin() and not biz_id:
        return redirect(url_for("admin_dashboard"))
    u = users.get(biz_id) or {}
    rows = get_cached_payments(biz_id, u.get("mp_access_token", ""))

    rng = request.args.get("range", "30")
    frm = request.args.get("from")
    to = request.args.get("to")
    page = request.args.get("page", 1, type=int)

    rows_f, start, end = filter_by_range(rows, rng, frm, to)
    metrics = compute_metrics(rows_f)
    rows_f = [r for r in rows_f if r.get("estado") == "approved"]  # tabla por defecto: aprobados
    slice_, page, pages, total = paginate(rows_f, page=page, per_page=25)

    return render_template("dashboard.html",
                           metrics=metrics,
                           rows=slice_,
                           page=page, pages=pages, total=total,
                           active_range=rng, start_date=str_date(start), end_date=str_date(end),
                           is_admin=is_admin(), business_id=biz_id,
                           business_name=u.get("name", biz_id),
                           impersonating=is_admin() and bool(session.get("impersonate")))

# =========================
# Admin global
# =========================
@app.route("/admin")
@login_required
@require_role("admin")
def admin_dashboard():
    users = load_users()
    rng = request.args.get("range", "30")
    frm = request.args.get("from")
    to = request.args.get("to")

    # tablero + métricas globales con caché por negocio
    board = []
    global_rows = []
    for biz_id, u in users.items():
        if biz_id == "admin":
            continue
        if not u.get("active", True):
            continue
        rows = get_cached_payments(biz_id, u.get("mp_access_token", ""))
        rows_f, _s, _e = filter_by_range(rows, rng, frm, to)
        global_rows.extend([r for r in rows_f if r.get("estado") == "approved"])
        m = compute_metrics(rows_f)
        board.append({
            "id": biz_id,
            "name": u.get("name", biz_id),
            "active": u.get("active", True),
            "today_total": m["today"]["total"],
            "week_total": m["week"]["total"],
            "month_total": m["month"]["total"]
        })
    global_metrics = compute_metrics(global_rows)
    board = sorted(board, key=lambda x: x["month_total"], reverse=True)
    return render_template("admin_dashboard.html",
                           board=board,
                           metrics=global_metrics,
                           active_range=rng,
                           start_date=request.args.get("from") or "",
                           end_date=request.args.get("to") or "")

# =========================
# Vista negocio (admin)
# =========================
@app.route("/admin/business/<biz_id>")
@login_required
@require_role("admin")
def admin_business_view(biz_id):
    users = load_users()
    u = users.get(biz_id)
    if not u:
        flash("Negocio no encontrado.", "err")
        return redirect(url_for("admin_dashboard"))

    rows = get_cached_payments(biz_id, u.get("mp_access_token", ""))

    rng = request.args.get("range", "30")
    frm = request.args.get("from")
    to = request.args.get("to")
    page = request.args.get("page", 1, type=int)

    rows_f, start, end = filter_by_range(rows, rng, frm, to)
    metrics = compute_metrics(rows_f)
    rows_f = [r for r in rows_f if r.get("estado") == "approved"]
    slice_, page, pages, total = paginate(rows_f, page=page, per_page=25)

    return render_template("business_view.html",
                           business_id=biz_id,
                           business=u,
                           rows=slice_,
                           page=page, pages=pages, total=total,
                           metrics=metrics,
                           active_range=rng, start_date=str_date(start), end_date=str_date(end))

# =========================
# Impersonación
# =========================
@app.route("/admin/impersonate/<biz_id>")
@login_required
@require_role("admin")
def admin_impersonate(biz_id):
    users = load_users()
    if biz_id not in users or biz_id == "admin":
        flash("Negocio inválido.", "err")
        return redirect(url_for("admin_dashboard"))
    session["impersonate"] = biz_id
    flash(f"Impersonando a {biz_id}.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/admin/stop")
@login_required
@require_role("admin")
def admin_stop_impersonate():
    session.pop("impersonate", None)
    flash("Volviste al modo administrador.", "ok")
    return redirect(url_for("admin_dashboard"))

# =========================
# Toggle activo
# =========================
@app.route("/admin/toggle/<biz_id>", methods=["POST"])
@login_required
@require_role("admin")
def admin_toggle_business(biz_id):
    users = load_users()
    if biz_id not in users or biz_id == "admin":
        return jsonify({"ok": False, "msg": "Negocio inválido"})
    users[biz_id]["active"] = not users[biz_id].get("active", True)
    save_users(users)
    # invalidar caché
    payments_cache.pop(biz_id, None)
    return jsonify({"ok": True, "active": users[biz_id]["active"]})

# =========================
# Config usuario (cambiar contraseña)
# =========================
@app.route("/config/user", methods=["GET", "POST"])
@login_required
def config_user():
    users = load_users()
    if request.method == "GET":
        return render_template("config_user.html")
    newpass = request.form.get("password", "").strip()
    if not newpass:
        flash("Contraseña inválida", "err")
        return redirect(url_for("config_user"))
    uid = "admin" if is_admin() else session.get("business_id")
    users[uid]["password"] = newpass
    save_users(users)
    flash("Contraseña actualizada.", "ok")
    return redirect(url_for("config_user"))

# =========================
# Exportar CSV (admin o dueño)
# =========================
def _authorize_export(biz_id):
    if is_admin():
        return True
    return session.get("business_id") == biz_id

def _rows_for_export(biz_id, rng, frm, to):
    users = load_users()
    u = users.get(biz_id) or {}
    rows = get_cached_payments(biz_id, u.get("mp_access_token", ""))
    rows_f, _s, _e = filter_by_range(rows, rng, frm, to)
    rows_f = [r for r in rows_f if r.get("estado") == "approved"]
    return rows_f[:500]  # límite export

@app.route("/export/<biz_id>")
@login_required
def export_csv(biz_id):
    if not _authorize_export(biz_id):
        return "Forbidden", 403
    rng = request.args.get("range", "30")
    frm = request.args.get("from")
    to = request.args.get("to")
    rows = _rows_for_export(biz_id, rng, frm, to)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Monto", "Estado", "Nombre", "ID"])
    for r in rows:
        writer.writerow([r.get("fecha"), r.get("monto"), r.get("estado"), r.get("nombre") or "", r.get("id")])
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename={biz_id}_transferencias.csv"
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    return resp

@app.route("/export_me")
@login_required
def export_me():
    biz_id = effective_business_id()
    if not biz_id:
        return "Forbidden", 403
    return export_csv(biz_id)

# =========================
# Endpoint simple para ESP32 (últimos 20 aprobados)
# =========================
@app.route("/pagos")
def pagos_plain():
    users = load_users()
    # devuelve del primer negocio activo con token
    for biz_id, u in users.items():
        if biz_id == "admin": 
            continue
        if u.get("active", True) and u.get("mp_access_token"):
            rows = get_cached_payments(biz_id, u.get("mp_access_token", ""))
            rows = [r for r in rows if r.get("estado") == "approved"]
            return jsonify(rows[:20])
    return jsonify([])

# =========================
# Static / favicon / errores
# =========================
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static", "img"),
                               "ic_launcher.png")

@app.errorhandler(403)
def _403(_e): return render_template("error.html", code=403, msg="Prohibido"), 403

@app.errorhandler(404)
def _404(_e): return render_template("error.html", code=404, msg="No encontrado"), 404

@app.errorhandler(500)
def _500(_e): return render_template("error.html", code=500, msg="Error interno"), 500

# =========================
# Main
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
