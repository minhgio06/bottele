import asyncio
import html
import os
import time
import sqlite3

try:
    import psycopg
except ImportError:  # SQLite vẫn được dùng khi chạy local không có DATABASE_URL
    psycopg = None
import logging
import signal
import uuid
import threading
import io
import csv
import zipfile
import random
import string
from PIL import Image, ImageDraw, ImageFont
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    ApplicationHandlerStop,
    filters,
)

# ============================================================
# CẤU HÌNH
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "h").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8207544772")) 
# Kênh bắt buộc:
# - KENH_YEU_CAU: @username hoặc ID dạng -100xxxxxxxxxx của KÊNH.
# - LINK_KENH_YEU_CAU: link mời/link tham gia kênh.
# Nếu dùng kênh riêng tư có "yêu cầu tham gia", hãy đặt LINK_KENH_YEU_CAU
# là invite link của kênh (https://t.me/+...).
KENH_THONG_BAO = os.getenv("KENH_THONG_BAO", "@rutxutiktok").strip()
KENH_YEU_CAU_1 = os.getenv("KENH_YEU_CAU_1", "@rutxutiktok").strip()
KENH_YEU_CAU_2 = os.getenv("KENH_YEU_CAU_2", "@thongbaoxutiktok").strip()
LINK_KENH_YEU_CAU_1 = os.getenv("LINK_KENH_YEU_CAU_1", "https://t.me/rutxutiktok").strip()
LINK_KENH_YEU_CAU_2 = os.getenv("LINK_KENH_YEU_CAU_2", "https://t.me/thongbaoxutiktok").strip()
KENH_YEU_CAU = KENH_YEU_CAU_2  # tương thích với code cũ
LINK_VIDEO = os.getenv("LINK_VIDEO", "https://vt.tiktok.com/ZSb6JTwaf/")
KENH_THONG_BAO_RUT = os.getenv("KENH_THONG_BAO_RUT", "@rutxutiktok").strip()
RUT_TOI_THIEU = 50_000
PHI_XAC_MINH = 30_000
PHI_XAC_MINH_SO_DU = 50_000
XAC_MINH_NGAN_HANG = os.getenv("XAC_MINH_NGAN_HANG", "ACB")
XAC_MINH_CHU_TK = os.getenv("XAC_MINH_CHU_TK", "HA QUANG MINH")
XAC_MINH_SO_TK = os.getenv("XAC_MINH_SO_TK", "25607451")

# CAPTCHA kiểu ảnh giống giao diện mẫu.
CAPTCHA_TTL_SECONDS = 5 * 60
CAPTCHA_LENGTH = 5
CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_FILE = os.getenv("DB_FILE", "bot_data.db")
# Render Webhook configuration.
# RENDER_EXTERNAL_URL is provided by Render automatically.
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
RENDER_PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip()
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = "/" + WEBHOOK_PATH
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()


def get_public_webhook_url():
    base = WEBHOOK_URL or os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "Thiếu WEBHOOK_URL và RENDER_EXTERNAL_URL. Trên Render, hãy để "
            "RENDER_EXTERNAL_URL tự cung cấp hoặc đặt WEBHOOK_URL thủ công."
        )
    return f"{base}{WEBHOOK_PATH}"


def _make_webhook_handler(application, loop):
    class _WebhookHandler(BaseHTTPRequestHandler):
        def _send(self, status, body=b"OK", content_type="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?", 1)[0] in ("/", "/health"):
                self._send(200, b"OK")
            else:
                self._send(404, b"Not Found")

        def do_HEAD(self):
            if self.path.split("?", 1)[0] in ("/", "/health"):
                self._send(200, b"")
            else:
                self._send(404, b"")

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            LOGGER.info("Incoming POST path=%s", path)
            if path != WEBHOOK_PATH:
                LOGGER.warning("Webhook path mismatch: got=%s expected=%s", path, WEBHOOK_PATH)
                self._send(404, b"Not Found")
                return

            if WEBHOOK_SECRET:
                received = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
                if received != WEBHOOK_SECRET:
                    LOGGER.warning("Webhook secret mismatch")
                    self._send(403, b"Forbidden")
                    return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 5 * 1024 * 1024:
                    LOGGER.warning("Invalid webhook body length=%s", length)
                    self._send(400, b"Invalid body")
                    return
                raw = self.rfile.read(length)
                data = __import__("json").loads(raw.decode("utf-8"))
                telegram_update = Update.de_json(data, application.bot)
                if telegram_update is None:
                    self._send(400, b"Invalid update")
                    return

                update_id = getattr(telegram_update, "update_id", None)
                update_type = (
                    "message" if telegram_update.message else
                    "callback_query" if telegram_update.callback_query else
                    "other"
                )
                LOGGER.info("Webhook received update_id=%s type=%s", update_id, update_type)

                # Process the update directly on PTB's event loop. This avoids
                # relying on the internal update queue when using a custom HTTP server.
                future = asyncio.run_coroutine_threadsafe(
                    application.process_update(telegram_update), loop
                )
                future.result(timeout=30)
                LOGGER.info("Webhook processed update_id=%s", update_id)
                self._send(200, b"OK")
            except Exception as exc:
                LOGGER.exception("Webhook update error: %r", exc)
                try:
                    self._send(500, b"Internal Server Error")
                except Exception:
                    pass

        def log_message(self, format, *args):
            return

    return _WebhookHandler


def start_webhook_server(application, loop):
    handler = _make_webhook_handler(application, loop)
    server = ThreadingHTTPServer(("0.0.0.0", RENDER_PORT), handler)
    LOGGER.info("Render webhook server listening on 0.0.0.0:%s", RENDER_PORT)
    thread = threading.Thread(
        target=server.serve_forever,
        name="render-webhook-server",
        daemon=True,
    )
    thread.start()
    return server


# Logging production-friendly: Render sẽ giữ log để truy lỗi.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("tiktok_bot")

# Conversation states
NHAP_TAI_KHOAN = 1
ADMIN_CONG_SO_DU = 10
ADMIN_TRU_SO_DU = 11
ADMIN_GUI_TB = 12
ADMIN_CONG_TAT_CA = 13
ADMIN_SUA_NGUOI = 14
ADMIN_TIM_NGUOI = 15
ADMIN_VIDEO_ADD = 16
ADMIN_TAO_MA = 17
NAP_GUI_ANH = 20
XAC_MINH_GUI_ANH = 21

CAP_BAC_CONFIG = {
    "Thành viên": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 2, "thuong_gioi_thieu": 100},
    "Leader Bạc": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 5, "thuong_gioi_thieu": 200},
    "Leader Vàng": {"xu_moi_video": 3000, "gioi_han_xem_ngay": 10, "thuong_gioi_thieu": 300},
    "Leader Bạch Kim": {"xu_moi_video": 3500, "gioi_han_xem_ngay": 20, "thuong_gioi_thieu": 500},
    "Leader Kim Cương": {"xu_moi_video": 6000, "gioi_han_xem_ngay": 30, "thuong_gioi_thieu": 1000},
    "Leader Cao Thủ": {"xu_moi_video": 8000, "gioi_han_xem_ngay": 50, "thuong_gioi_thieu": 3000},
}

MOC_CAP = [
    ("Thành viên", 0, 29),
    ("Leader Bạc", 30, 99),
    ("Leader Vàng", 100, 299),
    ("Leader Bạch Kim", 300, 499),
    ("Leader Kim Cương", 500, 999),
    ("Leader Cao Thủ", 1000, 999999),
]

GOI_NANG_CAP = {
    "goi_bac": {
        "ten": "Gói Bạc", "gia": 125000, "cap_moi": "Leader Bạc",
        "gioi_han_xem": 5, "tien_moi_video": 2500,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP BAC",
    },
    "goi_vang": {
        "ten": "Gói Vàng", "gia": 250000, "cap_moi": "Leader Vàng",
        "gioi_han_xem": 10, "tien_moi_video": 3000,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP VANG",
    },
    "goi_bachkim": {
        "ten": "Gói Bạch Kim", "gia": 1000000, "cap_moi": "Leader Bạch Kim",
        "gioi_han_xem": 20, "tien_moi_video": 3500,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP BACHKIM",
    },
    "goi_kimcuong": {
        "ten": "Gói Kim Cương", "gia": 2000000, "cap_moi": "Leader Kim Cương",
        "gioi_han_xem": 30, "tien_moi_video": 6000,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP KIMCUONG",
    },
}

HOA_HONG = {"f1": 0.03, "f2": 0.02, "f3": 0.01}


# ============================================================
# DATABASE
# ============================================================
class _DBRow(dict):
    """Row tương thích với sqlite3.Row: hỗ trợ cả row["column"] và row[0]."""
    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._columns = columns

    def __getitem__(self, key):
        if isinstance(key, int):
            return dict.__getitem__(self, self._columns[key])
        return dict.__getitem__(self, key)


class _PGResult:
    def __init__(self, cursor):
        self._cursor = cursor
        self._columns = [d.name for d in (cursor.description or [])]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _DBRow(self._columns, row)

    def fetchall(self):
        return [_DBRow(self._columns, row) for row in self._cursor.fetchall()]


