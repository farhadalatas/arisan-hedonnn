from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import uuid


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("ARISAN_PORT", "8080"))
ENVIRONMENT = os.environ.get("ARISAN_ENV", "local").strip().lower()
HOST = os.environ.get("ARISAN_HOST", "127.0.0.1" if ENVIRONMENT == "production" else "0.0.0.0")
SECURE_COOKIE = os.environ.get("ARISAN_SECURE_COOKIE", "1" if ENVIRONMENT == "production" else "0") == "1"
ALLOWED_HOSTS = {item.strip().lower() for item in os.environ.get("ARISAN_ALLOWED_HOSTS", "").split(",") if item.strip()}
ALLOWED_ORIGINS = {item.strip().rstrip("/") for item in os.environ.get("ARISAN_ALLOWED_ORIGINS", "").split(",") if item.strip()}
MAX_BODY_BYTES = 256 * 1024
MAX_PARTICIPANTS = 500
SESSION_TTL_SECONDS = 12 * 60 * 60
LEGACY_SESSION_FILE = ROOT / "arisan-live-session.json"
DATABASE_FILE = ROOT / "arisan-hedonnn.db"
PID_FILE = ROOT / "arisan-server.pid"
DRAW_DURATION_MS = 10000
PASSWORD_ITERATIONS = 310_000

rate_buckets = {}
rate_lock = threading.Lock()
event_lock = threading.RLock()


def inline_hash(tag_name):
    html_file = ROOT / "arisan-hedonnn-v4.html"
    if not html_file.exists():
        return ""
    content = html_file.read_bytes()
    opening = f"<{tag_name}>".encode("ascii")
    closing = f"</{tag_name}>".encode("ascii")
    start = content.find(opening)
    end = content.find(closing, start + len(opening))
    if start < 0 or end < 0:
        return ""
    block = content[start + len(opening):end]
    digest = base64.b64encode(hashlib.sha256(block).digest()).decode("ascii")
    return f"'sha256-{digest}'"


SCRIPT_HASH = inline_hash("script")
STYLE_HASH = inline_hash("style")

OPENING_CHAT = {
    "from": "ai",
    "text": "Halo, gue siap jadi pemandu. Masukkan nama peserta, pilih mode kocok, lalu tekan Kocok Toples.",
}


def fresh_state():
    return {
        "participants": [],
        "drawn": [],
        "mode": "random",
        "chat": [dict(OPENING_CHAT)],
        "activityLog": [],
    }


def now_ms():
    return int(time.time() * 1000)


def now_seconds():
    return int(time.time())


def normalize_name(name):
    return " ".join(str(name).strip().split())[:80]


def normalize_email(value):
    email = str(value or "").strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return ""
    return email


def sanitize_message(message):
    return {
        "from": "user" if message.get("from") == "user" else "ai",
        "text": str(message.get("text", ""))[:500],
    }


def sanitize_state(raw):
    cleaned = fresh_state()
    if not isinstance(raw, dict):
        return cleaned
    seen = set()
    participants = []
    raw_participants = raw.get("participants", [])
    if not isinstance(raw_participants, list):
        raw_participants = []
    for name in raw_participants[:MAX_PARTICIPANTS]:
        clean = normalize_name(name)
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            participants.append(clean)
    participant_names = {name.casefold() for name in participants}
    drawn = []
    for item in raw.get("drawn", []):
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get("name", ""))
        if not name or name.casefold() not in participant_names:
            continue
        drawn.append({
            "name": name,
            "mode": "ordered" if item.get("mode") == "ordered" else "random",
            "time": str(item.get("time", "-"))[:32],
        })
    chat = [sanitize_message(item) for item in raw.get("chat", []) if isinstance(item, dict) and item.get("text")]
    activity_log = []
    for item in raw.get("activityLog", []):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        activity_log.append({
            "key": str(item.get("key", ""))[:100],
            "text": str(item.get("text", ""))[:500],
            "time": str(item.get("time", "-"))[:64],
        })
    cleaned.update({
        "participants": participants,
        "drawn": drawn,
        "mode": "ordered" if raw.get("mode") == "ordered" else "random",
        "chat": chat[-60:] if chat else [dict(OPENING_CHAT)],
        "activityLog": activity_log[-200:],
    })
    return cleaned


