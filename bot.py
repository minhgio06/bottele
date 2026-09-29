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
    filters,
)

# ============================================================
# CẤU HÌNH
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8633360420:AAFKQg9_SpdAYo1iAqYwTfueD6TOifJZvE8").strip()
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
ADMIN_LINK_VIDEO = 15
ADMIN_THEM_VIDEO = 16
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

def get_link_video():
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM bot_settings WHERE key=?", ("link_video",)).fetchone()
        return ((row["value"] if row else LINK_VIDEO) or LINK_VIDEO).strip()
    except Exception:
        LOGGER.exception("Không đọc được link video từ database")
        return LINK_VIDEO


def set_link_video(value):
    with db() as conn:
        conn.execute(
            "INSERT INTO bot_settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("link_video", value.strip()),
        )


def get_random_video_link():
    """Lấy ngẫu nhiên một link TikTok đang hoạt động."""
    try:
        with db() as conn:
            rows = conn.execute("SELECT url FROM video_links ORDER BY id").fetchall()
        links = [str(r["url"]).strip() for r in rows if r["url"]]
        if links:
            return random.choice(links)
    except Exception:
        LOGGER.exception("Không đọc được danh sách link video")
    return get_link_video()


def add_video_link(value):
    value = value.strip()
    with db() as conn:
        conn.execute("INSERT INTO video_links(url, created_at) VALUES(?, ?)", (value, now_vn().isoformat()))


def get_video_links():
    with db() as conn:
        return conn.execute("SELECT id, url FROM video_links ORDER BY id").fetchall()