class _PGConnection:
    """Adapter nhỏ để giữ nguyên phần lớn SQL hiện tại của bot."""
    def __init__(self, url):
        if psycopg is None:
            raise RuntimeError(
                "Thiếu psycopg. Hãy thêm psycopg[binary] vào requirements.txt."
            )
        self._conn = psycopg.connect(url, connect_timeout=15)
        self._conn.autocommit = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()
        return False

    @staticmethod
    def _convert_sql(query):
        # Code cũ dùng placeholder SQLite '?'. Psycopg dùng '%s'.
        query = query.replace("BEGIN IMMEDIATE", "BEGIN")
        return query.replace("?", "%s")

    def execute(self, query, params=None):
        cur = self._conn.cursor()
        cur.execute(self._convert_sql(query), params or ())
        return _PGResult(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def db():
    """
    DATABASE_URL -> Neon PostgreSQL (production/persistent).
    Không có DATABASE_URL -> SQLite local để chạy thử trên máy.
    Trên Render bắt buộc đặt DATABASE_URL để dữ liệu không bị reset.
    """
    if DATABASE_URL:
        return _PGConnection(DATABASE_URL)

    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def now_vn():
    return datetime.now(VN_TZ)


def today_vn():
    return now_vn().strftime("%d/%m/%Y")


def h(value):
    return html.escape(str(value), quote=False)


def init_db():
    """
    Khởi tạo schema trên Neon PostgreSQL.
    Nếu DATABASE_URL chưa được cấu hình thì dùng SQLite local.
    """
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                ten TEXT NOT NULL,
                username TEXT,
                cap_bac TEXT NOT NULL DEFAULT 'Thành viên',
                so_du BIGINT NOT NULL DEFAULT 0,
                video_da_xem INTEGER NOT NULL DEFAULT 0,
                video_ngay INTEGER NOT NULL DEFAULT 0,
                gioi_thieu INTEGER NOT NULL DEFAULT 0,
                ref_by BIGINT,
                ngay_vao TEXT NOT NULL,
                captcha_da_xac_minh INTEGER NOT NULL DEFAULT 0,
                ngay_reset TEXT NOT NULL,
                dang_xem INTEGER NOT NULL DEFAULT 0,
                tai_khoan TEXT,
                xac_minh_nguoi_that INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                request_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                ten TEXT NOT NULL,
                so_tien BIGINT NOT NULL,
                tai_khoan TEXT NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                request_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                ten TEXT NOT NULL,
                goi_key TEXT NOT NULL,
                cap_moi TEXT NOT NULL,
                gia BIGINT NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                photo_file_id TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_requests (
                request_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                ten TEXT NOT NULL,
                phi BIGINT NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                photo_file_id TEXT,
                phuong_thuc TEXT NOT NULL DEFAULT 'nap_30000'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_links (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)

        if DATABASE_URL:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id BIGSERIAL PRIMARY KEY,
                    admin_id BIGINT NOT NULL,
                    action TEXT NOT NULL,
                    target_user_id BIGINT,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    admin_id BIGINT,
                    delta BIGINT NOT NULL,
                    balance_after BIGINT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
            """)
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY,
                    admin_id BIGINT NOT NULL,
                    action TEXT NOT NULL,
                    target_user_id BIGINT,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_history (
                    id INTEGER PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    admin_id BIGINT,
                    delta BIGINT NOT NULL,
                    balance_after BIGINT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_rewards (
                user_id BIGINT PRIMARY KEY,
                last_checkin TEXT,
                streak INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bonus_codes (
                code TEXT PRIMARY KEY,
                amount BIGINT NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bonus_claims (
                code TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY(code, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_claims (
                user_id BIGINT NOT NULL,
                task_key TEXT NOT NULL,
                claim_date TEXT NOT NULL,
                amount BIGINT NOT NULL,
                PRIMARY KEY(user_id, task_key, claim_date)
            )
        """)
        _auto_id = "BIGSERIAL" if DATABASE_URL else "INTEGER"
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS fraud_flags (
                id {_auto_id} PRIMARY KEY, user_id BIGINT NOT NULL, flag TEXT NOT NULL,
                detail TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS video_views (
                id {_auto_id} PRIMARY KEY, video_id INTEGER, user_id BIGINT NOT NULL,
                watched_at TEXT NOT NULL, reward BIGINT NOT NULL DEFAULT 0
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS scheduled_notifications (
                id {_auto_id} PRIMARY KEY, target TEXT NOT NULL DEFAULT 'all', content TEXT NOT NULL,
                send_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS events (
                id {_auto_id} PRIMARY KEY, name TEXT NOT NULL, amount BIGINT NOT NULL DEFAULT 0,
                start_at TEXT NOT NULL, end_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            )
        """)
        if DATABASE_URL:
            # Neon/Postgres: đảm bảo bảng video cũ có ID tự tăng.
            try:
                conn.execute("ALTER TABLE video_links ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY")
            except Exception:
                pass

        # Schema migration an toàn cho database cũ.
        if DATABASE_URL:
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "xac_minh_nguoi_that INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "bi_khoa INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE verification_requests ADD COLUMN IF NOT EXISTS "
                "photo_file_id TEXT"
            )
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT"
            )
            conn.execute(
                "ALTER TABLE verification_requests ADD COLUMN IF NOT EXISTS "
                "phuong_thuc TEXT NOT NULL DEFAULT 'nap_30000'"
            )
        else:
            # SQLite không hỗ trợ IF NOT EXISTS cho ADD COLUMN.
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN xac_minh_nguoi_that "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE verification_requests ADD COLUMN photo_file_id TEXT"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN username TEXT"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN bi_khoa INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE verification_requests ADD COLUMN phuong_thuc "
                    "TEXT NOT NULL DEFAULT 'nap_30000'"
                )
            except sqlite3.OperationalError:
                pass

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_ref_by ON users(ref_by)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_withdrawals_status "
            "ON withdrawals(status, thoi_gian)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deposits_status "
            "ON deposits(status, thoi_gian)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_verification_status "
            "ON verification_requests(status, thoi_gian)"
        )

        # Sau restart/redeploy, một phiên xem đang dở không nên khóa tài khoản.
        conn.execute("UPDATE users SET dang_xem=0 WHERE dang_xem=1")

def row_to_user(row):
    return dict(row) if row else None


def get_user(user_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return row_to_user(row)


def save_user(u):
    with db() as conn:
        conn.execute(
            """
            UPDATE users SET
                ten=?,
                cap_bac=?,
                so_du=?,
                video_da_xem=?,
                video_ngay=?,
                gioi_thieu=?,
                ref_by=?,
                captcha_da_xac_minh=?,
                ngay_reset=?,
                dang_xem=?,
                tai_khoan=?,
                xac_minh_nguoi_that=?
            WHERE id=?
            """,
            (
                u["ten"],
                u["cap_bac"],
                u["so_du"],
                u["video_da_xem"],
                u["video_ngay"],
                u["gioi_thieu"],
                u["ref_by"],
                int(u["captcha_da_xac_minh"]),
                u["ngay_reset"],
                int(u["dang_xem"]),
                u["tai_khoan"],
                int(u.get("xac_minh_nguoi_that", 0)),
                u["id"],
            ),
        )


def cap_bac_tu_so_nguoi(so_nguoi):
    for ten, min_n, _ in reversed(MOC_CAP):
        if so_nguoi >= min_n:
            return ten
    return "Thành viên"


def init_user(user_id, ten, ref_by=None, username=None):
    u = get_user(user_id)
    if u:
        changed = False
        if u["ten"] != ten:
            u["ten"] = ten
            changed = True
        if "username" in u and u.get("username") != username:
            with db() as conn:
                conn.execute("UPDATE users SET ten=?, username=? WHERE id=?", (u["ten"], username, user_id))
            u["username"] = username
            changed = False
        elif changed:
            save_user(u)
        return u

    if ref_by == user_id:
        ref_by = None

    if ref_by is not None and not get_user(ref_by):
        ref_by = None

    u = {
        "id": user_id,
        "ten": ten,
        "username": username,
        "cap_bac": "Thành viên",
        "so_du": 0,
        "video_da_xem": 0,
        "video_ngay": 0,
        "gioi_thieu": 0,
        "ref_by": ref_by,
        "ngay_vao": today_vn(),
        "captcha_da_xac_minh": False,
        "ngay_reset": today_vn(),
        "dang_xem": False,
        "tai_khoan": None,
        "xac_minh_nguoi_that": False,
    }

    with db() as conn:
        conn.execute(
            """
            INSERT INTO users
            (id, ten, username, cap_bac, so_du, video_da_xem, video_ngay,
             gioi_thieu, ref_by, ngay_vao, captcha_da_xac_minh,
             ngay_reset, dang_xem, tai_khoan, xac_minh_nguoi_that)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                u["id"], u["ten"], u["username"], u["cap_bac"], u["so_du"],
                u["video_da_xem"], u["video_ngay"], u["gioi_thieu"],
                u["ref_by"], u["ngay_vao"], 0, u["ngay_reset"],
                0, None, 0,
            ),
        )

    # Thưởng người mới cấu hình được trong Admin/system_settings.
    try:
        bonus = int(get_setting("new_user_bonus", 0))
        if bonus > 0:
            with db() as conn:
                conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?", (bonus, user_id))
                bal = conn.execute("SELECT so_du FROM users WHERE id=?", (user_id,)).fetchone()[0]
            record_balance_change(user_id, None, bonus, bal, "Thưởng người dùng mới")
    except Exception:
        LOGGER.exception("Không cấp được thưởng người mới")

    if ref_by:
        ref = get_user(ref_by)
        if ref:
            ref["gioi_thieu"] += 1
            ref["so_du"] += CAP_BAC_CONFIG[ref["cap_bac"]]["thuong_gioi_thieu"]
            ref["cap_bac"] = cap_bac_tu_so_nguoi(ref["gioi_thieu"])
            save_user(ref)

    return u


def all_users():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id"
        ).fetchall()
    return [row_to_user(r) for r in rows]


def update_balance(user_id, delta):
    with db() as conn:
        conn.execute(
            "UPDATE users SET so_du = so_du + ? WHERE id=?",
            (delta, user_id),
        )


def admin_log(action, target_user_id=None, detail=""):
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO admin_logs (admin_id, action, target_user_id, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (ADMIN_ID, action, target_user_id, detail, now_vn().strftime("%d/%m/%Y %H:%M:%S")),
            )
    except Exception:
        LOGGER.exception("Không ghi được admin log")

def get_setting(key, default):
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else str(default)
    except Exception:
        return str(default)

def set_setting(key, value):
    with db() as conn:
        conn.execute(
            "INSERT INTO system_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

def record_balance_change(user_id, admin_id, delta, balance_after, reason):
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO balance_history (user_id, admin_id, delta, balance_after, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, admin_id, delta, balance_after, reason, now_vn().strftime("%d/%m/%Y %H:%M:%S")),
            )
    except Exception:
        LOGGER.exception("Không ghi được lịch sử số dư")

async def chan_user_bi_khoa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id == ADMIN_ID:
        return
    u = get_user(update.effective_user.id)
    if u and u.get("bi_khoa", 0):
        if update.callback_query:
            await update.callback_query.answer("🔒 Tài khoản đang bị khóa.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("🔒 <b>Tài khoản của bạn đang bị khóa.</b>\n\nVui lòng liên hệ hỗ trợ.", parse_mode="HTML")
        raise ApplicationHandlerStop


def reset_daily_if_needed(u):
    if u["ngay_reset"] != today_vn():
        u["video_ngay"] = 0
        u["ngay_reset"] = today_vn()
        save_user(u)


# ============================================================
# UI
# ============================================================
def menu_chinh(user_id=None):
    rows = [
        [KeyboardButton("👤 Hồ Sơ"), KeyboardButton("🔍 Xem TikTok")],
        [KeyboardButton("👥 Cấp Giới Thiệu"), KeyboardButton("👑 Nâng Cấp Bậc")],
        [KeyboardButton("🎧 Hỗ Trợ"), KeyboardButton("🔐 Nhập CaptCha")],
        [KeyboardButton("🎁 Nhiệm Vụ"), KeyboardButton("🏆 BXH")],
        [KeyboardButton("🎡 Vòng Quay"), KeyboardButton("📜 Lịch Sử")],
        [KeyboardButton("💰 Rút Tiền")],
    ]
    if user_id == ADMIN_ID:
        rows.insert(2, [KeyboardButton("🎛 QUẢN LÝ ADMIN")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def kt_kenh(user_id, context):
    """Kiểm tra người dùng đã tham gia đủ 2 kênh bắt buộc."""
    channels = [KENH_YEU_CAU_1, KENH_YEU_CAU_2]
    for channel in channels:
        if not channel:
            continue
        try:
            m = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if m.status in {"member", "administrator", "creator"}:
                continue
            if m.status == "restricted" and getattr(m, "is_member", False):
                continue
            return False
        except Exception as exc:
            LOGGER.warning("CHECK CHANNEL ERROR channel=%s: %r", channel, exc)
            return False
    return True


def _channel_url(value, fallback):
    value = (value or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("@"):
        return "https://t.me/" + value[1:]
    return fallback


def nut_kiem_tra_kenh():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 THAM GIA @rutxutiktok", url=_channel_url(KENH_YEU_CAU_1, "https://t.me/rutxutiktok"))],
        [InlineKeyboardButton("📢 THAM GIA @thongbaoxutiktok", url=_channel_url(KENH_YEU_CAU_2, "https://t.me/thongbaoxutiktok"))],
        [InlineKeyboardButton("🔎 KIỂM TRA CẢ 2 KÊNH", callback_data="kiem_tra_kenh")],
    ])


async def xu_ly_yeu_cau_tham_gia_kenh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    Xử lý Telegram Join Request.

    Bot phải được thêm làm ADMIN của kênh và có quyền quản lý
    yêu cầu tham gia. Khi người dùng bấm link yêu cầu tham gia,
    bot sẽ tự duyệt request rồi nhắn cho người dùng mở bot.
    """
    req = update.chat_join_request
    user = req.from_user

    # Chỉ xử lý request của một trong hai kênh bắt buộc.
    try:
        allowed = {str(KENH_YEU_CAU_1), str(KENH_YEU_CAU_2)}
        username = getattr(req.chat, "username", None)
        username_forms = {str(username), f"@{username}"} if username else set()
        if str(req.chat.id) not in allowed and not (allowed & username_forms):
            return
    except Exception:
        return

    try:
        await req.approve()
        LOGGER.info(
            "Đã duyệt yêu cầu tham gia kênh: user_id=%s chat_id=%s",
            user.id,
            req.chat.id,
        )
    except Exception as exc:
        LOGGER.exception("Không thể duyệt join request: %r", exc)
        return

    # Gửi hướng dẫn mở bot sau khi đã được duyệt.
    try:
        bot_username = (await context.bot.get_me()).username
        if bot_username:
            bot_link = f"https://t.me/{bot_username}?start=joined"
            text = (
                "✅ <b>YÊU CẦU THAM GIA ĐÃ ĐƯỢC DUYỆT!</b>\n\n"
                "🎉 Bạn đã được duyệt vào kênh.\n"
                "👉 Bấm nút bên dưới để mở bot và sử dụng bot."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 MỞ BOT", url=bot_link)]
            ])
            await context.bot.send_message(
                chat_id=user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except Exception as exc:
        # Người dùng có thể chưa từng /start bot nên Telegram có thể không cho bot nhắn.
        LOGGER.info(
            "Không gửi được tin nhắn sau khi duyệt join request user=%s: %r",
            user.id,
            exc,
        )


async def yeu_cau_tham_gia_kenh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiện yêu cầu tham gia kênh và cho phép người dùng kiểm tra lại."""
    u = update.effective_user
    init_user(u.id, u.full_name, username=u.username)

    if await kt_kenh(u.id, context):
        await update.message.reply_text(
            "✅ Bạn đã tham gia kênh thành công!\n\n"
            "🎉 Bây giờ bạn có thể sử dụng bot.",
            reply_markup=menu_chinh(u.id),
        )
        return

    await update.message.reply_text(
        "🚀 <b>BẠN CHƯA THAM GIA KÊNH</b>\n\n"
        "1️⃣ Bấm <b>THAM GIA KÊNH</b>\n"
        "2️⃣ Nếu kênh dùng yêu cầu tham gia, gửi yêu cầu và chờ bot duyệt\n"
        "3️⃣ Quay lại bot và bấm <b>KIỂM TRA ĐÃ THAM GIA CHƯA</b>",
        parse_mode="HTML",
        reply_markup=nut_kiem_tra_kenh(),
    )


async def kiem_tra_kenh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id
    u = get_user(uid)
    if not u:
        u = init_user(uid, update.effective_user.full_name, username=update.effective_user.username)

    if await kt_kenh(uid, context):
        await query.edit_message_text(
            "✅ <b>XÁC NHẬN THAM GIA KÊNH THÀNH CÔNG!</b>\n\n"
            "🎉 Bạn đã được mở khóa bot.\n"
            "👇 Chọn chức năng bên dưới để bắt đầu.",
            parse_mode="HTML",
        )
        await context.bot.send_message(
            chat_id=uid,
            text="🎉 Chào mừng bạn! Menu bot đã được mở.",
            reply_markup=menu_chinh(uid),
        )
        return

    await query.answer(
        "❌ Chưa phát hiện bạn tham gia kênh. "
        "Nếu vừa gửi yêu cầu, hãy chờ bot duyệt rồi kiểm tra lại.",
        show_alert=True,
    )


# ============================================================
# USER
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref_by = None

    if context.args:
        try:
            ref_by = int(context.args[0])
        except (ValueError, TypeError):
            ref_by = None

    init_user(u.id, u.full_name, ref_by, username=u.username)

    if not await kt_kenh(u.id, context):
        await update.message.reply_text(
            "🚀 <b>Hãy tham gia kênh trước</b> rồi bấm <b>KIỂM TRA ĐÃ THAM GIA CHƯA</b> bên dưới.",
            parse_mode="HTML",
            reply_markup=nut_kiem_tra_kenh(),
        )
        return

    await update.message.reply_text(
        "🎉 CHÀO MỪNG BẠN ĐẾN VỚI XU TIKTOP VIEW!\n\n"
        "Vui lòng chọn chức năng bên dưới:",
        reply_markup=menu_chinh(u.id),
    )


async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return

    reset_daily_if_needed(u)
    xac_minh = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that", 0) else "🔒 Chưa xác minh"

    await update.message.reply_text(
        f"""👤 <b>HỒ SƠ</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {h(u['ten'])}
👑 Cấp bậc: <b>{h(u['cap_bac'])}</b>
💰 Số dư: <b>{u['so_du']:,}đ</b>
👥 Cấp giới thiệu: <b>{u['gioi_thieu']}</b>
🛡 Xác minh: {xac_minh}

🔗 Tài khoản rút: {h(u['tai_khoan'] or 'Chưa liên kết')}""",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )


async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return

    reset_daily_if_needed(u)

    if not u["captcha_da_xac_minh"]:
        await update.message.reply_text(
            "🔐 Vui lòng nhấn [Nhập CaptCha] để xác minh trước!",
            reply_markup=menu_chinh(u["id"]),
        )
        return

    if u["dang_xem"]:
        await update.message.reply_text(
            "⏳ Bạn đang có một phiên xem đang xử lý, vui lòng chờ.",
            reply_markup=menu_chinh(u["id"]),
        )
        return

    cfg = CAP_BAC_CONFIG[u["cap_bac"]]
    if u["video_ngay"] >= cfg["gioi_han_xem_ngay"]:
        await update.message.reply_text(
            f"""⏳ Đã hết lượt xem hôm nay!

📺 Giới hạn {h(u['cap_bac'])}: {cfg['gioi_han_xem_ngay']} video/ngày
💵 Thưởng/video: {cfg['xu_moi_video']:,}đ/video

👉 Nâng cấp gói để xem nhiều hơn.""",
            reply_markup=menu_chinh(u["id"]),
        )
        return

    u["dang_xem"] = True
    save_user(u)

    video_link = LINK_VIDEO
    video_id = None
    try:
        with db() as conn:
            video_rows = conn.execute("SELECT id, url FROM video_links ORDER BY RANDOM() LIMIT 1").fetchall()
        if video_rows:
            video_id = video_rows[0]["id"]
            video_link = video_rows[0]["url"]
    except Exception:
        LOGGER.exception("Không lấy được danh sách video, dùng LINK_VIDEO mặc định")

    msg = await update.message.reply_text(
        f"""🔍 XEM TIKTOK — {h(u['cap_bac'])}

📺 Video hôm nay: {u['video_ngay']}/{cfg['gioi_han_xem_ngay']}
💰 Thưởng: {cfg['xu_moi_video']:,}đ/video
⏱ Thời gian xem: 15 giây

👉 Bấm mở video và xem đủ 15 giây.
⌛ Sau 15 giây nút nhận thưởng sẽ xuất hiện.""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎬 MỞ VIDEO TIKTOK", url=video_link)]]
        ),
    )

    context.user_data["watch_message_id"] = msg.message_id
    context.user_data["watch_video_id"] = video_id

    await asyncio.sleep(15)

    u = get_user(u["id"])
    if not u or not u["dang_xem"]:
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"✅ NHẬN {cfg['xu_moi_video']:,}đ",
            callback_data=f"nhan_thuong:{u['id']}:{msg.message_id}",
        )]]
    )
    try:
        await msg.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass


async def nhan_thuong_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        _, uid_s, message_id_s = query.data.split(":")
        uid = int(uid_s)
        message_id = int(message_id_s)
    except (ValueError, AttributeError):
        await query.answer("❌ Dữ liệu không hợp lệ.", show_alert=True)
        return

    if uid != update.effective_user.id:
        await query.answer("❌ Không phải phiên của bạn!", show_alert=True)
        return

    if context.user_data.get("watch_message_id") != message_id:
        await query.answer("❌ Phiên không hợp lệ!", show_alert=True)
        return

    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            conn.rollback()
            await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
            return

        # Reset lượt theo ngày ngay trong cùng transaction.
        current_day = today_vn()
        if row["ngay_reset"] != current_day:
            conn.execute(
                "UPDATE users SET video_ngay=0, ngay_reset=?, dang_xem=0 WHERE id=?",
                (current_day, uid),
            )
            row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

        if not row["dang_xem"]:
            conn.rollback()
            await query.answer("❌ Phiên đã hết hạn hoặc đã nhận thưởng.", show_alert=True)
            return

        cfg = CAP_BAC_CONFIG.get(row["cap_bac"], CAP_BAC_CONFIG["Thành viên"])
        if row["video_ngay"] >= cfg["gioi_han_xem_ngay"]:
            conn.execute("UPDATE users SET dang_xem=0 WHERE id=?", (uid,))
            conn.commit()
            await query.answer("❌ Đã hết lượt hôm nay.", show_alert=True)
            return

        tien = int(cfg["xu_moi_video"])

        # Atomic claim: 2 lần bấm cùng lúc chỉ một lần được cộng tiền.
        changed = conn.execute(
            """
            UPDATE users
            SET video_da_xem=video_da_xem+1,
                video_ngay=video_ngay+1,
                so_du=so_du+?,
                dang_xem=0
            WHERE id=? AND dang_xem=1 AND video_ngay < ?
            """,
            (tien, uid, cfg["gioi_han_xem_ngay"]),
        ).rowcount

        if changed != 1:
            conn.rollback()
            await query.answer("❌ Phần thưởng đã được xử lý.", show_alert=True)
            return

        updated = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

        # Hoa hồng F1/F2/F3 cũng nằm trong cùng transaction.
        ancestor_id = updated["ref_by"]
        visited = {uid}
        for rate in (HOA_HONG["f1"], HOA_HONG["f2"], HOA_HONG["f3"]):
            if not ancestor_id or ancestor_id in visited:
                break
            parent = conn.execute(
                "SELECT id, ref_by FROM users WHERE id=?", (ancestor_id,)
            ).fetchone()
            if not parent:
                break
            visited.add(parent["id"])
            commission = int(tien * rate)
            if commission > 0:
                conn.execute(
                    "UPDATE users SET so_du=so_du+? WHERE id=?",
                    (commission, parent["id"]),
                )
            ancestor_id = parent["ref_by"]

        conn.commit()

    await v2_video_record(uid, context.user_data.get("watch_video_id"), tien)
    context.user_data.pop("watch_message_id", None)
    context.user_data.pop("watch_video_id", None)
    await v2_auto_rank(uid)
    await query.answer("✅ Đã cộng thưởng!", show_alert=False)
    await query.edit_message_text(
        f"""✅ <b>NHẬN THƯỞNG THÀNH CÔNG</b>

🎬 Video hôm nay: {updated['video_ngay']}/{cfg['gioi_han_xem_ngay']}
⏱ Đã xem đủ: 15 giây
💰 Thưởng: +{tien:,}đ
💵 Số dư: {updated['so_du']:,}đ""",
        parse_mode="HTML",
    )


async def diem_danh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return
    today = today_vn()
    with db() as conn:
        row = conn.execute("SELECT * FROM user_rewards WHERE user_id=?", (u["id"],)).fetchone()
        if row and row["last_checkin"] == today:
            await update.message.reply_text(
                f"🎁 <b>ĐÃ ĐIỂM DANH HÔM NAY</b>\n\n🔥 Chuỗi hiện tại: <b>{row['streak']}</b> ngày",
                parse_mode="HTML", reply_markup=menu_chinh(u["id"]))
            return
        streak = int(row["streak"] or 0) + 1 if row else 1
        # Chuỗi 7 ngày nhận thêm, nhưng mỗi ngày đều có thưởng.
        amount = 2_000 + min(streak, 7) * 500
        conn.execute("""INSERT INTO user_rewards(user_id,last_checkin,streak) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET last_checkin=excluded.last_checkin, streak=excluded.streak""",
            (u["id"], today, streak))
        conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?", (amount, u["id"]))
        newbal = conn.execute("SELECT so_du FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    record_balance_change(u["id"], None, amount, newbal, "Điểm danh hằng ngày")
    await update.message.reply_text(
        f"🎉 <b>ĐIỂM DANH THÀNH CÔNG!</b>\n\n🔥 Chuỗi: <b>{streak}</b> ngày\n💰 Nhận: <b>+{amount:,}đ</b>\n💵 Số dư: <b>{newbal:,}đ</b>",
        parse_mode="HTML", reply_markup=menu_chinh(u["id"]))

async def nhiem_vu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return
    today = today_vn()
    with db() as conn:
        claims = {r["task_key"] for r in conn.execute("SELECT task_key FROM task_claims WHERE user_id=? AND claim_date=?", (u["id"], today)).fetchall()}
    tasks = [
        ("checkin", "🎁 Điểm danh hôm nay", 3000, True),
        ("watch2", "🎬 Xem đủ 2 video hôm nay", 5000, u["video_ngay"] >= 2),
        ("ref1", "👥 Có ít nhất 1 lượt giới thiệu", 5000, u["gioi_thieu"] >= 1),
    ]
    text = "🎯 <b>NHIỆM VỤ HÔM NAY</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons=[]
    for key,title,amount,done in tasks:
        claimed = key in claims
        status = "✅ Đã nhận" if claimed else ("🟢 Hoàn thành" if done else "⚪ Chưa hoàn thành")
        text += f"{title}\n└ {status} · +{amount:,}đ\n\n"
        if done and not claimed and key != "checkin":
            buttons.append([InlineKeyboardButton(f"🎁 Nhận {amount:,}đ", callback_data=f"task_claim:{key}")])
    buttons += [[InlineKeyboardButton("🎁 Điểm danh", callback_data="user_checkin")], [InlineKeyboardButton("🎟️ Nhập mã thưởng", callback_data="bonus_redeem")]]
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def bang_xep_hang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute("SELECT id,ten,gioi_thieu FROM users ORDER BY gioi_thieu DESC, id ASC LIMIT 10").fetchall()
    text="🏆 <b>BẢNG XẾP HẠNG GIỚI THIỆU</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not rows:
        text += "Chưa có dữ liệu."
    else:
        icons=["🥇","🥈","🥉"]
        for i,r in enumerate(rows,1):
            text += f"{icons[i-1] if i<=3 else '👤'} <b>#{i}</b> {h(r['ten'])} — <b>{r['gioi_thieu']}</b> lượt\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=menu_chinh(update.effective_user.id))

async def lich_su_giao_dich_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    with db() as conn:
        rows=conn.execute("SELECT * FROM balance_history WHERE user_id=? ORDER BY id DESC LIMIT 15",(uid,)).fetchall()
        w=conn.execute("SELECT request_id,so_tien,status,thoi_gian FROM withdrawals WHERE user_id=? ORDER BY thoi_gian DESC LIMIT 10",(uid,)).fetchall()
    text="📜 <b>LỊCH SỬ GIAO DỊCH</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for r in rows:
        sign='+' if r['delta']>=0 else ''
        text += f"\n💰 {sign}{r['delta']:,}đ · {h(r['reason'] or '')}\n🕒 {h(r['created_at'])}\n"
    if w:
        text += "\n💸 <b>RÚT TIỀN</b>\n"
        for r in w:
            text += f"\n📋 <code>{h(r['request_id'])}</code> · {r['so_tien']:,}đ · {h(r['status'])}\n"
    if not rows and not w: text += "\nChưa có giao dịch."
    await update.message.reply_text(text,parse_mode="HTML",reply_markup=menu_chinh(uid))

async def bonus_redeem_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["await_bonus_code"] = True
    await update.effective_message.reply_text("🎟️ Gửi <b>mã thưởng</b> của bạn:",parse_mode="HTML",reply_markup=ReplyKeyboardRemove())

async def handle_bonus_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("await_bonus_code", False): return False
    code=(update.effective_message.text or '').strip().upper()
    uid=update.effective_user.id
    with db() as conn:
        row=conn.execute("SELECT * FROM bonus_codes WHERE code=? AND active=1",(code,)).fetchone()
        if not row:
            await update.effective_message.reply_text("❌ Mã không tồn tại hoặc đã khóa.",reply_markup=menu_chinh(uid)); return True
        if row['used_count']>=row['max_uses']:
            await update.effective_message.reply_text("❌ Mã đã hết lượt sử dụng.",reply_markup=menu_chinh(uid)); return True
        claimed=conn.execute("SELECT 1 FROM bonus_claims WHERE code=? AND user_id=?",(code,uid)).fetchone()
        if claimed:
            await update.effective_message.reply_text("❌ Bạn đã sử dụng mã này rồi.",reply_markup=menu_chinh(uid)); return True
        conn.execute("INSERT INTO bonus_claims(code,user_id,claimed_at) VALUES(?,?,?)",(code,uid,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
        conn.execute("UPDATE bonus_codes SET used_count=used_count+1 WHERE code=?",(code,))
        conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?",(row['amount'],uid))
        bal=conn.execute("SELECT so_du FROM users WHERE id=?",(uid,)).fetchone()[0]
    record_balance_change(uid,None,int(row['amount']),bal,f"Mã thưởng {code}")
    await update.effective_message.reply_text(f"🎉 <b>NHẬN MÃ THƯỞNG THÀNH CÔNG</b>\n\n🎟️ Mã: <code>{h(code)}</code>\n💰 +{row['amount']:,}đ\n💵 Số dư: {bal:,}đ",parse_mode='HTML',reply_markup=menu_chinh(uid))
    return True

async def user_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data; await q.answer()
    if data=="user_checkin":
        uid=update.effective_user.id; today=today_vn()
        with db() as conn:
            row=conn.execute("SELECT * FROM user_rewards WHERE user_id=?",(uid,)).fetchone()
            if row and row["last_checkin"]==today:
                await q.answer("❌ Hôm nay đã điểm danh.",show_alert=True); return
            streak=(int(row["streak"] or 0)+1) if row else 1
            amount=2000+min(streak,7)*500
            conn.execute("INSERT INTO user_rewards(user_id,last_checkin,streak) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET last_checkin=excluded.last_checkin, streak=excluded.streak",(uid,today,streak))
            conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?",(amount,uid))
            bal=conn.execute("SELECT so_du FROM users WHERE id=?",(uid,)).fetchone()[0]
        record_balance_change(uid,None,amount,bal,"Điểm danh hằng ngày")
        await q.message.reply_text(f"🎉 <b>ĐIỂM DANH THÀNH CÔNG!</b>\n\n🔥 Chuỗi: <b>{streak}</b> ngày\n💰 +{amount:,}đ\n💵 Số dư: <b>{bal:,}đ</b>",parse_mode='HTML',reply_markup=menu_chinh(uid)); return
    if data.startswith("task_claim:"):
        key=data.split(':',1)[1]; uid=update.effective_user.id; today=today_vn()
        rewards={'watch2':5000,'ref1':5000}
        u=get_user(uid)
        if key not in rewards or not u: return
        done=(key=='watch2' and u['video_ngay']>=2) or (key=='ref1' and u['gioi_thieu']>=1)
        with db() as conn:
            exists=conn.execute("SELECT 1 FROM task_claims WHERE user_id=? AND task_key=? AND claim_date=?",(uid,key,today)).fetchone()
            if exists or not done:
                await q.answer("❌ Nhiệm vụ chưa đủ điều kiện hoặc đã nhận.",show_alert=True); return
            amt=rewards[key]; conn.execute("INSERT INTO task_claims VALUES(?,?,?,?)",(uid,key,today,amt)); conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?",(amt,uid)); bal=conn.execute("SELECT so_du FROM users WHERE id=?",(uid,)).fetchone()[0]
        record_balance_change(uid,None,amt,bal,f"Nhiệm vụ {key}")
        await q.message.reply_text(f"🎉 Đã nhận +{amt:,}đ!\n💵 Số dư: {bal:,}đ",reply_markup=menu_chinh(uid))
    elif data=="bonus_redeem":
        await bonus_redeem_prompt(update,context)

async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khu vực riêng cho cấp giới thiệu và link giới thiệu."""
    u = get_user(update.effective_user.id)
    if not u:
        return

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={u['id']}"

    thuong = CAP_BAC_CONFIG[u["cap_bac"]]["thuong_gioi_thieu"]
    await update.message.reply_text(
        f"""👥 <b>CẤP GIỚI THIỆU</b>

👥 Người đã giới thiệu: <b>{u['gioi_thieu']}</b>
💰 Thưởng giới thiệu hiện tại: <b>{thuong:,}đ/người</b>

📈 <b>MỐC CẤP GIỚI THIỆU</b>
👤 0–29 → Thành viên
🥈 30–99 → Leader Bạc
🥇 100–299 → Leader Vàng
💎 300–499 → Leader Bạch Kim
💠 500–999 → Leader Kim Cương
👑 1.000+ → Leader Cao Thủ

🔗 <b>LINK GIỚI THIỆU</b>
<code>{link}</code>""",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )


async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥈 Gói Bạc", callback_data="goi_bac")],
        [InlineKeyboardButton("🥇 Gói Vàng", callback_data="goi_vang")],
        [InlineKeyboardButton("💎 Gói Bạch Kim", callback_data="goi_bachkim")],
        [InlineKeyboardButton("💠 Gói Kim Cương", callback_data="goi_kimcuong")],
    ])
    await update.message.reply_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n\n👇 Chọn gói bạn muốn xem:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def xu_ly_goi_nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    u = get_user(update.effective_user.id)
    if not u or data not in GOI_NANG_CAP:
        return ConversationHandler.END

    g = GOI_NANG_CAP[data]
    ma_nap = f"{g['ma_chung']} {u['id']} {int(time.time())}"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO deposits
            (request_id, user_id, ten, goi_key, cap_moi, gia, thoi_gian, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                ma_nap, u["id"], u["ten"], data, g["cap_moi"],
                g["gia"], now_vn().strftime("%d/%m/%Y %H:%M"),
            ),
        )

    await query.edit_message_text(
        f"""🏅 <b>{h(g['ten'])}</b>

💰 Nạp: {g['gia']:,}đ
📺 Xem: {g['gioi_han_xem']} video TikTok/ngày
💵 {g['tien_moi_video']:,}đ / video

🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>
Ngân hàng: {h(g['ngan_hang'])}
Chủ TK: {h(g['chu_tk'])}
Số TK: {h(g['so_tk'])}

💵 Số tiền: {g['gia']:,}đ
📝 Nội dung CK: {h(ma_nap)}

⚠️ Vui lòng chuyển đúng số tiền và đúng nội dung!""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📩 Tôi đã chuyển khoản",
                callback_data=f"dachuyen:{ma_nap}",
            )
        ]]),
    )
    context.user_data["ma_nap_dang_xu_ly"] = ma_nap
    return NAP_GUI_ANH


async def da_chuyen_khoan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    ma_nap = query.data.split(":", 1)[1]
    with db() as conn:
        yc = conn.execute(
            "SELECT * FROM deposits WHERE request_id=? AND status='pending'",
            (ma_nap,),
        ).fetchone()

    if not yc:
        await query.answer(
            "❌ Yêu cầu không tồn tại hoặc đã xử lý.",
            show_alert=True,
        )
        return ConversationHandler.END

    context.user_data["ma_nap_dang_xu_ly"] = ma_nap
    await query.edit_message_text(
        f"""📩 <b>XÁC NHẬN CHUYỂN KHOẢN</b>

Vui lòng gửi ảnh màn hình chuyển khoản thành công hoặc biên lai để Admin kiểm tra.

📦 Gói: {h(yc['goi_key'].replace('goi_', '').upper())}
💵 Số tiền: {yc['gia']:,}đ""",
        parse_mode="HTML",
    )
    return NAP_GUI_ANH


async def nhan_anh_chuyen_khoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    ma_nap = context.user_data.get("ma_nap_dang_xu_ly")

    with db() as conn:
        yc = conn.execute(
            "SELECT * FROM deposits WHERE request_id=? AND status='pending'",
            (ma_nap or "",),
        ).fetchone()

    if not yc:
        await update.message.reply_text(
            "❌ Yêu cầu không tồn tại hoặc đã hết hạn.",
            reply_markup=menu_chinh(u_id),
        )
        return ConversationHandler.END

    photo = update.effective_message.photo[-1] if update.effective_message.photo else None
    caption = f"""📢 <b>YÊU CẦU NẠP TIỀN — CHỜ DUYỆT</b>

🆔 ID: <code>{yc['user_id']}</code>
👤 Tên: {h(yc['ten'])}
📦 Gói: {h(yc['goi_key'].replace('goi_', '').upper())}
💵 Số tiền: {yc['gia']:,}đ
🏆 Nâng cấp lên: {h(yc['cap_moi'])}
📅 Thời gian: {h(yc['thoi_gian'])}
🔔 Mã: <code>{h(yc['request_id'])}</code>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ DUYỆT", callback_data=f"duyet_nap_ok:{ma_nap}"),
        InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"duyet_nap_no:{ma_nap}"),
    ]])

    if photo:
        with db() as conn:
            conn.execute(
                "UPDATE deposits SET photo_file_id=? WHERE request_id=?",
                (photo.file_id, ma_nap),
            )
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=caption + "\n\n⚠️ Người dùng không gửi ảnh.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    await update.message.reply_text(
        f"""✅ <b>ĐÃ GỬI XÁC NHẬN</b>

📦 Gói: {h(yc['goi_key'].replace('goi_', '').upper())}
💵 Số tiền: {yc['gia']:,}đ
⏳ Đang chờ Admin duyệt.""",
        parse_mode="HTML",
        reply_markup=menu_chinh(u_id),
    )

    context.user_data.pop("ma_nap_dang_xu_ly", None)
    return ConversationHandler.END