def database():
    conn = sqlite3.connect(DATABASE_FILE, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


def init_database():
    with database() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspace_members (
                workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner','admin','operator','viewer')),
                created_at INTEGER NOT NULL,
                PRIMARY KEY (workspace_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_sessions_expiry ON user_sessions(expires_at);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','live','completed','archived')),
                state_json TEXT NOT NULL,
                live_draw_json TEXT,
                last_winner_json TEXT,
                created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_workspace ON events(workspace_id, updated_at DESC);
        """)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)", (now_seconds(),))


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user_session(conn, user_id):
    raw_token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = now_seconds()
    conn.execute(
        "INSERT INTO user_sessions(token_hash,user_id,csrf_token,expires_at,created_at,last_seen_at) VALUES(?,?,?,?,?,?)",
        (token_hash(raw_token), user_id, csrf, now + SESSION_TTL_SECONDS, now, now),
    )
    return raw_token, csrf


def session_cookie(raw_token, max_age=SESSION_TTL_SECONDS):
    value = f"arisan_user={raw_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
    if SECURE_COOKIE:
        value += "; Secure"
    return value


def rate_limit(key, limit, window_seconds):
    now = time.monotonic()
    with rate_lock:
        bucket = [stamp for stamp in rate_buckets.get(key, []) if now - stamp < window_seconds]
        if len(bucket) >= limit:
            rate_buckets[key] = bucket
            return False
        bucket.append(now)
        rate_buckets[key] = bucket
        return True


def is_allowed_host(host_header):
    if not host_header:
        return False
    hostname = host_header.rsplit(":", 1)[0].strip("[]").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname in ALLOWED_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return ENVIRONMENT != "production" and (address.is_private or address.is_loopback)
    except ValueError:
        return False


def winner_copy(name):
    templates = [
        ("Pecah! Nama yang ditunggu akhirnya keluar!", f"{name}, silakan maju dengan senyum paling mahal. Giliran hedon resmi jatuh ke tangan lo!"),
        ("Jeng jeng jeng... pemenangnya adalah!", f"{name} berhasil ditarik dari toples keramat. Satu ruangan wajib kasih tepuk tangan!"),
        ("Toples sudah bicara, semua harap minggir!", f"Malam ini milik {name}. Nama keluar, vibes naik, arisan makin panas!"),
        ("Selamat! Rezeki arisan merapat!", f"{name}, status lo sekarang bukan peserta biasa. Lo adalah bintang kocokan hari ini!"),
        ("Breaking news dari toples!", f"{name} baru saja keluar sebagai nama pilihan. Hadirin, kasih applause yang niat!"),
        ("Lampu sorot ke tengah, kita punya nama!", f"{name}, toples memilih lo dengan penuh drama. Ini bukan kaleng-kaleng!"),
    ]
    label, sub = random.choice(templates)
    return {"label": label, "sub": sub}


def load_event(conn, event_id, workspace_id):
    row = conn.execute(
        "SELECT * FROM events WHERE id=? AND workspace_id=?",
        (event_id, workspace_id),
    ).fetchone()
    if not row:
        return None
    try:
        state = sanitize_state(json.loads(row["state_json"]))
        live_draw = json.loads(row["live_draw_json"]) if row["live_draw_json"] else None
        last_winner = json.loads(row["last_winner_json"]) if row["last_winner_json"] else None
    except (TypeError, json.JSONDecodeError):
        state, live_draw, last_winner = fresh_state(), None, None
    return {"row": row, "state": state, "liveDraw": live_draw, "lastWinner": last_winner}


def save_event(conn, runtime):
    conn.execute(
        "UPDATE events SET state_json=?,live_draw_json=?,last_winner_json=?,updated_at=? WHERE id=?",
        (
            json.dumps(runtime["state"], ensure_ascii=False, separators=(",", ":")),
            json.dumps(runtime["liveDraw"], ensure_ascii=False, separators=(",", ":")) if runtime["liveDraw"] else None,
            json.dumps(runtime["lastWinner"], ensure_ascii=False, separators=(",", ":")) if runtime["lastWinner"] else None,
            now_seconds(),
            runtime["row"]["id"],
        ),
    )


def add_ai_message(runtime, text):
    runtime["state"]["chat"].append({"from": "ai", "text": text})
    runtime["state"]["chat"] = runtime["state"]["chat"][-60:]


def available_names(runtime):
    used = {item["name"] for item in runtime["state"]["drawn"]}
    return [name for name in runtime["state"]["participants"] if name not in used]


def finalize_draw_if_ready(runtime):
    live_draw = runtime["liveDraw"]
    if not live_draw or now_ms() < live_draw["revealAt"]:
        return False
    winner = live_draw["winner"]
    if not any(item["name"] == winner for item in runtime["state"]["drawn"]):
        runtime["state"]["drawn"].append({"name": winner, "mode": live_draw["mode"], "time": time.strftime("%H:%M")})
        runtime["state"]["activityLog"].append({
            "key": f"winner-{winner}-{now_seconds()}",
            "text": f"{winner} keluar sebagai pemenang",
            "time": time.strftime("%d/%m/%Y %H:%M"),
        })
        runtime["state"]["activityLog"] = runtime["state"]["activityLog"][-200:]
        add_ai_message(runtime, f"{live_draw['label']} {live_draw['sub']}")
    runtime["lastWinner"] = {
        "id": live_draw["id"], "winner": winner, "label": live_draw["label"], "sub": live_draw["sub"],
        "revealedAt": live_draw["revealAt"], "expiresAt": now_ms() + 45000,
    }
    runtime["liveDraw"] = None
    return True


def event_snapshot(runtime):
    last_winner = runtime["lastWinner"]
    visible_winner = last_winner if last_winner and now_ms() <= last_winner.get("expiresAt", 0) else None
    return {
        "ok": True,
        "serverNow": now_ms(),
        "state": runtime["state"],
        "liveDraw": runtime["liveDraw"],
        "lastWinner": visible_winner,
        "hasSavedSession": True,
        "event": {"id": runtime["row"]["id"], "name": runtime["row"]["name"]},
    }


def start_draw(runtime):
    finalize_draw_if_ready(runtime)
    if runtime["liveDraw"]:
        return event_snapshot(runtime)
    names = available_names(runtime)
    if not names:
        add_ai_message(runtime, "Belum ada nama tersisa untuk dikocok. Tambahkan peserta atau mulai Sesi Baru dulu.")
        return event_snapshot(runtime)
    winner = names[0] if runtime["state"]["mode"] == "ordered" else random.choice(names)
    copy = winner_copy(winner)
    started = now_ms()
    runtime["liveDraw"] = {
        "id": f"draw-{started}-{random.randint(1000,9999)}", "startedAt": started,
        "revealAt": started + DRAW_DURATION_MS, "winner": winner,
        "mode": runtime["state"]["mode"], "label": copy["label"], "sub": copy["sub"],
    }
    add_ai_message(runtime, "Surprise mode dimulai. Toples dikocok, semua device ikut nonton reveal yang sama.")
    return event_snapshot(runtime)


class RequestProblem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class ArisanHandler(SimpleHTTPRequestHandler):
    server_version = "ArisanServer/5"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    @property
    def route(self):
        return urlsplit(self.path).path

    def end_headers(self):
        script_policy = f" 'self' {SCRIPT_HASH}" if SCRIPT_HASH else " 'self'"
        style_policy = f" 'self' {STYLE_HASH}" if STYLE_HASH else " 'self'"
        csp = (
            f"default-src 'self'; script-src{script_policy}; style-src{style_policy}; "
            "style-src-attr 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if SECURE_COOKIE:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def send_json(self, payload, status=200, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def reject(self, status, message):
        self.send_json({"ok": False, "error": message}, status=status)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def valid_host(self):
        if is_allowed_host(self.headers.get("Host", "")):
            return True
        self.reject(400, "Host tidak diizinkan.")
        return False

    def valid_origin(self, required=False):
        origin = self.headers.get("Origin")
        if not origin:
            if required:
                self.reject(403, "Origin wajib untuk request ini.")
                return False
            return True
        if origin.rstrip("/") in ALLOWED_ORIGINS:
            return True
        try:
            origin_host = urlsplit(origin).netloc.lower()
        except ValueError:
            origin_host = ""
        if origin_host == self.headers.get("Host", "").lower():
            return True
        self.reject(403, "Origin tidak diizinkan.")
        return False

    def client_key(self, scope):
        return f"{scope}:{self.client_address[0]}"

    def user_session(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("arisan_user")
        if not morsel:
            return None
        hashed = token_hash(morsel.value)
        now = now_seconds()
        with database() as conn:
            conn.execute("DELETE FROM user_sessions WHERE expires_at<=?", (now,))
            row = conn.execute("""
                SELECT s.token_hash,s.csrf_token,s.expires_at,s.last_seen_at,
                       u.id AS user_id,u.name AS user_name,u.email,
                       w.id AS workspace_id,w.name AS workspace_name,m.role
                FROM user_sessions s
                JOIN users u ON u.id=s.user_id AND u.status='active'
                JOIN workspace_members m ON m.user_id=u.id
                JOIN workspaces w ON w.id=m.workspace_id
                WHERE s.token_hash=?
                ORDER BY w.created_at ASC LIMIT 1
            """, (hashed,)).fetchone()
            if row and now - row["last_seen_at"] > 300:
                conn.execute("UPDATE user_sessions SET last_seen_at=? WHERE token_hash=?", (now, hashed))
            return dict(row) if row else None

    def require_user(self, csrf=False):
        session = self.user_session()
        if not session:
            self.reject(401, "Login pengguna diperlukan.")
            return None
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, session["csrf_token"]):
                self.reject(403, "Token keamanan tidak valid.")
                return None
        return session

    def selected_event_id(self, conn, session):
        requested = self.headers.get("X-Arisan-Event", "").strip()
        if requested:
            row = conn.execute("SELECT id FROM events WHERE id=? AND workspace_id=?", (requested, session["workspace_id"])).fetchone()
            return row["id"] if row else None
        row = conn.execute(
            "SELECT id FROM events WHERE workspace_id=? AND status!='archived' ORDER BY updated_at DESC LIMIT 1",
            (session["workspace_id"],),
        ).fetchone()
        return row["id"] if row else None

    def read_json(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestProblem(415, "Content-Type harus application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestProblem(400, "Content-Length tidak valid.") from error
        if length < 0 or length > MAX_BODY_BYTES:
            raise RequestProblem(413, "Request terlalu besar.")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestProblem(400, "JSON tidak valid.") from error
        if not isinstance(payload, dict):
            raise RequestProblem(400, "Payload harus berupa object JSON.")
        return payload

    def serve_route(self, file_name):
        original = self.path
        self.path = "/" + file_name
        try:
            super().do_GET()
        finally:
            self.path = original

    def do_GET(self):
        if not self.valid_host():
            return
        if self.route in {"/api/account/status", "/api/auth/status"}:
            session = self.user_session()
            if self.route == "/api/auth/status":
                self.send_json({"ok": True, "required": True, "authenticated": bool(session), "csrfToken": session["csrf_token"] if session else ""})
            else:
                self.send_json({"ok": True, "authenticated": bool(session), "csrfToken": session["csrf_token"] if session else "", "user": {"name": session["user_name"], "email": session["email"]} if session else None})
            return
        if self.route == "/api/dashboard":
            session = self.require_user()
            if not session:
                return
            with database() as conn:
                rows = conn.execute("SELECT id,name,status,state_json,created_at,updated_at FROM events WHERE workspace_id=? AND status!='archived' ORDER BY updated_at DESC", (session["workspace_id"],)).fetchall()
            events = []
            for row in rows:
                try:
                    event_state = sanitize_state(json.loads(row["state_json"]))
                except json.JSONDecodeError:
                    event_state = fresh_state()
                events.append({"id": row["id"], "name": row["name"], "status": row["status"], "participants": len(event_state["participants"]), "winners": len(event_state["drawn"]), "updatedAt": row["updated_at"]})
            self.send_json({"ok": True, "csrfToken": session["csrf_token"], "user": {"name": session["user_name"], "email": session["email"]}, "workspace": {"id": session["workspace_id"], "name": session["workspace_name"], "role": session["role"]}, "events": events})
            return
        if self.route == "/api/state":
            session = self.require_user()
            if not session:
                return
            if not rate_limit(self.client_key("state-read"), 180, 60):
                self.reject(429, "Terlalu banyak request.")
                return
            with event_lock, database() as conn:
                event_id = self.selected_event_id(conn, session)
                runtime = load_event(conn, event_id, session["workspace_id"]) if event_id else None
                if not runtime:
                    self.reject(404, "Acara tidak ditemukan.")
                    return
                if finalize_draw_if_ready(runtime):
                    save_event(conn, runtime)
                self.send_json(event_snapshot(runtime))
            return
        if self.route.startswith("/api/"):
            self.reject(404, "Endpoint tidak dikenal.")
            return
        public_pages = {"/": "home.html", "/index.html": "home.html", "/login": "login.html", "/register": "register.html"}
        public_files = {"/site.css": "site.css", "/site.js": "site.js"}
        if self.route in public_pages:
            self.serve_route(public_pages[self.route])
            return
        if self.route in public_files:
            self.serve_route(public_files[self.route])
            return
        if self.route == "/dashboard":
            if not self.user_session():
                self.redirect("/login?next=/dashboard")
                return
            self.serve_route("dashboard.html")
            return
        if self.route in {"/app", "/arisan-hedonnn-v4.html"}:
            if not self.user_session():
                self.redirect("/login?next=/app")
                return
            self.serve_route("arisan-hedonnn-v4.html")
            return
        self.reject(404, "File tidak ditemukan.")

    def do_HEAD(self):
        if not self.valid_host():
            return
        if self.route in {"/", "/index.html", "/login", "/register", "/dashboard", "/app", "/arisan-hedonnn-v4.html", "/site.css", "/site.js"}:
            self.send_response(200)
            self.end_headers()
            return
        self.reject(404, "File tidak ditemukan.")

    def do_POST(self):
        if not self.valid_host() or not self.valid_origin(required=True):
            return
        try:
            payload = self.read_json()
            if self.route == "/api/account/register":
                if not rate_limit(self.client_key("register"), 5, 900):
                    self.reject(429, "Terlalu banyak pendaftaran. Coba lagi nanti.")
                    return
                name = normalize_name(payload.get("name", ""))
                email = normalize_email(payload.get("email", ""))
                password = str(payload.get("password", ""))
                workspace_name = normalize_name(payload.get("workspace", "")) or f"Workspace {name}"
                if len(name) < 2:
                    raise RequestProblem(400, "Nama minimal 2 karakter.")
                if not email:
                    raise RequestProblem(400, "Format email tidak valid.")
                if len(password) < 10 or len(password) > 128:
                    raise RequestProblem(400, "Password harus 10-128 karakter.")
                now = now_seconds()
                user_id, workspace_id, event_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
                with database() as conn:
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        first_user = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"] == 0
                        conn.execute("INSERT INTO users(id,name,email,password_hash,created_at,updated_at) VALUES(?,?,?,?,?,?)", (user_id, name, email, hash_password(password), now, now))
                        conn.execute("INSERT INTO workspaces(id,name,owner_user_id,created_at,updated_at) VALUES(?,?,?,?,?)", (workspace_id, workspace_name, user_id, now, now))
                        conn.execute("INSERT INTO workspace_members(workspace_id,user_id,role,created_at) VALUES(?,?,?,?)", (workspace_id, user_id, "owner", now))
                        initial_state = fresh_state()
                        if first_user and LEGACY_SESSION_FILE.exists():
                            try:
                                initial_state = sanitize_state(json.loads(LEGACY_SESSION_FILE.read_text(encoding="utf-8")))
                            except (OSError, json.JSONDecodeError):
                                pass
                        conn.execute("INSERT INTO events(id,workspace_id,name,status,state_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (event_id, workspace_id, "Acara Pertama", "draft", json.dumps(initial_state, ensure_ascii=False, separators=(",", ":")), user_id, now, now))
                        raw_token, csrf = create_user_session(conn, user_id)
                        conn.commit()
                    except sqlite3.IntegrityError:
                        conn.rollback()
                        self.reject(409, "Email sudah terdaftar.")
                        return
                self.send_json({"ok": True, "csrfToken": csrf, "next": "/dashboard"}, status=201, extra_headers={"Set-Cookie": session_cookie(raw_token)})
                return
            if self.route == "/api/account/login":
                if not rate_limit(self.client_key("login"), 7, 300):
                    self.reject(429, "Terlalu banyak percobaan login. Coba lagi beberapa menit.")
                    return
                email = normalize_email(payload.get("email", ""))
                password = str(payload.get("password", ""))
                with database() as conn:
                    user = conn.execute("SELECT id,password_hash,status FROM users WHERE email=?", (email,)).fetchone()
                    if not user or user["status"] != "active" or not verify_password(password, user["password_hash"]):
                        time.sleep(0.35)
                        self.reject(401, "Email atau password salah.")
                        return
                    raw_token, csrf = create_user_session(conn, user["id"])
                self.send_json({"ok": True, "csrfToken": csrf, "next": "/dashboard"}, extra_headers={"Set-Cookie": session_cookie(raw_token)})
                return
            if self.route in {"/api/account/logout", "/api/auth/logout"}:
                session = self.require_user(csrf=True)
                if not session:
                    return
                with database() as conn:
                    conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (session["token_hash"],))
                self.send_json({"ok": True}, extra_headers={"Set-Cookie": session_cookie("", 0)})
                return
            session = self.require_user(csrf=True)
            if not session:
                return
            if not rate_limit(self.client_key("mutation"), 120, 60):
                self.reject(429, "Terlalu banyak perubahan. Tunggu sebentar.")
                return
            if self.route == "/api/events":
                event_name = normalize_name(payload.get("name", ""))
                if len(event_name) < 2:
                    raise RequestProblem(400, "Nama acara minimal 2 karakter.")
                event_id, now = str(uuid.uuid4()), now_seconds()
                with database() as conn:
                    conn.execute("INSERT INTO events(id,workspace_id,name,status,state_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (event_id, session["workspace_id"], event_name, "draft", json.dumps(fresh_state(), ensure_ascii=False, separators=(",", ":")), session["user_id"], now, now))
                self.send_json({"ok": True, "event": {"id": event_id, "name": event_name}, "next": f"/app?event={event_id}"}, status=201)
                return
            with event_lock, database() as conn:
                event_id = self.selected_event_id(conn, session)
                runtime = load_event(conn, event_id, session["workspace_id"]) if event_id else None
                if not runtime:
                    self.reject(404, "Acara tidak ditemukan atau bukan milik workspace ini.")
                    return
                if self.route == "/api/state":
                    finalize_draw_if_ready(runtime)
                    if not runtime["liveDraw"]:
                        runtime["state"] = sanitize_state(payload.get("state"))
                    save_event(conn, runtime)
                    self.send_json(event_snapshot(runtime))
                    return
                if self.route == "/api/draw/start":
                    result = start_draw(runtime)
                    save_event(conn, runtime)
                    self.send_json(result)
                    return
                if self.route == "/api/session/save":
                    finalize_draw_if_ready(runtime)
                    add_ai_message(runtime, "Sesi live sudah disimpan ke database.")
                    save_event(conn, runtime)
                    self.send_json(event_snapshot(runtime))
                    return
                if self.route == "/api/session/load":
                    add_ai_message(runtime, "Sesi database berhasil dimuat.")
                    save_event(conn, runtime)
                    self.send_json(event_snapshot(runtime))
                    return
            self.reject(404, "Endpoint tidak dikenal.")
        except RequestProblem as error:
            self.reject(error.status, error.message)
        except sqlite3.Error:
            self.reject(500, "Database sedang bermasalah.")
        except OSError:
            self.reject(500, "Penyimpanan server gagal.")
        except Exception:
            self.reject(500, "Terjadi kesalahan internal server.")

    def log_message(self, format, *args):
        if ENVIRONMENT != "production":
            super().log_message(format, *args)


class ArisanServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    if ENVIRONMENT == "production" and HOST not in {"127.0.0.1", "::1", "localhost"} and not SECURE_COOKIE:
        raise SystemExit("Production yang bind publik wajib memakai secure cookie/TLS.")
    init_database()
    server = ArisanServer((HOST, PORT), ArisanHandler)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    print(f"Arisan Hedonnn v5 local: http://127.0.0.1:{PORT}/")
    print(f"Mode: {ENVIRONMENT}; database: {DATABASE_FILE.name}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