def delete_video_link(link_id):
    with db() as conn:
        conn.execute("DELETE FROM video_links WHERE id=?", (link_id,))


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
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO bot_settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
            ("link_video", LINK_VIDEO),
        )

        video_links_id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS video_links (
                id {video_links_id_type},
                url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # Tự động chuyển link cũ sang danh sách nếu danh sách chưa có link.
        existing_links = conn.execute("SELECT COUNT(*) FROM video_links").fetchone()[0]
        if not existing_links:
            conn.execute(
                "INSERT INTO video_links(url, created_at) VALUES(?, ?)",
                (LINK_VIDEO, now_vn().isoformat()),
            )

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

        # Schema migration an toàn cho database cũ.
        if DATABASE_URL:
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "xac_minh_nguoi_that INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE verification_requests ADD COLUMN IF NOT EXISTS "
                "photo_file_id TEXT"
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


def init_user(user_id, ten, ref_by=None):
    u = get_user(user_id)
    if u:
        if u["ten"] != ten:
            u["ten"] = ten
            save_user(u)
        return u

    if ref_by == user_id:
        ref_by = None

    if ref_by is not None and not get_user(ref_by):
        ref_by = None

    u = {
        "id": user_id,
        "ten": ten,
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
            (id, ten, cap_bac, so_du, video_da_xem, video_ngay,
             gioi_thieu, ref_by, ngay_vao, captcha_da_xac_minh,
             ngay_reset, dang_xem, tai_khoan, xac_minh_nguoi_that)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                u["id"], u["ten"], u["cap_bac"], u["so_du"],
                u["video_da_xem"], u["video_ngay"], u["gioi_thieu"],
                u["ref_by"], u["ngay_vao"], 0, u["ngay_reset"],
                0, None, 0,
            ),
        )

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
    init_user(u.id, u.full_name)

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
        u = init_user(uid, update.effective_user.full_name)

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

    init_user(u.id, u.full_name, ref_by)

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

    msg = await update.message.reply_text(
        f"""🔍 XEM TIKTOK — {h(u['cap_bac'])}

📺 Video hôm nay: {u['video_ngay']}/{cfg['gioi_han_xem_ngay']}
💰 Thưởng: {cfg['xu_moi_video']:,}đ/video
⏱ Thời gian xem: 15 giây

👉 Bấm mở video và xem đủ 15 giây.
⌛ Sau 15 giây nút nhận thưởng sẽ xuất hiện.""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎬 MỞ VIDEO TIKTOK", url=get_random_video_link())]]
        ),
    )

    context.user_data["watch_message_id"] = msg.message_id

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

    context.user_data.pop("watch_message_id", None)
    await query.answer("✅ Đã cộng thưởng!", show_alert=False)
    await query.edit_message_text(
        f"""✅ <b>NHẬN THƯỞNG THÀNH CÔNG</b>

🎬 Video hôm nay: {updated['video_ngay']}/{cfg['gioi_han_xem_ngay']}
⏱ Đã xem đủ: 15 giây
💰 Thưởng: +{tien:,}đ
💵 Số dư: {updated['so_du']:,}đ""",
        parse_mode="HTML",
    )


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

    if so_tien < RUT_TOI_THIEU:
        await update.message.reply_text(
            f"❌ Tối thiểu rút {RUT_TOI_THIEU:,}đ.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return NHAP_TAI_KHOAN

    u = get_user(u["id"])
    if so_tien > u["so_du"]:
        await update.message.reply_text(
            "❌ Số tiền vượt quá số dư hiện tại.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return NHAP_TAI_KHOAN

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

    text = (
        "🎛 <b>BẢNG ĐIỀU KHIỂN ADMIN</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Người dùng: <b>{tong_nguoi:,}</b>\n"
        f"💰 Tổng số dư: <b>{tong_so_du:,}đ</b>\n\n"
        "📌 <b>ĐƠN ĐANG CHỜ</b>\n"
        f"💸 Rút tiền: <b>{tong_cho_rut}</b>\n"
        f"📥 Nạp / nâng cấp: <b>{tong_cho_nap}</b>\n"
        f"🛡 Xác minh: <b>{tong_cho_xac_minh}</b>\n\n"
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
        [
            InlineKeyboardButton("🎬 Thêm link video", callback_data="admin_add_video"),
            InlineKeyboardButton("📋 Danh sách video", callback_data="admin_list_video"),
        ],
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
            InlineKeyboardButton("🛡 Xác minh", callback_data=f"admin_edit:verify:{user_id}"),
            InlineKeyboardButton("🔓 Bỏ xác minh", callback_data=f"admin_edit:unverify:{user_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Reset CAPTCHA", callback_data=f"admin_edit:captcha:{user_id}"),
            InlineKeyboardButton("♻️ RESET TÀI KHOẢN", callback_data=f"admin_edit:reset:{user_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Sửa tên", callback_data=f"admin_edit:name:{user_id}"),
            InlineKeyboardButton("🏦 Sửa tài khoản", callback_data=f"admin_edit:account:{user_id}"),
        ],
        [
            InlineKeyboardButton("👥 Sửa giới thiệu", callback_data=f"admin_edit:gioithieu:{user_id}"),
            InlineKeyboardButton("🎬 Sửa video", callback_data=f"admin_edit:video:{user_id}"),
        ],
        [InlineKeyboardButton("⬅️ Danh sách người dùng", callback_data="admin_ds_nguoi")],
    ])


def _admin_user_detail_text(u):
    xac = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that", 0) else "🔒 Chưa xác minh"
    return (
        "👤 <b>QUẢN LÝ NGƯỜI DÙNG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{u['id']}</code>\n"
        f"👤 Tên: <b>{h(u['ten'])}</b>\n"
        f"💰 Số dư: <b>{u['so_du']:,}đ</b>\n"
        f"🏆 Cấp: <b>{h(u['cap_bac'])}</b>\n"
        f"🎬 Video đã xem: <b>{u['video_da_xem']}</b>\n"
        f"👥 Giới thiệu: <b>{u['gioi_thieu']}</b>\n"
        f"🛡 Trạng thái: <b>{xac}</b>\n"
        f"🔐 CAPTCHA: {'✅' if u.get('captcha_da_xac_minh', 0) else '❌'}\n"
        f"🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>"
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


async def xu_ly_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Không có quyền.", show_alert=True)
        return

    data = query.data

    # --------------------------------------------------------
    # SỬA LINK VIDEO DÙNG CHUNG CHO NGƯỜI DÙNG
    # --------------------------------------------------------
    if data == "admin_link_video":
        context.user_data["admin_link_video"] = True
        current = get_link_video()
        await query.answer()
        await query.message.reply_text(
            "🎬 <b>SỬA LINK VIDEO</b>\n\n"
            f"🔗 Link hiện tại: <code>{h(current)}</code>\n\n"
            "👉 Gửi link TikTok mới cho bot.\n"
            "Ví dụ: <code>https://vt.tiktok.com/...</code>",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_LINK_VIDEO

    if data == "admin_add_video":
        context.user_data["admin_add_video"] = True
        await query.answer()
        await query.message.reply_text(
            "➕ <b>THÊM LINK TIKTOK</b>\n\n"
            "👉 Gửi link TikTok mới. Bot sẽ thêm link vào danh sách và chọn ngẫu nhiên khi người dùng bấm <b>🔍 Xem TikTok</b>.\n\n"
            "Ví dụ: <code>https://vt.tiktok.com/...</code>",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_THEM_VIDEO

    if data == "admin_list_video":
        rows = get_video_links()
        if not rows:
            await query.answer("Chưa có link video.", show_alert=True)
            return
        buttons = []
        for row in rows[:50]:
            url = str(row["url"])
            buttons.append([InlineKeyboardButton(
                f"🗑 Xóa video #{row['id']}", callback_data=f"admin_del_video:{row['id']}"
            )])
        text = "📋 <b>DANH SÁCH LINK TIKTOK</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for row in rows[:50]:
            text += f"🎬 #{row['id']}: <code>{h(row['url'])}</code>\n"
        text += "\n🎲 Mỗi lần người dùng bấm Xem TikTok, bot sẽ chọn ngẫu nhiên 1 link."
        buttons.append([InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")])
        await query.answer()
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("admin_del_video:"):
        try:
            link_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("❌ ID không hợp lệ.", show_alert=True)
            return
        rows = get_video_links()
        if len(rows) <= 1:
            await query.answer("⚠️ Phải giữ lại ít nhất 1 link video.", show_alert=True)
            return
        delete_video_link(link_id)
        await query.answer("✅ Đã xóa link video.", show_alert=True)
        rows = get_video_links()
        buttons = [[InlineKeyboardButton(f"🗑 Xóa video #{r['id']}", callback_data=f"admin_del_video:{r['id']}")] for r in rows[:50]]
        text = "📋 <b>DANH SÁCH LINK TIKTOK</b>\n━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"🎬 #{r['id']}: <code>{h(r['url'])}</code>" for r in rows[:50])
        buttons.append([InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")])
        try:
            await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass
        return

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
        if action == "captcha":
            with db() as conn:
                conn.execute("UPDATE users SET captcha_da_xac_minh=0 WHERE id=?", (user_id,))
            await query.answer("🔄 Đã reset CAPTCHA.")
            await _admin_hien_thi_nguoi(query, user_id)
            return

        if action == "reset":
            # Reset dữ liệu hoạt động của người dùng nhưng giữ ID, tên và quan hệ ref_by.
            with db() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET cap_bac='Thành viên',
                        so_du=0,
                        video_da_xem=0,
                        video_ngay=0,
                        gioi_thieu=0,
                        captcha_da_xac_minh=0,
                        dang_xem=0,
                        tai_khoan=NULL,
                        xac_minh_nguoi_that=0,
                        ngay_reset=?
                    WHERE id=?
                    """,
                    (datetime.now().isoformat(), user_id),
                )
            await query.answer("♻️ Đã reset tài khoản.", show_alert=True)
            await _admin_hien_thi_nguoi(query, user_id)
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

        text = f"👥 <b>NGƯỜI DÙNG ({len(rows)})</b>\n━━━━━━━━━━━━━━━━━━━━\nChọn một người để chỉnh sửa:\n"
        buttons = []
        for u in rows[:50]:
            ten = (u["ten"] or "Không tên")[:25]
            buttons.append([InlineKeyboardButton(
                f"👤 {ten} | {u['id']}", callback_data=f"admin_user:{u['id']}"
            )])
        if len(rows) > 50:
            text += f"\n⚠️ Hiển thị 50/{len(rows)} người dùng.\n"
        buttons.append([InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")])
        await query.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return


async def admin_xu_ly_them_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    raw = (update.effective_message.text or "").strip()
    if not (raw.startswith("http://") or raw.startswith("https://")) or len(raw) > 1000:
        await update.effective_message.reply_text("❌ Link không hợp lệ. Vui lòng gửi link bắt đầu bằng http:// hoặc https://.")
        return ADMIN_THEM_VIDEO
    try:
        add_video_link(raw)
    except Exception:
        LOGGER.exception("Không thêm được link video")
        await update.effective_message.reply_text("❌ Không thêm được link video.")
        return ADMIN_THEM_VIDEO
    context.user_data.pop("admin_add_video", None)
    await update.effective_message.reply_text(
        f"✅ <b>Đã thêm link TikTok!</b>\n\n🔗 <code>{h(raw)}</code>\n\n🎲 Từ bây giờ bot sẽ chọn ngẫu nhiên link này khi người dùng bấm <b>🔍 Xem TikTok</b>.",
        parse_mode="HTML", reply_markup=menu_chinh(ADMIN_ID),
    )
    return ConversationHandler.END


async def admin_xu_ly_link_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    raw = (update.effective_message.text or "").strip()
    if not (raw.startswith("http://") or raw.startswith("https://")) or len(raw) > 1000:
        await update.effective_message.reply_text("❌ Link không hợp lệ. Vui lòng gửi link bắt đầu bằng http:// hoặc https://.")
        return ADMIN_LINK_VIDEO
    try:
        set_link_video(raw)
    except Exception:
        LOGGER.exception("Không lưu được link video")
        await update.effective_message.reply_text("❌ Không lưu được link video. Vui lòng thử lại.")
        return ADMIN_LINK_VIDEO
    context.user_data.pop("admin_link_video", None)
    await update.effective_message.reply_text(
        f"✅ <b>Đã đổi link video thành công!</b>\n\n🔗 <code>{h(raw)}</code>\n\nTừ bây giờ người dùng sẽ thấy link mới khi bấm <b>🔍 Xem TikTok</b>.",
        parse_mode="HTML", reply_markup=menu_chinh(ADMIN_ID),
    )
    return ConversationHandler.END


async def admin_xu_ly_sua_nguoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    user_id = context.user_data.get("admin_user_id")
    action = context.user_data.get("admin_user_action")
    if not user_id or not action:
        return ConversationHandler.END

    raw = (update.effective_message.text or "").strip()
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
# MAIN
# ============================================================
def build_application():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
                pattern=r"^(admin_(cong_tien|tru_tien|cong_tat_ca|gui_tb|link_video|add_video|list_video)|admin_del_video:\d+|admin_user:\d+|admin_edit:(cong|tru|setbal|cap|verify|unverify|captcha|reset|name|account|gioithieu|video):\d+)$",
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
            ADMIN_LINK_VIDEO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_link_video,
                ),
            ],
            ADMIN_THEM_VIDEO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_them_video,
                ),
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
                r"^(admin_(home|refresh|ds_(rut|nap|xacminh|nguoi)|duyet_tat_ca))$"
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
    app.add_handler(
        MessageHandler(filters.Regex(r"^🎧 Hỗ Trợ$"), ho_tro)
    )
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