async def ho_tro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Các thông tin liên hệ được chuyển thành nút bấm trực tiếp.
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 LIÊN HỆ HỖ TRỢ", url="https://t.me/hotroxutiktok")],
        [InlineKeyboardButton("📢 KÊNH THÔNG BÁO", url="https://t.me/rutxutiktok")],
    ])

    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\n"
        "Bấm nút bên dưới để liên hệ hỗ trợ hoặc xem kênh thông báo.\n\n"
        "⏰ 8:00 - 22:00 hàng ngày",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


def _captcha_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_captcha_image(code):
    """Tạo PNG CAPTCHA với chữ lớn + đường nhiễu giống ảnh mẫu."""
    width, height = 600, 220
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    # Nhiễu đường thẳng.
    for _ in range(32):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        shade = random.randint(120, 205)
        draw.line((x1, y1, x2, y2), fill=(shade, shade, shade), width=random.randint(1, 3))

    # Nhiễu chấm.
    for _ in range(180):
        x = random.randrange(width)
        y = random.randrange(height)
        shade = random.randint(130, 220)
        r = random.choice((1, 1, 2))
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(shade, shade, shade))

    font = _captcha_font(86)
    total_width = sum(draw.textlength(ch, font=font) for ch in code)
    x = (width - total_width) / 2

    for ch in code:
        bbox = draw.textbbox((0, 0), ch, font=font)
        ch_w = draw.textlength(ch, font=font)
        y = random.randint(55, 105)
        draw.text(
            (x, y),
            ch,
            font=font,
            fill=(15, 15, 15),
            stroke_width=1,
            stroke_fill=(0, 0, 0),
        )
        x += ch_w + random.randint(2, 8)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _new_captcha(context):
    code = "".join(random.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))
    context.user_data["captcha_code"] = code
    context.user_data["captcha_created_at"] = time.time()
    return code


async def _send_captcha(update, context, edit=False):
    code = _new_captcha(context)
    image = _make_captcha_image(code)

    caption = (
        "🔐 <b>GIẢI CAPTCHA</b>\n\n"
        "Nhập chính xác mã trong hình bên trên.\n"
        "⏱ CAPTCHA có hiệu lực trong <b>5 phút</b>."
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Đổi Captcha", callback_data="captcha_doi"),
            InlineKeyboardButton("❌ Hủy Captcha", callback_data="captcha_huy"),
        ]
    ])

    if edit and update.callback_query:
        # Xóa tin nhắn cũ rồi gửi ảnh mới để Telegram hiển thị CAPTCHA rõ ràng.
        try:
            await update.callback_query.delete_message()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=update.effective_user.id,
            photo=image,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text("✨ Đang tạo Captcha, vui lòng chờ...")
        await update.message.reply_photo(
            photo=image,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return

    context.user_data.pop("captcha_code", None)
    context.user_data.pop("captcha_created_at", None)
    await _send_captcha(update, context)


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "captcha_doi":
        await query.answer("🔄 Đang tạo CAPTCHA mới...")
        await _send_captcha(update, context, edit=True)
        return

    if data == "captcha_huy":
        context.user_data.pop("captcha_code", None)
        context.user_data.pop("captcha_created_at", None)
        await query.answer("Đã hủy CAPTCHA.")
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ Đã hủy CAPTCHA.",
            reply_markup=menu_chinh(update.effective_user.id),
        )


async def captcha_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiểm tra mã CAPTCHA người dùng nhập vào."""
    code = context.user_data.get("captcha_code")
    created = context.user_data.get("captcha_created_at")

    if not code or not created:
        return

    answer = (update.message.text or "").strip().upper()
    if time.time() - float(created) > CAPTCHA_TTL_SECONDS:
        context.user_data.pop("captcha_code", None)
        context.user_data.pop("captcha_created_at", None)
        await update.message.reply_text(
            "⏰ CAPTCHA đã hết hạn. Bấm '🔐 Nhập CaptCha' để tạo mã mới.",
            reply_markup=menu_chinh(update.effective_user.id),
        )
        return

    if answer != code:
        await update.message.reply_text(
            "❌ CAPTCHA không đúng. Vui lòng nhập lại hoặc bấm 'Đổi Captcha'."
        )
        return

    u = get_user(update.effective_user.id)
    if not u:
        return

    u["captcha_da_xac_minh"] = True
    save_user(u)
    context.user_data.pop("captcha_code", None)
    context.user_data.pop("captcha_created_at", None)

    await update.message.reply_text(
        "✅ <b>CAPTCHA chính xác!</b>\n\n"
        "🔓 Bạn đã xác minh CAPTCHA thành công và có thể xem TikTok.",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )


# ============================================================
# XÁC MINH NGƯỜI THẬT
# ============================================================
async def rut_bi_khoa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        "🔒 Bạn cần xác minh người thật trước khi rút tiền.",
        show_alert=True,
    )


async def xac_minh_nguoi_that_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Màn hình chọn phương thức xác minh, thiết kế gọn cho Telegram mobile."""
    query = update.callback_query
    u = get_user(update.effective_user.id)
    if not u:
        await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
        return

    if u.get("xac_minh_nguoi_that", 0):
        await query.answer("✅ Tài khoản đã được xác minh.", show_alert=True)
        return

    await query.answer()
    text = (
        "🛡 <b>XÁC MINH NGƯỜI THẬT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Chọn <b>1 trong 2 cách</b>:\n\n"
        f"💰 <b>Trừ số dư</b> · {PHI_XAC_MINH_SO_DU:,}đ\n"
        "└ Xác minh ngay, không cần biên lai\n\n"
        f"💳 <b>Nạp tiền</b> · {PHI_XAC_MINH:,}đ\n"
        "└ Chuyển khoản → gửi biên lai → Admin duyệt\n\n"
        "⚠️ Kiểm tra kỹ phương thức trước khi thực hiện."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"💰 Trừ {PHI_XAC_MINH_SO_DU:,}đ từ số dư",
            callback_data="xac_minh_so_du",
        )],
        [InlineKeyboardButton(
            f"💳 Nạp {PHI_XAC_MINH:,}đ để xác minh",
            callback_data="xac_minh_nap_30k",
        )],
        [InlineKeyboardButton("🏠 Menu chính", callback_data="ve_menu_chinh")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def ve_menu_chinh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(update.effective_user.id)
    if not u:
        return
    await query.edit_message_text(
        "🏠 <b>MENU CHÍNH</b>\n\nVui lòng chọn chức năng bên dưới.",
        parse_mode="HTML",
    )
    await context.bot.send_message(
        chat_id=u["id"],
        text="Chọn chức năng:",
        reply_markup=menu_chinh(u["id"]),
    )


async def xac_minh_bang_so_du_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trừ 50.000đ trong số dư và xác minh ngay trong một transaction."""
    query = update.callback_query
    u = get_user(update.effective_user.id)
    if not u:
        await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
        return

    if u.get("xac_minh_nguoi_that", 0):
        await query.answer("✅ Bạn đã được xác minh.", show_alert=True)
        return

    with db() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM users WHERE id=?", (u["id"],)
        ).fetchone()
        if not row:
            await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
            return
        if row["xac_minh_nguoi_that"]:
            await query.answer("✅ Bạn đã được xác minh.", show_alert=True)
            return
        if row["so_du"] < PHI_XAC_MINH_SO_DU:
            await query.answer(
                f"❌ Số dư không đủ. Cần {PHI_XAC_MINH_SO_DU:,}đ, hiện có {row['so_du']:,}đ.",
                show_alert=True,
            )
            return

        request_id = f"XMSD{row['id']}{int(time.time() * 1000)}"

        changed = conn.execute(
            """
            UPDATE users
            SET so_du=so_du-?, xac_minh_nguoi_that=1
            WHERE id=? AND so_du>=? AND xac_minh_nguoi_that=0
            """,
            (PHI_XAC_MINH_SO_DU, row["id"], PHI_XAC_MINH_SO_DU),
        ).rowcount

        if changed != 1:
            conn.rollback()
            await query.answer(
                "❌ Tài khoản vừa được xác minh hoặc số dư không đủ.",
                show_alert=True,
            )
            return

        conn.execute(
            """
            INSERT INTO verification_requests
            (request_id, user_id, ten, phi, thoi_gian, status, photo_file_id, phuong_thuc)
            VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'so_du_50000')
            """,
            (
                request_id, row["id"], row["ten"], PHI_XAC_MINH_SO_DU,
                now_vn().strftime("%d/%m/%Y %H:%M"),
            ),
        )
        new_balance = row["so_du"] - PHI_XAC_MINH_SO_DU

    await query.answer("✅ Xác minh thành công! Đã trừ 50.000đ.", show_alert=True)
    await query.edit_message_text(
        f"""🛡 <b>XÁC MINH THÀNH CÔNG</b>

✅ Bạn đã xác minh người thật thành công.
💰 Phí đã trừ: <b>{PHI_XAC_MINH_SO_DU:,}đ</b>
💵 Số dư còn lại: <b>{new_balance:,}đ</b>

🔓 Chức năng rút tiền đã được mở khóa.""",
        parse_mode="HTML",
        reply_markup=menu_chinh(row["id"]),
    )


async def xac_minh_nap_30k_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tạo yêu cầu xác minh bằng chuyển khoản 30.000đ."""
    query = update.callback_query
    u = get_user(update.effective_user.id)
    if not u:
        await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
        return
    if u.get("xac_minh_nguoi_that", 0):
        await query.answer("✅ Tài khoản đã được xác minh.", show_alert=True)
        return
    await query.answer()

    with db() as conn:
        old = conn.execute(
            """SELECT * FROM verification_requests
               WHERE user_id=? AND status='pending' AND phuong_thuc='nap_30000'
               ORDER BY thoi_gian DESC LIMIT 1""",
            (u["id"],),
        ).fetchone()
        if old:
            request_id = old["request_id"]
        else:
            request_id = f"XM{u['id']}{int(time.time() * 1000)}"
            conn.execute(
                """INSERT INTO verification_requests
                   (request_id, user_id, ten, phi, thoi_gian, status, phuong_thuc)
                   VALUES (?, ?, ?, ?, ?, 'pending', 'nap_30000')""",
                (request_id, u["id"], u["ten"], PHI_XAC_MINH,
                 now_vn().strftime("%d/%m/%Y %H:%M")),
            )

    context.user_data["dang_xac_minh"] = request_id
    content = (
        "💳 <b>XÁC MINH BẰNG CHUYỂN KHOẢN</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Số tiền:</b> {PHI_XAC_MINH:,}đ\n\n"
        "🏦 <b>NGÂN HÀNG ACB</b>\n"
        f"👤 <b>Chủ TK:</b> {h(XAC_MINH_CHU_TK)}\n"
        f"🔢 <b>Số TK:</b> <code>{h(XAC_MINH_SO_TK)}</code>\n"
        f"📝 <b>Nội dung:</b> <code>XACMINH {u['id']}</code>\n\n"
        "📌 <b>Thực hiện:</b>\n"
        "1️⃣ Chuyển đúng 30.000đ\n"
        "2️⃣ Bấm <b>Đã chuyển khoản</b>\n"
        "3️⃣ Gửi ảnh biên lai vào chat\n\n"
        "⏳ Admin sẽ kiểm tra giao dịch và duyệt."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Đã chuyển khoản — Gửi biên lai", callback_data="xac_minh_da_chuyen_khoan")],
        [InlineKeyboardButton("↩️ Đổi phương thức", callback_data="xac_minh_nguoi_that")],
        [InlineKeyboardButton("🏠 Menu chính", callback_data="ve_menu_chinh")],
    ])
    await query.edit_message_text(content, parse_mode="HTML", reply_markup=keyboard)


async def xac_minh_da_chuyen_khoan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chuyển sang trạng thái chờ ảnh biên lai."""
    query = update.callback_query
    u = get_user(update.effective_user.id)
    if not u:
        await query.answer("❌ Không tìm thấy tài khoản.", show_alert=True)
        return
    await query.answer()

    request_id = context.user_data.get("dang_xac_minh")
    if not request_id:
        with db() as conn:
            row = conn.execute(
                """SELECT request_id FROM verification_requests
                   WHERE user_id=? AND status='pending' AND phuong_thuc='nap_30000'
                   ORDER BY thoi_gian DESC LIMIT 1""",
                (u["id"],),
            ).fetchone()
        if row:
            request_id = row["request_id"]
            context.user_data["dang_xac_minh"] = request_id

    if not request_id:
        await query.answer("❌ Không tìm thấy yêu cầu. Vui lòng chọn lại.", show_alert=True)
        return

    text = (
        "📸 <b>GỬI BIÊN LAI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Bạn đã chọn xác minh bằng chuyển khoản.\n\n"
        f"💰 Số tiền: <b>{PHI_XAC_MINH:,}đ</b>\n"
        f"📝 Nội dung: <code>XACMINH {u['id']}</code>\n\n"
        "👉 <b>Bây giờ hãy gửi ảnh biên lai chuyển khoản vào chat này.</b>\n"
        "⚠️ Chỉ gửi ảnh biên lai rõ ràng, không gửi thông tin thẻ hoặc mã bảo mật."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Quay lại", callback_data="xac_minh_nap_30k")],
        [InlineKeyboardButton("🏠 Menu chính", callback_data="ve_menu_chinh")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def nhan_anh_xac_minh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận biên lai 30.000đ và gửi cho Admin kiểm tra."""
    request_id = context.user_data.get("dang_xac_minh")
    if not request_id:
        return

    u = get_user(update.effective_user.id)
    if not u:
        context.user_data.pop("dang_xac_minh", None)
        return

    photo = update.effective_message.photo[-1] if update.effective_message.photo else None
    if not photo:
        await update.message.reply_text(
            "❌ Vui lòng gửi ảnh biên lai chuyển khoản.",
            reply_markup=menu_chinh(u["id"]),
        )
        return

    with db() as conn:
        yc = conn.execute(
            "SELECT * FROM verification_requests WHERE request_id=? AND status='pending'",
            (request_id,),
        ).fetchone()
        if not yc:
            context.user_data.pop("dang_xac_minh", None)
            await update.message.reply_text(
                "❌ Yêu cầu xác minh không tồn tại hoặc đã được xử lý.",
                reply_markup=menu_chinh(u["id"]),
            )
            return
        conn.execute(
            "UPDATE verification_requests SET photo_file_id=? WHERE request_id=?",
            (photo.file_id, request_id),
        )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ DUYỆT XÁC MINH", callback_data=f"xacminh_ok:{request_id}"),
        InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"xacminh_no:{request_id}"),
    ]])

    caption = f"""🛡 <b>BIÊN LAI XÁC MINH NGƯỜI THẬT</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {h(u['ten'])}
💰 Phí: {PHI_XAC_MINH:,}đ
📝 Nội dung cần đối chiếu: <code>XACMINH {u['id']}</code>
📋 Mã: <code>{h(request_id)}</code>

⚠️ Kiểm tra giao dịch thực tế trước khi duyệt."""

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    context.user_data.pop("dang_xac_minh", None)
    await update.message.reply_text(
        "✅ Đã gửi biên lai cho Admin. Vui lòng chờ kiểm tra và duyệt.",
        reply_markup=menu_chinh(u["id"]),
    )


# ============================================================


async def gui_yeu_cau_rut_kenh(*args, **kwargs):
    # Không đăng yêu cầu rút đang chờ duyệt lên kênh công khai.
    return None

async def cap_nhat_thong_bao_rut_kenh(context, message_id, request_id, trang_thai, so_tien=None, tai_khoan=None, ten=None):
    """Cập nhật bài đăng trong kênh sau khi duyệt/từ chối."""
    if not message_id:
        return
    if trang_thai == "approved":
        text = (
            "✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>\n\n"
            f"📋 Mã: <code>{h(request_id)}</code>\n"
            f"💵 Số tiền: <b>{so_tien:,}đ</b>\n"
            f"🔗 Tài khoản: {h(tai_khoan)}\n"
            f"👤 Người nhận: <b>{h(ten)}</b>\n\n"
            "✅ <b>Đã duyệt.</b>"
        )
    else:
        text = (
            "❌ <b>YÊU CẦU RÚT TIỀN BỊ TỪ CHỐI</b>\n\n"
            f"📋 Mã: <code>{h(request_id)}</code>\n\n"
            "❌ <b>Đã từ chối.</b>"
        )
    try:
        await context.bot.edit_message_text(
            chat_id=KENH_THONG_BAO,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception as exc:
        LOGGER.warning("Không cập nhật được thông báo %s trong kênh: %r", request_id, exc)


async def gui_thong_bao_rut_thanh_cong(context, ma_rut, so_tien, tai_khoan, ten_nguoi_nhan):
    """Gửi thông báo rút tiền thành công vào kênh @rutxutiktok."""
    if not KENH_THONG_BAO_RUT:
        return
    text = (
        "✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>\n\n"
        f"📋 Mã: <code>{h(ma_rut)}</code>\n"
        f"💵 Số tiền: <b>{so_tien:,}đ</b>\n"
        f"🔗 Tài khoản: {h(tai_khoan)}\n"
        f"👤 Người nhận: <b>{h(ten_nguoi_nhan)}</b>\n\n"
        "✅ <b>Đã duyệt.</b>"
    )
    try:
        await context.bot.send_message(chat_id=KENH_THONG_BAO_RUT, text=text, parse_mode="HTML")
    except Exception as exc:
        LOGGER.exception("Không gửi được thông báo rút thành công vào kênh: %r", exc)


# RÚT TIỀN + LIÊN KẾT TÀI KHOẢN
# ============================================================
async def rut_tien_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return ConversationHandler.END

    if not u["tai_khoan"]:
        await update.message.reply_text(
            "💰 <b>RÚT TIỀN</b>\n\n"
            "🏦 Bạn chưa liên kết tài khoản nhận tiền.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔗 Liên kết tài khoản",
                    callback_data="lien_ket_tai_khoan",
                )
            ]]),
        )
        return ConversationHandler.END

    if not u.get("xac_minh_nguoi_that", 0):
        parts = u["tai_khoan"].split()
        bank = parts[0] if parts else "Chưa có"
        number = parts[1] if len(parts) > 1 else "Chưa có"
        owner = " ".join(parts[2:]) if len(parts) > 2 else "Chưa có"

        await update.message.reply_text(
            f"""💰 <b>RÚT TIỀN</b>

🏦 <b>TÀI KHOẢN ĐÃ LIÊN KẾT</b>

🏦 Tên ngân hàng: <b>{h(bank)}</b>
🔢 Số tài khoản: <b>{h(number)}</b>
👤 Chủ tài khoản: <b>{h(owner)}</b>

Bạn có thể sử dụng tài khoản này cho các lần rút sau.

🔒 <b>CHƯA THỂ RÚT TIỀN</b>

Bạn cần xác minh người thật trước khi tạo yêu cầu rút tiền.

💰 <b>Phí xác minh: {PHI_XAC_MINH:,}đ</b>
✅ Sau khi Admin duyệt xác minh, bạn được mở khóa rút tiền.""",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💸 Rút tiền",
                    callback_data="rut_bi_khoa",
                )],
                [InlineKeyboardButton(
                    "🔄 Thay đổi tài khoản",
                    callback_data="lien_ket_tai_khoan",
                )],
                [InlineKeyboardButton(
                    "🛡 Xác minh người thật",
                    callback_data="xac_minh_nguoi_that",
                )],
            ]),
        )
        return ConversationHandler.END

    if u["so_du"] < RUT_TOI_THIEU:
        await update.message.reply_text(
            f"""💰 <b>RÚT TIỀN</b>

❌ Số dư không đủ!
💵 Hiện có: {u['so_du']:,}đ
💰 Tối thiểu: {RUT_TOI_THIEU:,}đ""",
            parse_mode="HTML",
            reply_markup=menu_chinh(u["id"]),
        )
        return ConversationHandler.END

    context.user_data["dang_rut_tien"] = True
    await update.message.reply_text(
        f"""💰 RÚT TIỀN

🔗 Tài khoản: {h(u['tai_khoan'])}
💵 Số dư: {u['so_du']:,}đ

Vui lòng nhập số tiền muốn rút (tối thiểu {RUT_TOI_THIEU:,}đ):""",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NHAP_TAI_KHOAN


async def lien_ket_tai_khoan_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["dang_lien_ket"] = True

    await query.edit_message_text(
        """🔗 LIÊN KẾT TÀI KHOẢN

Gửi theo dạng:
MOMO 0396037105 HA QUANG MINH
ACB 25607451 HA QUANG MINH

⚠️ Số tài khoản chỉ gồm chữ số.
Tên chủ tài khoản viết sau số tài khoản.""",
    )
    return NHAP_TAI_KHOAN


async def nhap_thong_tin_tai_khoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return ConversationHandler.END

    text = update.effective_message.text.strip()

    if context.user_data.get("dang_lien_ket"):
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Sai định dạng.\nVí dụ: ACB 25607451 NGUYEN VAN A",
                reply_markup=ReplyKeyboardRemove(),
            )
            return NHAP_TAI_KHOAN

        loai_tk = parts[0].upper()
        so_tk = parts[1]
        ten_chu = " ".join(parts[2:]).upper()

        if not so_tk.isdigit():
            await update.message.reply_text(
                "❌ Số tài khoản chỉ gồm chữ số.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return NHAP_TAI_KHOAN

        u["tai_khoan"] = f"{loai_tk} {so_tk} {ten_chu}"
        save_user(u)
        context.user_data.pop("dang_lien_ket", None)

        await update.message.reply_text(
            f"✅ <b>LIÊN KẾT TÀI KHOẢN THÀNH CÔNG!</b>\n\n"
            f"🔗 {h(u['tai_khoan'])}",
            parse_mode="HTML",
            reply_markup=menu_chinh(u["id"]),
        )
        return ConversationHandler.END

    try:
        so_tien = int(
            text.replace(".", "").replace(",", "").replace("đ", "").strip()
        )
    except ValueError:
        await update.message.reply_text(
            "❌ Vui lòng nhập số tiền hợp lệ.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return NHAP_TAI_KHOAN

    rut_min = int(get_setting("rut_toi_thieu", RUT_TOI_THIEU))
    rut_max = int(get_setting("rut_toi_da", 0))
    if so_tien < rut_min:
        await update.message.reply_text(
            f"❌ Tối thiểu rút {rut_min:,}đ.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return NHAP_TAI_KHOAN

    u = get_user(u["id"])
    if rut_max > 0 and so_tien > rut_max:
        await update.message.reply_text(f"❌ Tối đa mỗi lần rút {rut_max:,}đ.", reply_markup=ReplyKeyboardRemove())
        return NHAP_TAI_KHOAN
    if so_tien > u["so_du"]:
        await update.message.reply_text(
            "❌ Số tiền vượt quá số dư hiện tại.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return NHAP_TAI_KHOAN

    # Giới hạn số lần rút/ngày và khoảng cách giữa các yêu cầu.
    today_prefix = now_vn().strftime("%d/%m/%Y") + "%"
    max_daily = int(get_setting("rut_so_lan_ngay", 0))
    cooldown = int(get_setting("rut_cooldown_giay", 0))
    with db() as conn:
        today_count = conn.execute(
            "SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND thoi_gian LIKE ?",
            (u["id"], today_prefix),
        ).fetchone()[0]
        last = conn.execute(
            "SELECT thoi_gian FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (u["id"],),
        ).fetchone()
    if max_daily > 0 and today_count >= max_daily:
        await update.message.reply_text(f"❌ Bạn đã đạt giới hạn {max_daily} lần rút trong hôm nay.", reply_markup=ReplyKeyboardRemove())
        return NHAP_TAI_KHOAN
    if cooldown > 0 and last and last["thoi_gian"]:
        try:
            last_dt = datetime.strptime(last["thoi_gian"], "%d/%m/%Y %H:%M").replace(tzinfo=VN_TZ)
            remain = cooldown - int((now_vn() - last_dt).total_seconds())
            if remain > 0:
                await update.message.reply_text(f"⏱️ Vui lòng chờ {remain} giây trước khi tạo yêu cầu rút tiếp theo.", reply_markup=ReplyKeyboardRemove())
                return NHAP_TAI_KHOAN
        except Exception:
            pass

    request_id = f"RUT{u['id']}{int(time.time() * 1000)}"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO withdrawals
            (request_id, user_id, ten, so_tien, tai_khoan, thoi_gian, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                request_id,
                u["id"],
                u["ten"],
                so_tien,
                u["tai_khoan"],
                now_vn().strftime("%d/%m/%Y %H:%M"),
            ),
        )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ DUYỆT",
            callback_data=f"duyet_ok:{request_id}",
        ),
        InlineKeyboardButton(
            "❌ TỪ CHỐI",
            callback_data=f"duyet_no:{request_id}",
        ),
    ]])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"""📢 <b>YÊU CẦU RÚT TIỀN MỚI</b>

📋 Mã: <code>{h(request_id)}</code>
🆔 ID: <code>{u['id']}</code>
👤 Tên: {h(u['ten'])}
💵 Số tiền: {so_tien:,}đ
🔗 Tài khoản: {h(u['tai_khoan'])}
📅 Thời gian: {now_vn().strftime('%d/%m/%Y %H:%M')}""",
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    await update.message.reply_text(
        f"""✅ <b>ĐÃ GỬI YÊU CẦU RÚT TIỀN</b>

📋 Mã: <code>{h(request_id)}</code>
💵 Số tiền: {so_tien:,}đ
⏳ Đang chờ Admin duyệt.""",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )

    context.user_data.pop("dang_rut_tien", None)
    return ConversationHandler.END


# ============================================================

# ============================================================
# SECURITY / BUSINESS-RULE HELPERS
# ============================================================
def user_is_verified(user_id: int) -> bool:
    """Kiểm tra trạng thái xác minh người thật của người dùng."""
    try:
        u = get_user(user_id)
        return bool(u and u.get("xac_minh_nguoi_that", 0))
    except Exception:
        LOGGER.exception(
            "Không thể kiểm tra trạng thái xác minh user_id=%s", user_id
        )
        return False


# ADMIN
# ============================================================
async def _admin_dashboard_content():
    with db() as conn:
        tong_nguoi = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        tong_cho_rut = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        tong_cho_nap = conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
        tong_cho_xac_minh = conn.execute("SELECT COUNT(*) FROM verification_requests WHERE status='pending'").fetchone()[0]
        tong_so_du = conn.execute("SELECT COALESCE(SUM(so_du),0) FROM users").fetchone()[0]
        nguoi_bi_khoa = conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0]
        ngay_prefix = now_vn().strftime("%d/%m/%Y") + "%"
        nguoi_moi_hom_nay = conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao LIKE ?", (ngay_prefix,)).fetchone()[0]
        rut_hom_nay = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved' AND thoi_gian LIKE ?", (ngay_prefix,)).fetchone()[0]
        tien_rut_hom_nay = conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved' AND thoi_gian LIKE ?", (ngay_prefix,)).fetchone()[0]

    text = (
        "🎛 <b>BẢNG ĐIỀU KHIỂN ADMIN</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Người dùng: <b>{tong_nguoi:,}</b>\n"
        f"🔒 Đang khóa: <b>{nguoi_bi_khoa:,}</b>\n"
        f"💰 Tổng số dư: <b>{tong_so_du:,}đ</b>\n\n"
        "📌 <b>ĐƠN ĐANG CHỜ</b>\n"
        f"💸 Rút tiền: <b>{tong_cho_rut}</b>\n"
        f"📥 Nạp / nâng cấp: <b>{tong_cho_nap}</b>\n"
        f"🛡 Xác minh: <b>{tong_cho_xac_minh}</b>\n\n"
        "📈 <b>HÔM NAY</b>\n"
        f"💸 Đơn rút đã duyệt: <b>{rut_hom_nay}</b>\n"
        f"💵 Tiền đã rút: <b>{tien_rut_hom_nay:,}đ</b>\n"
        f"🆕 Người dùng mới: <b>{nguoi_moi_hom_nay:,}</b>\n\n"
        "⚡ Chọn chức năng bên dưới để quản lý."
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Rút tiền", callback_data="admin_ds_rut"),
            InlineKeyboardButton("📥 Nạp / cấp", callback_data="admin_ds_nap"),
        ],
        [
            InlineKeyboardButton("🛡 Xác minh", callback_data="admin_ds_xacminh"),
            InlineKeyboardButton("👥 Người dùng", callback_data="admin_ds_nguoi"),
        ],
        [
            InlineKeyboardButton("💰 Cộng tiền", callback_data="admin_cong_tien"),
            InlineKeyboardButton("💸 Trừ tiền", callback_data="admin_tru_tien"),
        ],
        [
            InlineKeyboardButton("💰 Cộng TẤT CẢ", callback_data="admin_cong_tat_ca"),
            InlineKeyboardButton("📢 Thông báo", callback_data="admin_gui_tb"),
        ],
        [InlineKeyboardButton("🎬 Quản lý Video", callback_data="admin_video")],
        [InlineKeyboardButton("📜 Lịch sử giao dịch", callback_data="admin_lich_su")],
        [InlineKeyboardButton("🛡 Nhật ký Admin", callback_data="admin_log")],
        [InlineKeyboardButton("⚙️ Cài đặt hệ thống", callback_data="admin_settings")],
        [InlineKeyboardButton("🛡 Anti-Fraud", callback_data="admin_antifraud"), InlineKeyboardButton("📊 Thống kê", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Thông báo nâng cao", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⏰ Hẹn giờ thông báo", callback_data="admin_schedule")],
        [InlineKeyboardButton("🎁 Sự kiện", callback_data="admin_event")],
        [InlineKeyboardButton("💾 Backup dữ liệu", callback_data="admin_backup")],
        [InlineKeyboardButton("🎟️ Tạo mã thưởng", callback_data="admin_bonus_create"), InlineKeyboardButton("📤 Xuất User", callback_data="admin_export")],
        [InlineKeyboardButton("✅ DUYỆT TẤT CẢ ĐƠN", callback_data="admin_duyet_tat_ca")],
        [InlineKeyboardButton("🔄 Làm mới", callback_data="admin_refresh")],
    ])
    return text, keyboard


async def trang_quan_ly_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bạn không có quyền truy cập khu vực Admin.")
        return

    text, keyboard = await _admin_dashboard_content()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


def _admin_user_search_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Tìm người dùng", callback_data="admin_tim_nguoi")],
        [InlineKeyboardButton("📋 Tất cả người dùng", callback_data="admin_ds_nguoi")],
        [InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")],
    ])


def _admin_search_users(keyword):
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    with db() as conn:
        if keyword.isdigit():
            rows = conn.execute(
                "SELECT * FROM users WHERE CAST(id AS TEXT)=? LIMIT 20",
                (keyword,),
            ).fetchall()
        else:
            like = f"%{keyword}%"
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE LOWER(ten) LIKE LOWER(?)
                   OR LOWER(COALESCE(username, '')) LIKE LOWER(?)
                ORDER BY id
                LIMIT 20
                """,
                (like, like),
            ).fetchall()
    return [row_to_user(r) for r in rows]


def _admin_user_detail_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Cộng tiền", callback_data=f"admin_edit:cong:{user_id}"),
            InlineKeyboardButton("💸 Trừ tiền", callback_data=f"admin_edit:tru:{user_id}"),
        ],
        [
            InlineKeyboardButton("💵 Đặt số dư", callback_data=f"admin_edit:setbal:{user_id}"),
            InlineKeyboardButton("🏆 Đổi cấp", callback_data=f"admin_edit:cap:{user_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Sửa tên", callback_data=f"admin_edit:name:{user_id}"),
            InlineKeyboardButton("🏦 Sửa tài khoản", callback_data=f"admin_edit:account:{user_id}"),
        ],
        [
            InlineKeyboardButton("👥 Sửa giới thiệu", callback_data=f"admin_edit:gioithieu:{user_id}"),
            InlineKeyboardButton("🎬 Sửa video", callback_data=f"admin_edit:video:{user_id}"),
        ],
        [
            InlineKeyboardButton("🛡 Xác minh", callback_data=f"admin_edit:verify:{user_id}"),
            InlineKeyboardButton("🔓 Bỏ xác minh", callback_data=f"admin_edit:unverify:{user_id}"),
        ],
        [InlineKeyboardButton("🔄 Reset CAPTCHA", callback_data=f"admin_edit:captcha:{user_id}")],
        [InlineKeyboardButton("🔒 Khóa tài khoản", callback_data=f"admin_edit:lock:{user_id}"), InlineKeyboardButton("🔓 Mở khóa", callback_data=f"admin_edit:unlock:{user_id}")],
        [InlineKeyboardButton("📜 Lịch sử người dùng", callback_data=f"admin_history:{user_id}")],
        [InlineKeyboardButton("♻️ RESET TÀI KHOẢN", callback_data=f"admin_edit:reset:{user_id}")],
        [InlineKeyboardButton("⬅️ Danh sách người dùng", callback_data="admin_ds_nguoi")],
    ])


def _admin_user_detail_text(u):
    xac = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that", 0) else "🔒 Chưa xác minh"
    username_line = f"🔗 Username: <code>@{h(u['username'])}</code>\n" if u.get("username") else ""
    return (
        "👤 <b>QUẢN LÝ NGƯỜI DÙNG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{u['id']}</code>\n"
        f"👤 Tên: <b>{h(u['ten'])}</b>\n"
        + username_line
        + f"💰 Số dư: <b>{u['so_du']:,}đ</b>\n"
        + f"🏆 Cấp: <b>{h(u['cap_bac'])}</b>\n"
        + f"🎬 Video đã xem: <b>{u['video_da_xem']}</b>\n"
        + f"👥 Giới thiệu: <b>{u['gioi_thieu']}</b>\n"
        + f"🛡 Trạng thái: <b>{xac}</b>\n"
        + f"🔒 Tài khoản: <b>{'ĐANG KHÓA' if u.get('bi_khoa', 0) else 'Hoạt động'}</b>\n"
        + f"🔐 CAPTCHA: {'✅' if u.get('captcha_da_xac_minh', 0) else '❌'}\n"
        + f"🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>"
    )


async def _admin_hien_thi_nguoi(query, user_id):
    u = get_user(user_id)
    if not u:
        await query.answer("❌ Không tìm thấy người dùng.", show_alert=True)
        return
    await query.message.reply_text(
        _admin_user_detail_text(u),
        parse_mode="HTML",
        reply_markup=_admin_user_detail_keyboard(user_id),
    )


def _admin_video_keyboard(rows=None):
    buttons = [
        [InlineKeyboardButton("➕ Thêm video", callback_data="admin_video_add")],
        [InlineKeyboardButton("📋 Danh sách video", callback_data="admin_video_list")],
    ]
    if rows:
        for row in rows[:30]:
            buttons.append([InlineKeyboardButton(f"🗑 Xóa video #{row['id']}", callback_data=f"admin_video_del:{row['id']}")])
    buttons.append([InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")])
    return InlineKeyboardMarkup(buttons)


async def _admin_video_list_message(query):
    with db() as conn:
        rows = conn.execute("SELECT * FROM video_links ORDER BY id DESC LIMIT 100").fetchall()
    if not rows:
        text = "🎬 <b>QUẢN LÝ VIDEO</b>\n━━━━━━━━━━━━━━━━━━━━\n\nChưa có video nào.\n\n➕ Hãy thêm link TikTok để hệ thống chọn ngẫu nhiên cho người dùng."
    else:
        text = f"🎬 <b>QUẢN LÝ VIDEO</b>\n━━━━━━━━━━━━━━━━━━━━\nTổng: <b>{len(rows)}</b> video\n\n"
        for row in rows:
            text += f"🎬 <b>#{row['id']}</b> — <code>{h(row['url'])}</code>\n"
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=_admin_video_keyboard(rows))


async def xu_ly_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Không có quyền.", show_alert=True)
        return

    data = query.data


    if data == "admin_bonus_create":
        await query.answer()
        context.user_data["admin_bonus_create"] = True
        await query.message.reply_text("🎟️ Nhập mã theo dạng: <code>CODE 10000 100</code>\n\nCODE = mã thưởng, 10000 = số tiền, 100 = số lượt tối đa.", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return ADMIN_TAO_MA

    if data == "admin_export":
        import csv
        with db() as conn:
            rows=conn.execute("SELECT id,ten,username,cap_bac,so_du,video_da_xem,gioi_thieu,tai_khoan,bi_khoa FROM users ORDER BY id").fetchall()
        out=io.StringIO(); w=csv.writer(out); w.writerow(["id","ten","username","cap_bac","so_du","video_da_xem","gioi_thieu","tai_khoan","bi_khoa"])
        for r in rows: w.writerow([r[x] for x in ["id","ten","username","cap_bac","so_du","video_da_xem","gioi_thieu","tai_khoan","bi_khoa"]])
        bio=io.BytesIO(out.getvalue().encode("utf-8-sig")); bio.name="users_export.csv"
        await query.message.reply_document(document=bio, caption=f"📤 Xuất {len(rows)} người dùng.")
        admin_log("Xuất danh sách user")
        return

    if data == "admin_stats":
        await query.answer(); await v2_admin_stats(query); return
    if data == "admin_antifraud":
        await query.answer(); await v2_admin_antifraud(query); return
    if data == "admin_fraud_scan":
        await query.answer(); await v2_fraud_scan(query); return
    if data == "admin_event":
        await query.answer(); await v2_admin_event(query); return
    if data == "admin_broadcast":
        await query.answer(); return await v2_admin_broadcast(query, context)
    if data == "admin_schedule":
        await query.answer(); return await v2_admin_schedule(query, context)
    if data == "admin_backup":
        await query.answer(); await v2_admin_backup(query); return

    if data == "admin_video":
        await query.answer()
        await _admin_video_list_message(query)
        return

    if data == "admin_video_list":
        await query.answer()
        await _admin_video_list_message(query)
        return

    if data == "admin_video_add":
        await query.answer()
        await query.message.reply_text(
            "➕ <b>THÊM VIDEO TIKTOK</b>\n\nGửi link TikTok cần thêm.\nVí dụ: <code>https://vt.tiktok.com/...</code>",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
        )
        return ADMIN_VIDEO_ADD

    if data.startswith("admin_video_del:"):
        try:
            video_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("❌ ID video không hợp lệ.", show_alert=True)
            return
        with db() as conn:
            deleted = conn.execute("DELETE FROM video_links WHERE id=?", (video_id,)).rowcount
        await query.answer("🗑 Đã xóa video." if deleted else "❌ Không tìm thấy video.", show_alert=True)
        await _admin_video_list_message(query)
        return

    # --------------------------------------------------------
    # TÌM KIẾM NGƯỜI DÙNG
    # --------------------------------------------------------
    if data == "admin_tim_nguoi":
        await query.answer()
        await query.message.reply_text(
            "🔎 <b>TÌM NGƯỜI DÙNG</b>\n\n"
            "Nhập <b>ID</b>, <b>tên</b> hoặc <b>@username</b> cần tìm:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_TIM_NGUOI

    # --------------------------------------------------------
    # QUẢN LÝ TỪNG NGƯỜI DÙNG
    # --------------------------------------------------------
    if data.startswith("admin_user:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("❌ ID không hợp lệ.", show_alert=True)
            return
        context.user_data["admin_user_id"] = user_id
        await _admin_hien_thi_nguoi(query, user_id)
        return

    if data.startswith("admin_edit:"):
        parts = data.split(":")
        if len(parts) != 3:
            await query.answer("❌ Dữ liệu không hợp lệ.", show_alert=True)
            return
        action, raw_id = parts[1], parts[2]
        try:
            user_id = int(raw_id)
        except ValueError:
            await query.answer("❌ ID không hợp lệ.", show_alert=True)
            return
        if not get_user(user_id):
            await query.answer("❌ Không tìm thấy người dùng.", show_alert=True)
            return
        context.user_data["admin_user_id"] = user_id

        if action == "verify":
            with db() as conn:
                conn.execute("UPDATE users SET xac_minh_nguoi_that=1 WHERE id=?", (user_id,))
            await query.answer("✅ Đã xác minh người dùng.")
            await _admin_hien_thi_nguoi(query, user_id)
            return
        if action == "unverify":
            with db() as conn:
                conn.execute("UPDATE users SET xac_minh_nguoi_that=0 WHERE id=?", (user_id,))
            await query.answer("🔓 Đã bỏ xác minh.")
            await _admin_hien_thi_nguoi(query, user_id)
            return
        if action in {"name", "account", "gioithieu", "video"}:
            context.user_data["admin_user_action"] = action

        if action == "captcha":
            with db() as conn:
                conn.execute("UPDATE users SET captcha_da_xac_minh=0 WHERE id=?", (user_id,))
            admin_log("Reset CAPTCHA", user_id)
            await query.answer("🔄 Đã reset CAPTCHA.")
            await _admin_hien_thi_nguoi(query, user_id)
            return

        if action in {"lock", "unlock"}:
            locked = 1 if action == "lock" else 0
            with db() as conn:
                conn.execute("UPDATE users SET bi_khoa=? WHERE id=?", (locked, user_id))
            admin_log("Khóa tài khoản" if locked else "Mở khóa tài khoản", user_id)
            await query.answer("🔒 Đã khóa tài khoản." if locked else "🔓 Đã mở khóa tài khoản.", show_alert=True)
            await _admin_hien_thi_nguoi(query, user_id)
            return

        if action == "reset":
            await query.answer("⚠️ Xác nhận reset tài khoản.", show_alert=True)
            await query.message.reply_text(
                f"⚠️ <b>RESET TÀI KHOẢN</b>\n\n🆔 <code>{user_id}</code>\n\n"
                "Thao tác sẽ đưa số dư, cấp, video, giới thiệu, CAPTCHA, xác minh và tài khoản rút về mặc định.\n"
                "Tên, ID và mã giới thiệu gốc được giữ lại.\n\nBạn có chắc chắn?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Xác nhận reset", callback_data=f"admin_reset_confirm:{user_id}")],
                    [InlineKeyboardButton("❌ Hủy", callback_data=f"admin_user:{user_id}")],
                ]),
            )
            return

        context.user_data["admin_user_action"] = action
        prompts = {
            "cong": "💰 Nhập số tiền muốn CỘNG cho người dùng (ví dụ: 50000):",
            "tru": "💸 Nhập số tiền muốn TRỪ cho người dùng (ví dụ: 50000):",
            "setbal": "💵 Nhập SỐ DƯ MỚI (ví dụ: 100000):",
            "cap": "🏆 Nhập cấp mới:\n" + "\n".join(f"• {x}" for x in CAP_BAC_CONFIG),
            "name": "✏️ Nhập tên mới của người dùng:",
            "account": "🏦 Nhập tài khoản rút tiền mới (hoặc nhập - để xóa):",
            "gioithieu": "👥 Nhập số người đã giới thiệu mới (số nguyên >= 0):",
            "video": "🎬 Nhập số video đã xem mới (số nguyên >= 0):",
        }
        await query.message.reply_text(prompts.get(action, "Nhập giá trị:"), reply_markup=ReplyKeyboardRemove())
        return ADMIN_SUA_NGUOI

    if data.startswith("admin_reset_confirm:"):
        try:
            user_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("❌ ID không hợp lệ.", show_alert=True)
            return
        if not get_user(user_id):
            await query.answer("❌ Không tìm thấy người dùng.", show_alert=True)
            return
        with db() as conn:
            conn.execute(
                """UPDATE users SET cap_bac=?, so_du=0, video_da_xem=0, video_ngay=0,
                gioi_thieu=0, captcha_da_xac_minh=0, dang_xem=0, tai_khoan=NULL,
                xac_minh_nguoi_that=0, ngay_reset=? WHERE id=?""",
                ("Thành viên", today_vn(), user_id),
            )
        admin_log("Reset tài khoản", user_id)
        await query.answer("♻️ Đã reset tài khoản.", show_alert=True)
        await _admin_hien_thi_nguoi(query, user_id)
        return

    # --------------------------------------------------------
    # XÁC MINH NGƯỜI THẬT
    # --------------------------------------------------------
    if data.startswith("xacminh_ok:") or data.startswith("xacminh_no:"):
        await query.answer()
        request_id = data.split(":", 1)[1]

        with db() as conn:
            yc = conn.execute(
                """
                SELECT * FROM verification_requests
                WHERE request_id=? AND status='pending'
                """,
                (request_id,),
            ).fetchone()

            if not yc:
                await query.edit_message_text(
                    "❌ Yêu cầu không tồn tại hoặc đã được xử lý."
                )
                return

            if data.startswith("xacminh_ok:"):
                if not yc["photo_file_id"]:
                    await query.answer(
                        "❌ Chưa có biên lai. Yêu cầu người dùng gửi ảnh trước khi duyệt.",
                        show_alert=True,
                    )
                    return

                conn.execute(
                    """
                    UPDATE verification_requests
                    SET status='approved'
                    WHERE request_id=? AND status='pending'
                    """,
                    (request_id,),
                )
                conn.execute(
                    """
                    UPDATE users
                    SET xac_minh_nguoi_that=1
                    WHERE id=?
                    """,
                    (yc["user_id"],),
                )

                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=f"""🛡 <b>XÁC MINH THÀNH CÔNG</b>

✅ Admin đã xác nhận yêu cầu của bạn.

💰 Phí xác minh đã xác nhận: {yc['phi']:,}đ
🔓 Chức năng rút tiền đã được mở khóa.

Bạn có thể nhấn <b>💰 Rút Tiền</b> để tiếp tục.""",
                    parse_mode="HTML",
                )

                await query.edit_message_text(
                    f"✅ Đã duyệt xác minh cho ID {yc['user_id']}."
                )
            else:
                conn.execute(
                    """
                    UPDATE verification_requests
                    SET status='rejected'
                    WHERE request_id=? AND status='pending'
                    """,
                    (request_id,),
                )

                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=f"""❌ <b>XÁC MINH BỊ TỪ CHỐI</b>

📋 Mã: <code>{h(request_id)}</code>

Vui lòng liên hệ hỗ trợ để được kiểm tra.""",
                    parse_mode="HTML",
                )

                await query.edit_message_text(
                    f"❌ Đã từ chối xác minh ID {yc['user_id']}."
                )
        return

    await query.answer()

    if data.startswith("admin_history:"):
        user_id = int(data.split(":", 1)[1])
        with db() as conn:
            rows = conn.execute("SELECT * FROM balance_history WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
            withdrawals = conn.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY thoi_gian DESC LIMIT 10", (user_id,)).fetchall()
        text = f"📜 <b>LỊCH SỬ NGƯỜI DÙNG</b>\n🆔 <code>{user_id}</code>\n━━━━━━━━━━━━━━━━━━━━\n"
        if rows:
            text += "\n💰 <b>BIẾN ĐỘNG SỐ DƯ</b>\n" + "\n".join(f"{r['created_at']} | {'+' if r['delta'] >= 0 else ''}{r['delta']:,}đ | {h(r['reason'] or '')}" for r in rows)
        else:
            text += "\n💰 Chưa có lịch sử số dư.\n"
        if withdrawals:
            text += "\n💸 <b>LỊCH SỬ RÚT</b>\n" + "\n".join(f"{r['request_id']} | {r['so_tien']:,}đ | {r['status']}" for r in withdrawals)
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Người dùng", callback_data=f"admin_user:{user_id}")]]))
        return

    if data == "admin_lich_su":
        with db() as conn:
            rows = conn.execute("SELECT * FROM withdrawals ORDER BY thoi_gian DESC LIMIT 30").fetchall()
        text = "📜 <b>LỊCH SỬ GIAO DỊCH</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "\n".join(f"{r['request_id']} | ID {r['user_id']} | {r['so_tien']:,}đ | {r['status']}" for r in rows) or "Chưa có giao dịch."
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_home")]]))
        return

    if data == "admin_log":
        with db() as conn:
            rows = conn.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 30").fetchall()
        text = "🛡 <b>NHẬT KÝ ADMIN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "\n".join(f"{r['created_at']} | {h(r['action'])} | ID {r['target_user_id'] or '-'} | {h(r['detail'] or '')}" for r in rows) or "Chưa có log."
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_home")]]))
        return

    if data == "admin_settings":
        min_rut = int(get_setting("rut_toi_thieu", RUT_TOI_THIEU))
        max_rut = int(get_setting("rut_toi_da", 0))
        max_ngay = int(get_setting("rut_so_lan_ngay", 0))
        cooldown = int(get_setting("rut_cooldown_giay", 0))
        text = ("⚙️ <b>CÀI ĐẶT HỆ THỐNG</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Rút tối thiểu: <b>{min_rut:,}đ</b>\n"
                f"💰 Rút tối đa: <b>{max_rut:,}đ</b> (0 = không giới hạn)\n"
                f"📅 Số lần rút/ngày: <b>{max_ngay}</b> (0 = không giới hạn)\n"
                f"⏱️ Khoảng cách giữa 2 lần rút: <b>{cooldown} giây</b> (0 = tắt)\n\n"
                "Chọn mục cần thay đổi:")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Rút tối thiểu", callback_data="admin_set:min"), InlineKeyboardButton("💰 Rút tối đa", callback_data="admin_set:max")],
            [InlineKeyboardButton("📅 Số lần/ngày", callback_data="admin_set:daily"), InlineKeyboardButton("⏱️ Khoảng cách", callback_data="admin_set:cooldown")],
            [InlineKeyboardButton("⬅️ Admin", callback_data="admin_home")],
        ])
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data in {"admin_set:min", "admin_set:max"}:
        context.user_data["admin_setting"] = data.split(":", 1)[1]
        await query.message.reply_text("💰 Nhập số tiền mới:", reply_markup=ReplyKeyboardRemove())
        return ADMIN_SUA_NGUOI

    # --------------------------------------------------------
    # DASHBOARD ADMIN
    # --------------------------------------------------------
    if data in ("admin_home", "admin_refresh"):
        text, keyboard = await _admin_dashboard_content()
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    # --------------------------------------------------------
    # NẠP/NÂNG CẤP
    # --------------------------------------------------------
    if data.startswith("duyet_nap_ok:") or data.startswith("duyet_nap_no:"):
        ma_nap = data.split(":", 1)[1]

        with db() as conn:
            yc = conn.execute(
                """
                SELECT * FROM deposits
                WHERE request_id=? AND status='pending'
                """,
                (ma_nap,),
            ).fetchone()

            if not yc:
                await query.edit_message_text(
                    "❌ Yêu cầu không tồn tại hoặc đã xử lý."
                )
                return

            if data.startswith("duyet_nap_ok:"):
                if not yc["photo_file_id"]:
                    await query.answer(
                        "❌ Chưa có biên lai. Không thể duyệt đơn nạp.",
                        show_alert=True,
                    )
                    return
                conn.execute(
                    """
                    UPDATE deposits
                    SET status='approved'
                    WHERE request_id=? AND status='pending'
                    """,
                    (ma_nap,),
                )
                conn.execute(
                    "UPDATE users SET cap_bac=? WHERE id=?",
                    (yc["cap_moi"], yc["user_id"]),
                )

                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=f"""✅ <b>NÂNG CẤP THÀNH CÔNG!</b>

🏆 Cấp hiện tại: {h(yc['cap_moi'])}
📺 Giới hạn: {CAP_BAC_CONFIG[yc['cap_moi']]['gioi_han_xem_ngay']} video/ngày
💵 Thưởng/video: {CAP_BAC_CONFIG[yc['cap_moi']]['xu_moi_video']:,}đ""",
                    parse_mode="HTML",
                )
                await query.edit_message_text(
                    f"✅ Đã duyệt {h(ma_nap)} → {h(yc['ten'])} lên {h(yc['cap_moi'])}."
                )
            else:
                conn.execute(
                    """
                    UPDATE deposits SET status='rejected'
                    WHERE request_id=? AND status='pending'
                    """,
                    (ma_nap,),
                )
                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=f"""❌ <b>YÊU CẦU NÂNG CẤP BỊ TỪ CHỐI</b>

🔔 Mã: {h(ma_nap)}
Vui lòng kiểm tra lại thông tin chuyển khoản hoặc liên hệ hỗ trợ.""",
                    parse_mode="HTML",
                )
                await query.edit_message_text(
                    f"❌ Đã từ chối {h(ma_nap)}."
                )
        return

    # --------------------------------------------------------
    # RÚT TIỀN
    # --------------------------------------------------------
    if data.startswith("duyet_ok:") or data.startswith("duyet_no:"):
        request_id = data.split(":", 1)[1]

        with db() as conn:
            conn.execute("BEGIN")
            yc = conn.execute(
                """
                SELECT * FROM withdrawals
                WHERE request_id=? AND status='pending'
                """,
                (request_id,),
            ).fetchone()

            if not yc:
                conn.rollback()
                await query.edit_message_text(
                    "❌ Yêu cầu không tồn tại hoặc đã được xử lý."
                )
                return

            if data.startswith("duyet_no:"):
                changed = conn.execute(
                    """
                    UPDATE withdrawals
                    SET status='rejected'
                    WHERE request_id=? AND status='pending'
                    """,
                    (request_id,),
                ).rowcount

                if changed != 1:
                    conn.rollback()
                    await query.edit_message_text(
                        "❌ Yêu cầu đã được xử lý bởi thao tác khác."
                    )
                    return

                conn.commit()

                try:
                    await context.bot.send_message(
                        chat_id=yc["user_id"],
                        text=(
                            "❌ <b>RÚT TIỀN BỊ TỪ CHỐI</b>\n\n"
                            f"📋 Mã: <code>{h(request_id)}</code>\n"
                            f"💵 Số tiền: {yc['so_tien']:,}đ\n"
                            "Vui lòng liên hệ hỗ trợ."
                        ),
                        parse_mode="HTML",
                    )
                except Exception as exc:
                    print("SEND REJECT NOTICE ERROR:", repr(exc))

                await query.edit_message_text(
                    f"❌ Đã từ chối {h(request_id)}."
                )
                return

            changed_balance = conn.execute(
                """
                UPDATE users
                SET so_du = so_du - ?
                WHERE id=? AND so_du >= ?
                """,
                (yc["so_tien"], yc["user_id"], yc["so_tien"]),
            ).rowcount

            if changed_balance != 1:
                conn.rollback()
                await query.edit_message_text(
                    "❌ Số dư hiện tại không đủ để duyệt đơn."
                )
                return

            changed_request = conn.execute(
                """
                UPDATE withdrawals
                SET status='approved'
                WHERE request_id=? AND status='pending'
                """,
                (request_id,),
            ).rowcount

            if changed_request != 1:
                conn.rollback()
                await query.edit_message_text(
                    "❌ Yêu cầu đã được xử lý bởi thao tác khác."
                )
                return

            conn.commit()

        try:
            await context.bot.send_message(
                chat_id=yc["user_id"],
                text=(
                    "✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>\n\n"
                    f"📋 Mã: <code>{h(request_id)}</code>\n"
                    f"💵 Số tiền: {yc['so_tien']:,}đ\n"
                    f"🔗 Tài khoản: {h(yc['tai_khoan'])}\n"
                    "✅ Đã duyệt."
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            print("SEND APPROVE NOTICE ERROR:", repr(exc))

        # Chỉ khi Admin DUYỆT thành công mới đăng thông báo vào kênh @rutxutiktok.
        await gui_thong_bao_rut_thanh_cong(
            context,
            request_id,
            yc["so_tien"],
            yc["tai_khoan"],
            yc["ten"],
        )

        await query.edit_message_text(
            f"✅ Đã duyệt {h(request_id)} — Trừ {yc['so_tien']:,}đ."
        )
        return

    # --------------------------------------------------------
    # DUYỆT TẤT CẢ ĐƠN
    # --------------------------------------------------------
    if data == "admin_duyet_tat_ca":
        approved_deposits = []
        approved_withdrawals = []
        skipped_withdrawals = []
        skipped_deposits = []
        approved_verifications = []

        with db() as conn:
            conn.execute("BEGIN")

            verification_rows = conn.execute(
                """
                SELECT * FROM verification_requests
                WHERE status='pending'
                ORDER BY thoi_gian ASC
                """
            ).fetchall()

            for yc in verification_rows:
                user = conn.execute(
                    "SELECT id FROM users WHERE id=?",
                    (yc["user_id"],),
                ).fetchone()

                if not user or not yc["photo_file_id"]:
                    continue

                changed = conn.execute(
                    """
                    UPDATE verification_requests
                    SET status='approved'
                    WHERE request_id=? AND status='pending'
                    """,
                    (yc["request_id"],),
                ).rowcount

                if changed == 1:
                    conn.execute(
                        """
                        UPDATE users
                        SET xac_minh_nguoi_that=1
                        WHERE id=?
                        """,
                        (yc["user_id"],),
                    )
                    approved_verifications.append(dict(yc))

            deposit_rows = conn.execute(
                """
                SELECT * FROM deposits
                WHERE status='pending'
                ORDER BY thoi_gian ASC
                """
            ).fetchall()

            for yc in deposit_rows:
                user = conn.execute(
                    "SELECT id FROM users WHERE id=?",
                    (yc["user_id"],),
                ).fetchone()

                if not user or not yc["photo_file_id"]:
                    skipped_deposits.append(yc["request_id"])
                    continue

                changed = conn.execute(
                    """
                    UPDATE deposits
                    SET status='approved'
                    WHERE request_id=? AND status='pending'
                    """,
                    (yc["request_id"],),
                ).rowcount

                if changed != 1:
                    continue

                conn.execute(
                    """
                    UPDATE users
                    SET cap_bac=?
                    WHERE id=?
                    """,
                    (yc["cap_moi"], yc["user_id"]),
                )
                approved_deposits.append(dict(yc))

            withdrawal_rows = conn.execute(
                """
                SELECT * FROM withdrawals
                WHERE status='pending'
                ORDER BY thoi_gian ASC
                """
            ).fetchall()

            for yc in withdrawal_rows:
                changed_balance = conn.execute(
                    """
                    UPDATE users
                    SET so_du = so_du - ?
                    WHERE id=? AND so_du >= ?
                    """,
                    (yc["so_tien"], yc["user_id"], yc["so_tien"]),
                ).rowcount

                if changed_balance != 1:
                    skipped_withdrawals.append(dict(yc))
                    continue

                changed_request = conn.execute(
                    """
                    UPDATE withdrawals
                    SET status='approved'
                    WHERE request_id=? AND status='pending'
                    """,
                    (yc["request_id"],),
                ).rowcount

                if changed_request == 1:
                    approved_withdrawals.append(dict(yc))
                else:
                    conn.execute(
                        """
                        UPDATE users
                        SET so_du = so_du + ?
                        WHERE id=?
                        """,
                        (yc["so_tien"], yc["user_id"]),
                    )

            conn.commit()

        for yc in approved_verifications:
            try:
                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=f"""🛡 <b>XÁC MINH THÀNH CÔNG</b>

✅ Yêu cầu xác minh của bạn đã được Admin duyệt.
💰 Phí xác minh đã xác nhận: {yc['phi']:,}đ
🔓 Chức năng rút tiền đã được mở khóa.""",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        for yc in approved_deposits:
            try:
                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=(
                        "✅ <b>NÂNG CẤP THÀNH CÔNG!</b>\n\n"
                        f"🏆 Cấp hiện tại: {h(yc['cap_moi'])}\n"
                        f"📺 Giới hạn: {CAP_BAC_CONFIG[yc['cap_moi']]['gioi_han_xem_ngay']} video/ngày\n"
                        f"💵 Thưởng/video: {CAP_BAC_CONFIG[yc['cap_moi']]['xu_moi_video']:,}đ\n"
                        f"🔔 Mã: <code>{h(yc['request_id'])}</code>"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        for yc in approved_withdrawals:
            try:
                await context.bot.send_message(
                    chat_id=yc["user_id"],
                    text=(
                        "✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>\n\n"
                        f"📋 Mã: <code>{h(yc['request_id'])}</code>\n"
                        f"💵 Số tiền: {yc['so_tien']:,}đ\n"
                        f"🔗 Tài khoản: {h(yc['tai_khoan'])}\n"
                        "✅ Đã duyệt."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

            # Gửi thông báo duyệt từng đơn vào kênh RÚT XU TIKTOK.
            await gui_thong_bao_rut_thanh_cong(
                context,
                yc["request_id"],
                yc["so_tien"],
                yc["tai_khoan"],
                yc["ten"],
            )

        msg = (
            "✅ <b>ĐÃ DUYỆT TẤT CẢ ĐƠN CÓ THỂ XỬ LÝ</b>\n\n"
            f"🛡 Xác minh: <b>{len(approved_verifications)}</b> đơn\n"
            f"📥 Nạp/nâng cấp: <b>{len(approved_deposits)}</b> đơn\n"
            f"💸 Rút tiền: <b>{len(approved_withdrawals)}</b> đơn\n"
            f"⚠️ Rút bỏ qua do số dư không đủ: <b>{len(skipped_withdrawals)}</b> đơn\n"
            f"⚠️ Nạp bỏ qua do thiếu biên lai/người dùng: <b>{len(skipped_deposits)}</b> đơn"
        )

        if skipped_withdrawals:
            msg += "\n\n💸 <b>CÁC ĐƠN RÚT CHƯA DUYỆT:</b>"
            for yc in skipped_withdrawals[:10]:
                msg += (
                    f"\n• <code>{h(yc['request_id'])}</code>"
                    f" — {yc['so_tien']:,}đ"
                )
            if len(skipped_withdrawals) > 10:
                msg += f"\n• ... và {len(skipped_withdrawals) - 10} đơn khác"

        await query.edit_message_text(msg, parse_mode="HTML")
        return

    # --------------------------------------------------------
    # ADMIN ACTIONS
    # --------------------------------------------------------
    if data == "admin_cong_tien":
        context.user_data["admin_hanh_dong"] = "cong"
        await query.message.reply_text(
            "💰 Nhập: ID số_tiền\nVí dụ: 123456789 500000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_CONG_SO_DU

    if data == "admin_tru_tien":
        context.user_data["admin_hanh_dong"] = "tru"
        await query.message.reply_text(
            "💸 Nhập: ID số_tiền\nVí dụ: 123456789 100000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_TRU_SO_DU

    if data == "admin_cong_tat_ca":
        context.user_data["admin_hanh_dong"] = "cong_tat_ca"
        await query.message.reply_text(
            "💰 Nhập số tiền muốn cộng cho mọi người:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_CONG_TAT_CA

    if data == "admin_gui_tb":
        await query.message.reply_text(
            "📢 Nhập nội dung thông báo:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_GUI_TB

    if data == "admin_ds_rut":
        with db() as conn:
            rows = conn.execute(
                "SELECT w.* FROM withdrawals w JOIN users u ON u.id = w.user_id WHERE w.status='pending' AND u.xac_minh_nguoi_that=1 ORDER BY w.thoi_gian DESC"
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "✅ <b>KHÔNG CÓ ĐƠN RÚT ĐANG CHỜ</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_home")]])
            )
            return

        await query.message.reply_text(
            f"💸 <b>ĐƠN RÚT ĐANG CHỜ: {len(rows)}</b>\n\n"
            "Chọn từng đơn để duyệt hoặc từ chối.",
            parse_mode="HTML",
        )
        for yc in rows[:50]:
            text = (
                f"💸 <b>{yc['so_tien']:,}đ</b>\n"
                f"👤 {h(yc['ten'])}\n"
                f"🆔 <code>{yc['user_id']}</code>\n"
                f"🏦 {h(yc['tai_khoan'])}\n"
                f"📋 <code>{h(yc['request_id'])}</code>\n"
                f"🕒 {h(yc['thoi_gian'])}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Duyệt", callback_data=f"duyet_ok:{yc['request_id']}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"duyet_no:{yc['request_id']}"),
            ]])
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        if len(rows) > 50:
            await query.message.reply_text(f"⚠️ Chỉ hiển thị 50/{len(rows)} đơn để tránh quá dài.")
        await query.message.reply_text("⬅️", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Quay lại Admin", callback_data="admin_home")]]))
        return

    if data == "admin_ds_nap":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM deposits WHERE status='pending' ORDER BY thoi_gian DESC"
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "✅ <b>KHÔNG CÓ ĐƠN NẠP / NÂNG CẤP</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_home")]])
            )
            return

        await query.message.reply_text(
            f"📥 <b>ĐƠN NẠP / NÂNG CẤP: {len(rows)}</b>\n\nChọn từng đơn để xử lý.",
            parse_mode="HTML",
        )
        for yc in rows[:50]:
            text = (
                f"📥 <b>{yc['gia']:,}đ</b> → <b>{h(yc['cap_moi'])}</b>\n"
                f"👤 {h(yc['ten'])} | 🆔 <code>{yc['user_id']}</code>\n"
                f"📋 <code>{h(yc['request_id'])}</code>\n"
                f"🕒 {h(yc['thoi_gian'])}\n"
                f"🧾 Biên lai: {'✅ Có' if yc['photo_file_id'] else '❌ Chưa có'}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Duyệt", callback_data=f"duyet_nap_ok:{yc['request_id']}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"duyet_nap_no:{yc['request_id']}"),
            ]])
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        if len(rows) > 50:
            await query.message.reply_text(f"⚠️ Chỉ hiển thị 50/{len(rows)} đơn.")
        await query.message.reply_text("⬅️", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Quay lại Admin", callback_data="admin_home")]]))
        return

    if data == "admin_ds_xacminh":
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM verification_requests WHERE status='pending' ORDER BY thoi_gian DESC"
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "✅ <b>KHÔNG CÓ ĐƠN XÁC MINH</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_home")]])
            )
            return

        await query.message.reply_text(
            f"🛡 <b>ĐƠN XÁC MINH: {len(rows)}</b>\n\nChọn từng đơn để xử lý.", parse_mode="HTML"
        )
        for yc in rows[:50]:
            text = (
                f"🛡 <b>XÁC MINH NGƯỜI THẬT</b>\n"
                f"👤 {h(yc['ten'])} | 🆔 <code>{yc['user_id']}</code>\n"
                f"💰 Phí: <b>{yc['phi']:,}đ</b>\n"
                f"📋 <code>{h(yc['request_id'])}</code>\n"
                f"🕒 {h(yc['thoi_gian'])}\n"
                f"🧾 Biên lai: {'✅ Có' if yc['photo_file_id'] else '❌ Chưa có'}"
            )
            buttons = []
            if yc['photo_file_id']:
                buttons.append([
                    InlineKeyboardButton("✅ Duyệt", callback_data=f"xacminh_ok:{yc['request_id']}"),
                    InlineKeyboardButton("❌ Từ chối", callback_data=f"xacminh_no:{yc['request_id']}"),
                ])
            kb = InlineKeyboardMarkup(buttons) if buttons else None
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        if len(rows) > 50:
            await query.message.reply_text(f"⚠️ Chỉ hiển thị 50/{len(rows)} đơn.")
        await query.message.reply_text("⬅️", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Quay lại Admin", callback_data="admin_home")]]))
        return

    if data == "admin_ds_nguoi":
        rows = all_users()
        if not rows:
            await query.message.reply_text(
                "👥 <b>CHƯA CÓ NGƯỜI DÙNG</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_home")]])
            )
            return

        text = (
            f"👥 <b>QUẢN LÝ NGƯỜI DÙNG</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Tổng: <b>{len(rows):,}</b> người dùng\n\n"
            "🔎 Bạn có thể tìm theo <b>ID / tên / @username</b>."
        )
        buttons = [
            [InlineKeyboardButton("🔎 Tìm người dùng", callback_data="admin_tim_nguoi")],
            [InlineKeyboardButton("📋 Xem danh sách", callback_data="admin_ds_nguoi_all")],
            [InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")],
        ]
        await query.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "admin_ds_nguoi_all":
        rows = all_users()
        if not rows:
            await query.message.reply_text(
                "👥 <b>CHƯA CÓ NGƯỜI DÙNG</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_home")]])
            )
            return

        text = f"👥 <b>DANH SÁCH NGƯỜI DÙNG ({len(rows)})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        buttons = []
        for u in rows[:50]:
            ten = (u["ten"] or "Không tên")[:22]
            username = f" @{u['username']}" if u.get("username") else ""
            buttons.append([InlineKeyboardButton(
                f"👤 {ten}{username} | {u['id']}", callback_data=f"admin_user:{u['id']}"
            )])
        if len(rows) > 50:
            text += f"⚠️ Hiển thị 50/{len(rows)} người dùng.\n"
        buttons += [
            [InlineKeyboardButton("🔎 Tìm người dùng", callback_data="admin_tim_nguoi")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_ds_nguoi")],
        ]
        await query.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return



async def admin_xu_ly_tim_nguoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    keyword = (update.effective_message.text or "").strip()
    if keyword.startswith("@"):
        keyword = keyword[1:]

    rows = _admin_search_users(keyword)
    if not rows:
        await update.effective_message.reply_text(
            f"❌ Không tìm thấy người dùng với: <code>{h(keyword)}</code>\n\n"
            "Bạn có thể nhập lại ID, tên hoặc @username.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Tìm lại", callback_data="admin_tim_nguoi")],
                [InlineKeyboardButton("📋 Tất cả người dùng", callback_data="admin_ds_nguoi_all")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="admin_ds_nguoi")],
            ]),
        )
        return ConversationHandler.END

    buttons = []
    for u in rows:
        ten = (u["ten"] or "Không tên")[:25]
        username = f" @{u['username']}" if u.get("username") else ""
        buttons.append([InlineKeyboardButton(
            f"👤 {ten}{username} | {u['id']}", callback_data=f"admin_user:{u['id']}"
        )])
    buttons.append([InlineKeyboardButton("🔎 Tìm tiếp", callback_data="admin_tim_nguoi")])
    buttons.append([InlineKeyboardButton("⬅️ Quản lý người dùng", callback_data="admin_ds_nguoi")])

    await update.effective_message.reply_text(
        f"🔎 <b>KẾT QUẢ TÌM KIẾM</b>\n"
        f"Từ khóa: <code>{h(keyword)}</code>\n"
        f"Tìm thấy: <b>{len(rows)}</b> người dùng",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


async def admin_xu_ly_tao_ma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    raw=(update.effective_message.text or '').strip().split()
    if len(raw)!=3:
        await update.effective_message.reply_text("❌ Sai định dạng. Ví dụ: BONUS100 10000 50")
        return ADMIN_TAO_MA
    code=raw[0].upper()
    try: amount=int(raw[1]); max_uses=int(raw[2])
    except ValueError: amount=max_uses=0
    if not code.isalnum() or amount<=0 or max_uses<=0 or len(code)>32:
        await update.effective_message.reply_text("❌ Mã, số tiền hoặc số lượt không hợp lệ.")
        return ADMIN_TAO_MA
    try:
        with db() as conn:
            conn.execute("INSERT INTO bonus_codes(code,amount,max_uses,used_count,created_at,active) VALUES(?,?,0,?, ?,1)", (code,amount,max_uses,0,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
    except Exception:
        await update.effective_message.reply_text("❌ Mã đã tồn tại.")
        return ConversationHandler.END
    admin_log("Tạo mã thưởng",None,f"{code}={amount};max={max_uses}")
    context.user_data.pop('admin_bonus_create',None)
    await update.effective_message.reply_text(f"✅ Đã tạo mã <code>{h(code)}</code> · {amount:,}đ · {max_uses} lượt.",parse_mode='HTML',reply_markup=menu_chinh(ADMIN_ID))
    return ConversationHandler.END

async def admin_xu_ly_them_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    url = (update.effective_message.text or "").strip()
    if not (url.startswith("https://") and ("tiktok.com" in url.lower() or "vt.tiktok.com" in url.lower())):
        await update.effective_message.reply_text("❌ Link không hợp lệ. Hãy gửi link TikTok bắt đầu bằng https://")
        return ADMIN_VIDEO_ADD
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO video_links (url, created_at) VALUES (?, ?)",
                (url, now_vn().strftime("%d/%m/%Y %H:%M")),
            )
        msg = "✅ Đã thêm video TikTok thành công."
    except Exception:
        msg = "⚠️ Video này đã có trong danh sách hoặc không thể thêm."
    await update.effective_message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Quản lý Video", callback_data="admin_video")]]))
    return ConversationHandler.END


async def admin_xu_ly_sua_nguoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    setting = context.user_data.get("admin_setting")
    raw = (update.effective_message.text or "").strip()
    if setting:
        try:
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0: raise ValueError
            setting_keys = {"min": "rut_toi_thieu", "max": "rut_toi_da", "daily": "rut_so_lan_ngay", "cooldown": "rut_cooldown_giay"}
            key = setting_keys.get(setting)
            if not key:
                raise ValueError
            set_setting(key, value)
            admin_log("Đổi cài đặt", None, f"{key}={value}")
            context.user_data.pop("admin_setting", None)
            await update.effective_message.reply_text("✅ Đã cập nhật cài đặt hệ thống.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Cài đặt", callback_data="admin_settings")]]))
            return ConversationHandler.END
        except ValueError:
            await update.effective_message.reply_text("❌ Số tiền không hợp lệ.")
            return ADMIN_SUA_NGUOI

    user_id = context.user_data.get("admin_user_id")
    action = context.user_data.get("admin_user_action")
    if not user_id or not action:
        return ConversationHandler.END
    u = get_user(user_id)
    if not u:
        await update.effective_message.reply_text("❌ Không tìm thấy người dùng.")
        return ConversationHandler.END

    try:
        if action == "cong":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount <= 0: raise ValueError
            update_balance(user_id, amount)
            msg = f"✅ Đã cộng {amount:,}đ cho <code>{user_id}</code>."
        elif action == "tru":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount <= 0: raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET so_du = MAX(0, so_du - ?) WHERE id=?", (amount, user_id))
            msg = f"✅ Đã trừ {amount:,}đ của <code>{user_id}</code>."
        elif action == "setbal":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount < 0: raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET so_du=? WHERE id=?", (amount, user_id))
            msg = f"✅ Đã đặt số dư thành {amount:,}đ cho <code>{user_id}</code>."
        elif action == "cap":
            if raw not in CAP_BAC_CONFIG:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET cap_bac=? WHERE id=?", (raw, user_id))
            msg = f"✅ Đã đổi cấp của <code>{user_id}</code> thành <b>{h(raw)}</b>."
        elif action == "name":
            if not raw or len(raw) > 100:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET ten=? WHERE id=?", (raw, user_id))
            msg = f"✅ Đã đổi tên người dùng <code>{user_id}</code> thành <b>{h(raw)}</b>."
        elif action == "account":
            value = None if raw == "-" else raw
            if value is not None and len(value) > 200:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET tai_khoan=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã {'xóa' if value is None else 'đổi'} tài khoản rút tiền của <code>{user_id}</code>."
        elif action == "gioithieu":
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET gioi_thieu=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã đặt số người giới thiệu của <code>{user_id}</code> thành <b>{value}</b>."
        elif action == "video":
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET video_da_xem=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã đặt số video đã xem của <code>{user_id}</code> thành <b>{value}</b>."
        else:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("❌ Giá trị không hợp lệ. Vui lòng nhập lại.")
        return ADMIN_SUA_NGUOI

    if action in {"cong", "tru", "setbal"}:
        latest = get_user(user_id)
        if latest:
            admin_log("Điều chỉnh số dư", user_id, msg.replace("<code>", "").replace("</code>", "").replace("<b>", "").replace("</b>", ""))
            record_balance_change(user_id, ADMIN_ID, latest["so_du"] - u["so_du"], latest["so_du"], action)
    else:
        admin_log(f"Sửa {action}", user_id)
    context.user_data.pop("admin_user_action", None)
    await update.effective_message.reply_text(
        msg, parse_mode="HTML", reply_markup=menu_chinh(ADMIN_ID)
    )
    return ConversationHandler.END


async def admin_xu_ly_cong_tru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    action = context.user_data.get("admin_hanh_dong")
    text = update.effective_message.text.strip()

    if action == "cong_tat_ca":
        try:
            so_tien = int(
                text.replace(".", "").replace(",", "").replace("đ", "").strip()
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Số tiền không hợp lệ.",
                reply_markup=menu_chinh(ADMIN_ID),
            )
            return ConversationHandler.END

        if so_tien <= 0:
            await update.message.reply_text(
                "❌ Số tiền phải > 0.",
                reply_markup=menu_chinh(ADMIN_ID),
            )
            return ConversationHandler.END

        rows = all_users()
        for u in rows:
            update_balance(u["id"], so_tien)
            try:
                new_balance = get_user(u["id"])["so_du"]
                await context.bot.send_message(
                    chat_id=u["id"],
                    text=(
                        f"💰 Hệ thống cộng +{so_tien:,}đ\n"
                        f"💵 Số dư mới: {new_balance:,}đ"
                    ),
                )
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ Đã cộng {so_tien:,}đ cho {len(rows)} người.",
            reply_markup=menu_chinh(ADMIN_ID),
        )
        context.user_data.pop("admin_hanh_dong", None)
        return ConversationHandler.END

    try:
        uid_s, amount_s = text.split()
        uid = int(uid_s)
        amount = int(
            amount_s.replace(".", "").replace(",", "").replace("đ", "")
        )
    except (ValueError, TypeError):
        await update.message.reply_text(
            "❌ Định dạng: 123456789 500000",
            reply_markup=menu_chinh(ADMIN_ID),
        )
        return ConversationHandler.END

    u = get_user(uid)
    if not u:
        await update.message.reply_text(
            "❌ Người dùng không tồn tại.",
            reply_markup=menu_chinh(ADMIN_ID),
        )
        return ConversationHandler.END

    if amount <= 0:
        await update.message.reply_text(
            "❌ Số tiền phải > 0.",
            reply_markup=menu_chinh(ADMIN_ID),
        )
        return ConversationHandler.END

    if action == "cong":
        update_balance(uid, amount)
        new_balance = get_user(uid)["so_du"]

        await update.message.reply_text(
            f"✅ Đã cộng +{amount:,}đ cho {uid}.\n"
            f"💵 Số dư mới: {new_balance:,}đ",
            reply_markup=menu_chinh(ADMIN_ID),
        )

        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"💰 Bạn được cộng +{amount:,}đ.\n"
                    f"💵 Số dư mới: {new_balance:,}đ"
                ),
            )
        except Exception:
            pass

    elif action == "tru":
        if u["so_du"] < amount:
            await update.message.reply_text(
                "❌ Số dư không đủ.",
                reply_markup=menu_chinh(ADMIN_ID),
            )
            return ConversationHandler.END

        update_balance(uid, -amount)
        new_balance = get_user(uid)["so_du"]

        await update.message.reply_text(
            f"✅ Đã trừ -{amount:,}đ của {uid}.\n"
            f"💵 Số dư mới: {new_balance:,}đ",
            reply_markup=menu_chinh(ADMIN_ID),
        )

        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"💸 Tài khoản bị trừ -{amount:,}đ.\n"
                    f"💵 Số dư mới: {new_balance:,}đ"
                ),
            )
        except Exception:
            pass

    context.user_data.pop("admin_hanh_dong", None)
    return ConversationHandler.END


async def admin_xu_ly_gui_tb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    if context.user_data.get("v2_broadcast"):
        await v2_process_broadcast(update, context)
        return ConversationHandler.END
    if context.user_data.get("v2_schedule"):
        await v2_process_schedule(update, context)
        return ConversationHandler.END

    noi_dung = update.effective_message.text
    thanh_cong = 0
    rows = all_users()

    for u in rows:
        try:
            await context.bot.send_message(
                chat_id=u["id"],
                text=f"📢 <b>THÔNG BÁO HỆ THỐNG</b>\n\n{h(noi_dung)}",
                parse_mode="HTML",
            )
            thanh_cong += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ Đã gửi thông báo cho {thanh_cong}/{len(rows)} người.",
        reply_markup=menu_chinh(ADMIN_ID),
    )
    context.user_data.pop("admin_hanh_dong", None)
    return ConversationHandler.END


# ============================================================
# CANCEL / ERROR
# ============================================================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Đã hủy thao tác.",
        reply_markup=menu_chinh(update.effective_user.id),
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    LOGGER.exception("Unhandled Telegram error", exc_info=context.error)


# ============================================================
# V2 FEATURE PACK: anti-fraud, stats, broadcast, wheel, events
# ============================================================
def _wheel_reward():
    rewards = [500, 1000, 2000, 5000, 10000, 0]
    odds = [35, 30, 18, 10, 5, 2]
    return random.choices(rewards, weights=odds, k=1)[0]

async def v2_vong_quay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=get_user(update.effective_user.id)
    if not u: return
    price=int(get_setting("wheel_price", 1000))
    if u["so_du"] < price:
        await update.message.reply_text(f"❌ Vòng quay giá {price:,}đ. Số dư không đủ.", reply_markup=menu_chinh(u["id"]))
        return
    await update.message.reply_text(
        f"🎡 <b>VÒNG QUAY MAY MẮN</b>\n\n💰 Phí: <b>{price:,}đ/lượt</b>\n🎁 Phần thưởng: 0đ → 10.000đ\n\nBấm quay để nhận thưởng!",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎡 QUAY NGAY", callback_data="wheel_spin")]])
    )

async def v2_wheel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=update.effective_user.id; u=get_user(uid)
    if not u: return
    price=int(get_setting("wheel_price",1000))
    with db() as conn:
        row=conn.execute("SELECT so_du FROM users WHERE id=?",(uid,)).fetchone()
        if not row or row["so_du"] < price:
            await q.answer("❌ Không đủ số dư.",show_alert=True); return
        reward=_wheel_reward()
        conn.execute("UPDATE users SET so_du=so_du-?+? WHERE id=?",(price,reward,uid))
        bal=conn.execute("SELECT so_du FROM users WHERE id=?",(uid,)).fetchone()[0]
    record_balance_change(uid,None,reward-price,bal,"Vòng quay may mắn")
    await q.edit_message_text(f"🎡 <b>KẾT QUẢ VÒNG QUAY</b>\n\n🎁 Bạn nhận: <b>{reward:,}đ</b>\n💸 Phí: {price:,}đ\n💵 Số dư: <b>{bal:,}đ</b>",parse_mode="HTML")

async def v2_admin_stats(query):
    with db() as conn:
        vals={
          "users":conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
          "balance":conn.execute("SELECT COALESCE(SUM(so_du),0) FROM users").fetchone()[0],
          "withdraw":conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved'").fetchone()[0],
          "pending":conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
          "locked":conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0],
          "videos":conn.execute("SELECT COUNT(*) FROM video_links").fetchone()[0],
          "views":conn.execute("SELECT COUNT(*) FROM video_views").fetchone()[0],
        }
    text=("📊 <b>THỐNG KÊ HỆ THỐNG</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"👥 Người dùng: <b>{vals['users']:,}</b>\n💰 Tổng số dư: <b>{vals['balance']:,}đ</b>\n"
          f"💸 Tổng tiền đã duyệt rút: <b>{vals['withdraw']:,}đ</b>\n⏳ Đơn rút chờ: <b>{vals['pending']}</b>\n"
          f"🔒 Tài khoản khóa: <b>{vals['locked']}</b>\n🎬 Video: <b>{vals['videos']}</b>\n👁 Lượt xem ghi nhận: <b>{vals['views']}</b>")
    await query.message.reply_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]]))

async def v2_admin_antifraud(query):
    with db() as conn:
        rows=conn.execute("SELECT user_id,flag,detail,created_at FROM fraud_flags WHERE status='open' ORDER BY id DESC LIMIT 30").fetchall()
    text="🛡 <b>ANTI-FRAUD</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    if not rows: text+="✅ Chưa có cảnh báo đang mở."
    else:
        for r in rows: text+=f"\n🆔 <code>{r['user_id']}</code> · <b>{h(r['flag'])}</b>\n{h(r['detail'] or '')}\n🕒 {h(r['created_at'])}\n"
    await query.message.reply_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Quét tài khoản trùng TK",callback_data="admin_fraud_scan")],[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]]))

async def v2_fraud_scan(query):
    with db() as conn:
        rows=conn.execute("SELECT tai_khoan, COUNT(*) c FROM users WHERE tai_khoan IS NOT NULL AND tai_khoan<>'' GROUP BY tai_khoan HAVING COUNT(*)>1 ORDER BY c DESC LIMIT 50").fetchall()
        count=0
        for r in rows:
            us=conn.execute("SELECT id FROM users WHERE tai_khoan=?",(r['tai_khoan'],)).fetchall()
            for u in us:
                exists=conn.execute("SELECT 1 FROM fraud_flags WHERE user_id=? AND flag='TRUNG_TAI_KHOAN' AND status='open'",(u['id'],)).fetchone()
                if not exists:
                    conn.execute("INSERT INTO fraud_flags(user_id,flag,detail,status,created_at) VALUES(?,?,?,?,?)",(u['id'],'TRUNG_TAI_KHOAN',f"Tài khoản dùng chung: {r['tai_khoan']}",'open',now_vn().strftime('%d/%m/%Y %H:%M:%S'))); count+=1
    await query.answer(f"🔎 Đã tạo {count} cảnh báo.",show_alert=True); await v2_admin_antifraud(query)

async def v2_admin_broadcast(query, context):
    await query.message.reply_text("📢 <b>THÔNG BÁO NÂNG CAO</b>\n\nGửi theo dạng:\n<code>ALL | nội dung</code>\n<code>CAP:Thành viên | nội dung</code>\n<code>USER:123456 | nội dung</code>",parse_mode="HTML",reply_markup=ReplyKeyboardRemove())
    context.user_data["v2_broadcast"]=True
    return ADMIN_GUI_TB

async def v2_process_broadcast(update, context):
    if not context.user_data.pop("v2_broadcast",False): return False
    raw=update.effective_message.text or ""
    if "|" not in raw:
        await update.message.reply_text("❌ Sai định dạng."); return True
    target,msg=[x.strip() for x in raw.split("|",1)]
    with db() as conn:
        if target.upper()=="ALL": rows=conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()
        elif target.upper().startswith("USER:"):
            rows=conn.execute("SELECT id FROM users WHERE id=?",(int(target.split(":",1)[1]),)).fetchall()
        elif target.upper().startswith("CAP:"):
            rows=conn.execute("SELECT id FROM users WHERE cap_bac=? AND bi_khoa=0",(target.split(":",1)[1],)).fetchall()
        else: rows=[]
    ok=0
    for r in rows:
        try: await context.bot.send_message(r['id'],f"📢 <b>THÔNG BÁO</b>\n\n{h(msg)}",parse_mode="HTML"); ok+=1
        except Exception: pass
    await update.message.reply_text(f"✅ Đã gửi {ok}/{len(rows)} người.",reply_markup=menu_chinh(ADMIN_ID)); return True

async def v2_admin_event(query):
    with db() as conn: rows=conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 20").fetchall()
    text="🎁 <b>SỰ KIỆN</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"#{r['id']} {h(r['name'])} · +{r['amount']:,}đ · {h(r['start_at'])} → {h(r['end_at'])}" for r in rows)
    await query.message.reply_text(text or "Chưa có sự kiện.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]]))

async def v2_auto_rank(user_id):
    u=get_user(user_id)
    if not u:return
    new=cap_bac_tu_so_nguoi(u.get('gioi_thieu',0))
    if new and new!=u['cap_bac']:
        with db() as conn: conn.execute("UPDATE users SET cap_bac=? WHERE id=?",(new,user_id))

async def v2_video_record(user_id, video_id, reward):
    try:
        with db() as conn: conn.execute("INSERT INTO video_views(video_id,user_id,watched_at,reward) VALUES(?,?,?,?)",(video_id,user_id,now_vn().strftime('%d/%m/%Y %H:%M:%S'),reward))
    except Exception: pass

async def v2_schedule_job(context):
    now=now_vn().strftime('%d/%m/%Y %H:%M')
    with db() as conn: rows=conn.execute("SELECT * FROM scheduled_notifications WHERE status='pending' AND send_at<=? ORDER BY id LIMIT 10",(now,)).fetchall()
    for r in rows:
        with db() as conn:
            if r['target']=='all': users=conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()
            else: users=conn.execute("SELECT id FROM users WHERE cap_bac=? AND bi_khoa=0",(r['target'],)).fetchall()
            conn.execute("UPDATE scheduled_notifications SET status='sent' WHERE id=?",(r['id'],))
        for u in users:
            try: await context.bot.send_message(u['id'],f"📢 <b>THÔNG BÁO</b>\n\n{h(r['content'])}",parse_mode='HTML')
            except Exception: pass

async def v2_admin_schedule(query, context):
    context.user_data["v2_schedule"] = True
    await query.message.reply_text("⏰ Nhập: <code>DD/MM/YYYY HH:MM | ALL</code> hoặc <code>DD/MM/YYYY HH:MM | Thành viên</code> | nội dung",parse_mode="HTML",reply_markup=ReplyKeyboardRemove())
    return ADMIN_GUI_TB

async def v2_process_schedule(update, context):
    if not context.user_data.pop("v2_schedule",False): return False
    raw=update.effective_message.text or ""
    parts=[x.strip() for x in raw.split("|",2)]
    if len(parts)!=3:
        await update.message.reply_text("❌ Sai định dạng. Ví dụ: 30/09/2026 20:00 | ALL | Chúc mọi người buổi tối vui vẻ."); return True
    send_at,target,msg=parts
    try: datetime.strptime(send_at,"%d/%m/%Y %H:%M")
    except ValueError:
        await update.message.reply_text("❌ Sai ngày giờ."); return True
    if target.upper()=="ALL": target="all"
    with db() as conn:
        conn.execute("INSERT INTO scheduled_notifications(target,content,send_at,status,created_at) VALUES(?,?,?,?,?)",(target,msg,send_at,"pending",now_vn().strftime("%d/%m/%Y %H:%M:%S")))
    await update.message.reply_text("✅ Đã tạo lịch thông báo.",reply_markup=menu_chinh(ADMIN_ID)); return True

async def v2_admin_backup(query):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        with db() as conn:
            for table in ("users","withdrawals","deposits","verification_requests","balance_history","admin_logs","video_links"):
                rows=conn.execute(f"SELECT * FROM {table}").fetchall()
                cols=list(rows[0].keys()) if rows else []
                out=io.StringIO(); w=csv.writer(out); w.writerow(cols)
                for r in rows: w.writerow([r[c] for c in cols])
                z.writestr(f"{table}.csv",out.getvalue())
    buf.seek(0); buf.name=f"backup_{now_vn().strftime('%Y%m%d_%H%M%S')}.zip"
    await query.message.reply_document(buf,caption="💾 Backup dữ liệu: users, withdrawals, deposits, verification, lịch sử số dư, log admin, video.")

# ============================================================
# MAIN
# ============================================================
def build_application():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    try:
        if app.job_queue:
            app.job_queue.run_repeating(v2_schedule_job, interval=60, first=10, name="scheduled_notifications")
    except Exception:
        LOGGER.exception("Không khởi động được lịch thông báo")

    # Conversation: nạp tiền
    nap_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                xu_ly_goi_nang_cap,
                pattern=r"^goi_(bac|vang|bachkim|kimcuong)$",
            ),
            CallbackQueryHandler(
                da_chuyen_khoan_callback,
                pattern=r"^dachuyen:.+$",
            ),
        ],
        states={
            NAP_GUI_ANH: [
                MessageHandler(
                    filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    nhan_anh_chuyen_khoan,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    # Conversation: rút tiền / liên kết tài khoản
    rut_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^💰 Rút Tiền$"),
                rut_tien_bat_dau,
            ),
            CallbackQueryHandler(
                lien_ket_tai_khoan_bat_dau,
                pattern=r"^lien_ket_tai_khoan$",
            ),
        ],
        states={
            NHAP_TAI_KHOAN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    nhap_thong_tin_tai_khoan,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    # Conversation: admin
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                xu_ly_admin_callback,
                pattern=r"^(admin_(cong_tien|tru_tien|cong_tat_ca|gui_tb|tim_nguoi|ds_nguoi_all|video|video_list|video_add|lich_su|log|settings|set:(min|max|daily|cooldown)|stats|antifraud|fraud_scan|broadcast|schedule|backup|event)|admin_history:\d+|admin_bonus_create|admin_export|admin_user:\d+|admin_reset_confirm:\d+|admin_edit:(cong|tru|setbal|cap|verify|unverify|captcha|reset|name|account|gioithieu|video|lock|unlock):\d+|admin_video_del:\d+)$",
            ),
        ],
        states={
            ADMIN_CONG_SO_DU: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_TRU_SO_DU: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_CONG_TAT_CA: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_SUA_NGUOI: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_sua_nguoi,
                ),
            ],
            ADMIN_TIM_NGUOI: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_tim_nguoi,
                ),
            ],
            ADMIN_VIDEO_ADD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_them_video,
                ),
            ],
            ADMIN_TAO_MA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_xu_ly_tao_ma),
            ],
            ADMIN_GUI_TB: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_gui_tb,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    # Xác minh người thật không phụ thuộc ConversationHandler.
    # Callback sẽ lưu request_id vào user_data, sau đó photo handler sẽ nhận biên lai.

    app.add_handler(
        CallbackQueryHandler(
            ve_menu_chinh_callback,
            pattern=r"^ve_menu_chinh$",
        ),
        group=0,
    )

    # Xác minh: chọn phương thức / trừ số dư 50k.
    app.add_handler(
        CallbackQueryHandler(
            xac_minh_bang_so_du_callback,
            pattern=r"^xac_minh_so_du$",
        ),
        group=0,
    )

    # Callback Admin: duyệt đơn, xác minh, danh sách, duyệt tất cả.
    app.add_handler(
        CallbackQueryHandler(
            xu_ly_admin_callback,
            pattern=(
                r"^(duyet_nap_ok|duyet_nap_no|duyet_ok|duyet_no|"
                r"xacminh_ok|xacminh_no):.+$|"
                r"^(admin_(home|refresh|ds_(rut|nap|xacminh|nguoi)|duyet_tat_ca|bonus_create|export))$"
            ),
        ),
        group=1,
    )

    app.add_handler(
        CallbackQueryHandler(
            captcha_callback,
            pattern=r"^captcha_(doi|huy)$",
        ),
        group=0,
    )

    app.add_handler(
        CallbackQueryHandler(
            kiem_tra_kenh_callback,
            pattern=r"^kiem_tra_kenh$",
        ),
        group=0,
    )

    # Tự xử lý yêu cầu tham gia kênh bằng BOT.
    # Bot phải là ADMIN của kênh và có quyền duyệt yêu cầu tham gia.
    app.add_handler(
        ChatJoinRequestHandler(
            xu_ly_yeu_cau_tham_gia_kenh,
        ),
        group=0,
    )

    app.add_handler(
        CallbackQueryHandler(
            nhan_thuong_callback,
            pattern=r"^nhan_thuong:.+$",
        ),
        group=0,
    )

    app.add_handler(
        CallbackQueryHandler(
            rut_bi_khoa_callback,
            pattern=r"^rut_bi_khoa$",
        ),
        group=0,
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chan_user_bi_khoa), group=-2)
    app.add_handler(CallbackQueryHandler(chan_user_bi_khoa, pattern=r".*"), group=-2)

    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("cancel", cancel), group=0)

    app.add_handler(nap_conv, group=1)
    app.add_handler(rut_conv, group=1)
    app.add_handler(admin_conv, group=0)

    # Xác minh: chọn phương thức / xác nhận chuyển khoản / quay lại.
    app.add_handler(
        CallbackQueryHandler(
            xac_minh_nguoi_that_callback,
            pattern=r"^xac_minh_nguoi_that$",
        ),
        group=0,
    )
    app.add_handler(
        CallbackQueryHandler(
            xac_minh_nap_30k_callback,
            pattern=r"^xac_minh_nap_30k$",
        ),
        group=0,
    )
    app.add_handler(
        CallbackQueryHandler(
            xac_minh_da_chuyen_khoan_callback,
            pattern=r"^xac_minh_da_chuyen_khoan$",
        ),
        group=0,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bonus_code), group=-2)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            captcha_text_handler,
        ),
        group=-1,
    )

    app.add_handler(
        MessageHandler(filters.PHOTO, nhan_anh_xac_minh),
        group=0,
    )

    app.add_handler(
        MessageHandler(filters.Regex(r"^👤 Hồ Sơ$"), ho_so)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔍 Xem TikTok$"), xem_tiktok)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👥 Cấp Giới Thiệu$"), khu_vuc_leader)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👑 Nâng Cấp Bậc$"), nang_cap)
    )
    app.add_handler(MessageHandler(filters.Regex(r"^🎁 Nhiệm Vụ$"), nhiem_vu))
    app.add_handler(MessageHandler(filters.Regex(r"^🏆 BXH$"), bang_xep_hang))
    app.add_handler(MessageHandler(filters.Regex(r"^📜 Lịch Sử$"), lich_su_giao_dich_user))
    app.add_handler(CallbackQueryHandler(user_new_callback, pattern=r"^(task_claim:.+|bonus_redeem|user_checkin)$"), group=0)
    app.add_handler(CallbackQueryHandler(v2_wheel_callback, pattern=r"^wheel_spin$"), group=0)
    app.add_handler(MessageHandler(filters.Regex(r"^🎡 Vòng Quay$"), v2_vong_quay))
    app.add_handler(MessageHandler(filters.Regex(r"^🎧 Hỗ Trợ$"), ho_tro))
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔐 Nhập CaptCha$"), captcha)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🎛 QUẢN LÝ ADMIN$"), trang_quan_ly_admin)
    )

    app.add_error_handler(error_handler)
    return app


def run_bot():
    """Production webhook startup using python-telegram-bot's built-in server."""
    application = build_application()
    public_url = get_public_webhook_url()
    LOGGER.info("Starting built-in Telegram webhook: %s", public_url)
    LOGGER.info("Webhook listen=0.0.0.0 port=%s path=%s", RENDER_PORT, WEBHOOK_PATH)

    # PTB's built-in webhook server handles Telegram POST requests directly
    # and avoids the custom ThreadingHTTPServer/update-loop bridge.
    application.run_webhook(
        listen="0.0.0.0",
        port=RENDER_PORT,
        url_path=WEBHOOK_PATH.lstrip("/"),
        webhook_url=public_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        secret_token=WEBHOOK_SECRET or None,
        stop_signals=(signal.SIGTERM, signal.SIGINT),
    )


if __name__ == "__main__":
    try:
        if not BOT_TOKEN:
            raise RuntimeError(
                "Thiếu BOT_TOKEN. Hãy thêm BOT_TOKEN vào Environment Variables của Render."
            )
        if not ADMIN_ID:
            raise RuntimeError(
                "Thiếu ADMIN_ID hoặc ADMIN_ID không hợp lệ. "
                "Hãy thêm ADMIN_ID vào Environment Variables của Render."
            )

        if os.getenv("RENDER") and not DATABASE_URL:
            raise RuntimeError(
                "Thiếu DATABASE_URL. Hãy thêm connection string PostgreSQL của Neon "
                "vào Render > Environment Variables."
            )

        init_db()
        backend = "Neon PostgreSQL" if DATABASE_URL else f"SQLite ({DB_FILE})"
        LOGGER.info("Database backend: %s", backend)
        run_bot()

    except KeyboardInterrupt:
        print("Bot đã dừng.")
    except Exception as exc:
        print("BOT START ERROR:", repr(exc))