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
import re
import ast
from pathlib import Path
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.error import BadRequest

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
# V20.8: THEO DÕI CALLBACK THỰC TẾ - CHỐNG BÁO LỖI GIẢ
# ============================================================
class V208TrackedCallbackQueryHandler(CallbackQueryHandler):
    """Đánh dấu callback đã được một handler thực thi thành công.

    Không sửa logic nghiệp vụ; chỉ giúp bộ rà soát biết callback nào thật sự
    được handler nhận. Callback bảo vệ tài khoản bị khóa được bỏ qua vì nó có
    thể dừng luồng trước các handler nghiệp vụ.
    """
    async def handle_update(self, update, application, check_result, context):
        result = await super().handle_update(update, application, check_result, context)
        cb = getattr(self.callback, '__name__', '')
        if cb not in {'chan_user_bi_khoa', '_v208_unhandled_callback'}:
            q = getattr(update, 'callback_query', None)
            if q is not None:
                try:
                    context.user_data['_v208_handled_callback_id'] = q.id
                except Exception:
                    pass
        return result

# Dùng lớp theo dõi cho toàn bộ CallbackQueryHandler được khai báo phía dưới.
CallbackQueryHandler = V208TrackedCallbackQueryHandler

# ============================================================
# CẤU HÌNH
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
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
NAP_GUI_ANH = 20
XAC_MINH_GUI_ANH = 21
GIFT_INPUT = 30
ADMIN_EXT_INPUT = 31
ADMIN_V9_BROADCAST_INPUT = 910
ADMIN_SCHEDULE_INPUT = 32

CAP_BAC_GIOI_THIEU_GIAM = True
CAP_BAC_CONFIG = {
    'Thành viên': {"xu_moi_video": 1500, "gioi_han_xem_ngay": 2, "thuong_gioi_thieu": 100, "icon": '🌱'},
    'Tân Binh': {"xu_moi_video": 1800, "gioi_han_xem_ngay": 6, "thuong_gioi_thieu": 450, "icon": '🔰'},
    'Leader Đồng I': {"xu_moi_video": 2200, "gioi_han_xem_ngay": 10, "thuong_gioi_thieu": 800, "icon": '🥉'},
    'Leader Đồng II': {"xu_moi_video": 2600, "gioi_han_xem_ngay": 14, "thuong_gioi_thieu": 1150, "icon": '🥉'},
    'Leader Bạc I': {"xu_moi_video": 3000, "gioi_han_xem_ngay": 18, "thuong_gioi_thieu": 1500, "icon": '🥈'},
    'Leader Bạc II': {"xu_moi_video": 3400, "gioi_han_xem_ngay": 22, "thuong_gioi_thieu": 1850, "icon": '🥈'},
    'Leader Vàng I': {"xu_moi_video": 3800, "gioi_han_xem_ngay": 26, "thuong_gioi_thieu": 2200, "icon": '🥇'},
    'Leader Vàng II': {"xu_moi_video": 4200, "gioi_han_xem_ngay": 30, "thuong_gioi_thieu": 2550, "icon": '🥇'},
    'Leader Bạch Kim I': {"xu_moi_video": 4600, "gioi_han_xem_ngay": 34, "thuong_gioi_thieu": 2900, "icon": '💎'},
    'Leader Bạch Kim II': {"xu_moi_video": 5000, "gioi_han_xem_ngay": 38, "thuong_gioi_thieu": 3250, "icon": '💎'},
    'Leader Ruby I': {"xu_moi_video": 5500, "gioi_han_xem_ngay": 42, "thuong_gioi_thieu": 3600, "icon": '♦️'},
    'Leader Ruby II': {"xu_moi_video": 6000, "gioi_han_xem_ngay": 46, "thuong_gioi_thieu": 3950, "icon": '♦️'},
    'Leader Sapphire I': {"xu_moi_video": 6500, "gioi_han_xem_ngay": 50, "thuong_gioi_thieu": 4300, "icon": '🔷'},
    'Leader Sapphire II': {"xu_moi_video": 7000, "gioi_han_xem_ngay": 54, "thuong_gioi_thieu": 4650, "icon": '🔷'},
    'Leader Kim Cương I': {"xu_moi_video": 7500, "gioi_han_xem_ngay": 58, "thuong_gioi_thieu": 5000, "icon": '💠'},
    'Leader Kim Cương II': {"xu_moi_video": 8000, "gioi_han_xem_ngay": 62, "thuong_gioi_thieu": 5350, "icon": '💠'},
    'Leader Titan I': {"xu_moi_video": 8500, "gioi_han_xem_ngay": 66, "thuong_gioi_thieu": 5700, "icon": '⚡'},
    'Leader Titan II': {"xu_moi_video": 9000, "gioi_han_xem_ngay": 70, "thuong_gioi_thieu": 6050, "icon": '⚡'},
    'Leader Cao Thủ I': {"xu_moi_video": 9500, "gioi_han_xem_ngay": 74, "thuong_gioi_thieu": 6400, "icon": '👑'},
    'Leader Cao Thủ II': {"xu_moi_video": 10000, "gioi_han_xem_ngay": 78, "thuong_gioi_thieu": 6750, "icon": '👑'},
    'Leader Đại Cao Thủ I': {"xu_moi_video": 12500, "gioi_han_xem_ngay": 82, "thuong_gioi_thieu": 7100, "icon": '🔥'},
    'Leader Đại Cao Thủ II': {"xu_moi_video": 13000, "gioi_han_xem_ngay": 86, "thuong_gioi_thieu": 7450, "icon": '🔥'},
    'Leader Đại Cao Thủ III': {"xu_moi_video": 13500, "gioi_han_xem_ngay": 90, "thuong_gioi_thieu": 7800, "icon": '🔥'},
    'Leader Huyền Thoại I': {"xu_moi_video": 14000, "gioi_han_xem_ngay": 94, "thuong_gioi_thieu": 8150, "icon": '🌟'},
    'Leader Huyền Thoại II': {"xu_moi_video": 14500, "gioi_han_xem_ngay": 98, "thuong_gioi_thieu": 8500, "icon": '🌟'},
    'Leader Bất Diệt I': {"xu_moi_video": 15000, "gioi_han_xem_ngay": 102, "thuong_gioi_thieu": 8850, "icon": '☄️'},
    'Leader Bất Diệt II': {"xu_moi_video": 15500, "gioi_han_xem_ngay": 106, "thuong_gioi_thieu": 9200, "icon": '☄️'},
    'Leader Tối Thượng I': {"xu_moi_video": 16000, "gioi_han_xem_ngay": 110, "thuong_gioi_thieu": 9550, "icon": '🌌'},
    'Leader Tối Thượng II': {"xu_moi_video": 16500, "gioi_han_xem_ngay": 114, "thuong_gioi_thieu": 9900, "icon": '🌌'},
    'Leader Thần Thoại I': {"xu_moi_video": 17000, "gioi_han_xem_ngay": 118, "thuong_gioi_thieu": 10250, "icon": '🏆'},
    'Leader Thần Thoại II': {"xu_moi_video": 17500, "gioi_han_xem_ngay": 122, "thuong_gioi_thieu": 10600, "icon": '🏆'},
    'Leader Chí Tôn': {"xu_moi_video": 18000, "gioi_han_xem_ngay": 126, "thuong_gioi_thieu": 10950, "icon": '👑'},
    'Leader Đế Vương': {"xu_moi_video": 18500, "gioi_han_xem_ngay": 130, "thuong_gioi_thieu": 11300, "icon": '👑'},
    'Leader Thiên Đế': {"xu_moi_video": 19000, "gioi_han_xem_ngay": 134, "thuong_gioi_thieu": 11650, "icon": '🌠'},
    'Leader Thần Vương': {"xu_moi_video": 19500, "gioi_han_xem_ngay": 138, "thuong_gioi_thieu": 12000, "icon": '🪐'},
}

MOC_CAP = [
    ('Thành viên', 0, 2),
    ('Tân Binh', 3, 4),
    ('Leader Đồng I', 5, 9),
    ('Leader Đồng II', 10, 14),
    ('Leader Bạc I', 15, 24),
    ('Leader Bạc II', 25, 39),
    ('Leader Vàng I', 40, 59),
    ('Leader Vàng II', 60, 74),
    ('Leader Bạch Kim I', 75, 99),
    ('Leader Bạch Kim II', 100, 149),
    ('Leader Ruby I', 150, 199),
    ('Leader Ruby II', 200, 249),
    ('Leader Sapphire I', 250, 324),
    ('Leader Sapphire II', 325, 399),
    ('Leader Kim Cương I', 400, 499),
    ('Leader Kim Cương II', 500, 599),
    ('Leader Titan I', 600, 749),
    ('Leader Titan II', 750, 999),
    ('Leader Cao Thủ I', 1000, 1249),
    ('Leader Cao Thủ II', 1250, 1499),
    ('Leader Đại Cao Thủ I', 1500, 1749),
    ('Leader Đại Cao Thủ II', 1750, 1999),
    ('Leader Đại Cao Thủ III', 2000, 2499),
    ('Leader Huyền Thoại I', 2500, 3749),
    ('Leader Huyền Thoại II', 3750, 4999),
    ('Leader Bất Diệt I', 5000, 7499),
    ('Leader Bất Diệt II', 7500, 9999),
    ('Leader Tối Thượng I', 10000, 14999),
    ('Leader Tối Thượng II', 15000, 24999),
    ('Leader Thần Thoại I', 25000, 37499),
    ('Leader Thần Thoại II', 37500, 49999),
    ('Leader Chí Tôn', 50000, 99999),
    ('Leader Đế Vương', 100000, 249999),
    ('Leader Thiên Đế', 250000, 499999),
    ('Leader Thần Vương', 500000, 499999999),
]

# ===== CẤP BẬC SIÊU CAO BỔ SUNG =====
CAP_BAC_CONFIG.update({
    'Leader Thiên Tôn': {"xu_moi_video": 20000, "gioi_han_xem_ngay": 142, "thuong_gioi_thieu": 12350, "icon": '☯️'},
    'Leader Hỗn Nguyên': {"xu_moi_video": 21000, "gioi_han_xem_ngay": 146, "thuong_gioi_thieu": 12700, "icon": '🌀'},
    'Leader Chí Thánh': {"xu_moi_video": 22000, "gioi_han_xem_ngay": 150, "thuong_gioi_thieu": 13050, "icon": '✨'},
    'Leader Thánh Vương': {"xu_moi_video": 23000, "gioi_han_xem_ngay": 154, "thuong_gioi_thieu": 13400, "icon": '🔱'},
    'Leader Đạo Tổ': {"xu_moi_video": 24000, "gioi_han_xem_ngay": 158, "thuong_gioi_thieu": 13750, "icon": '☯️'},
    'Leader Đế Tôn': {"xu_moi_video": 25000, "gioi_han_xem_ngay": 162, "thuong_gioi_thieu": 14100, "icon": '👑'},
    'Leader Thần Đế': {"xu_moi_video": 26000, "gioi_han_xem_ngay": 166, "thuong_gioi_thieu": 14450, "icon": '🌌'},
    'Leader Vạn Cổ': {"xu_moi_video": 27000, "gioi_han_xem_ngay": 170, "thuong_gioi_thieu": 14800, "icon": '♾️'},
    'Leader Bất Hủ': {"xu_moi_video": 28000, "gioi_han_xem_ngay": 174, "thuong_gioi_thieu": 15150, "icon": '💫'},
    'Leader Siêu Việt': {"xu_moi_video": 30000, "gioi_han_xem_ngay": 180, "thuong_gioi_thieu": 15800, "icon": '🚀'},
    'Leader Vô Cực': {"xu_moi_video": 32000, "gioi_han_xem_ngay": 186, "thuong_gioi_thieu": 16500, "icon": '♾️'},
    'Leader Tối Cường': {"xu_moi_video": 35000, "gioi_han_xem_ngay": 192, "thuong_gioi_thieu": 17500, "icon": '⚜️'},
    'Leader Thần Thoại Tối Cao': {"xu_moi_video": 40000, "gioi_han_xem_ngay": 200, "thuong_gioi_thieu": 19000, "icon": '🌠'},
    'Leader Đấng Tối Cao': {"xu_moi_video": 50000, "gioi_han_xem_ngay": 220, "thuong_gioi_thieu": 22000, "icon": '👼'},
    'Leader Chúa Tể': {"xu_moi_video": 75000, "gioi_han_xem_ngay": 250, "thuong_gioi_thieu": 30000, "icon": '👑'},
})
MOC_CAP.extend([
    ('Leader Thiên Tôn', 500000000, 999999999),
    ('Leader Hỗn Nguyên', 1000000000, 2499999999),
    ('Leader Chí Thánh', 2500000000, 4999999999),
    ('Leader Thánh Vương', 5000000000, 9999999999),
    ('Leader Đạo Tổ', 10000000000, 24999999999),
    ('Leader Đế Tôn', 25000000000, 49999999999),
    ('Leader Thần Đế', 50000000000, 99999999999),
    ('Leader Vạn Cổ', 100000000000, 249999999999),
    ('Leader Bất Hủ', 250000000000, 499999999999),
    ('Leader Siêu Việt', 500000000000, 999999999999),
    ('Leader Vô Cực', 1000000000000, 2499999999999),
    ('Leader Tối Cường', 2500000000000, 4999999999999),
    ('Leader Thần Thoại Tối Cao', 5000000000000, 24999999999999),
    ('Leader Đấng Tối Cao', 25000000000000, 49999999999999),
    ('Leader Chúa Tể', 50000000000000, 499999999999999999),
])


# ===== CẤP BẬC ELITE V5: mở rộng hệ thống lên 70 cấp =====
_ELITE_RANKS_V5 = [
    ('Leader Chí Tôn Vương', 500000000000000000, 749999999999999999),
    ('Leader Thần Tôn', 750000000000000000, 999999999999999999),
    ('Leader Thiên Tôn Vương', 1000000000000000000, 1249999999999999999),
    ('Leader Hồng Mông', 1250000000000000000, 1499999999999999999),
    ('Leader Hỗn Độn', 1500000000000000000, 1749999999999999999),
    ('Leader Vĩnh Hằng', 1750000000000000000, 1999999999999999999),
    ('Leader Thái Sơ', 2000000000000000000, 2249999999999999999),
    ('Leader Thái Cổ', 2250000000000000000, 2499999999999999999),
    ('Leader Cổ Đế', 2500000000000000000, 2749999999999999999),
    ('Leader Thiên Mệnh', 2750000000000000000, 2999999999999999999),
    ('Leader Chí Cao', 3000000000000000000, 3249999999999999999),
    ('Leader Vạn Đạo', 3250000000000000000, 3499999999999999999),
    ('Leader Vô Thượng', 3500000000000000000, 3749999999999999999),
    ('Leader Siêu Thần', 3750000000000000000, 3999999999999999999),
    ('Leader Tối Cao Thần', 4000000000000000000, 8999999999999999999),
]
_ELITE_ICONS_V5 = ['👑','🌌','🌠','🪐','☯️','♾️','✨','🔥','⚜️','💫','🔱','🏆','♾️','🚀','🌟']
for _i, (_name, _lo, _hi) in enumerate(_ELITE_RANKS_V5):
    if _name not in CAP_BAC_CONFIG:
        _prev = CAP_BAC_CONFIG['Leader Chúa Tể']
        CAP_BAC_CONFIG[_name] = {
            'xu_moi_video': min(120000, 80000 + _i * 3000),
            'gioi_han_xem_ngay': min(500, 270 + _i * 12),
            'thuong_gioi_thieu': min(100000, 33000 + _i * 3500),
            'icon': _ELITE_ICONS_V5[_i],
        }
        MOC_CAP.append((_name, _lo, _hi))

# V17: CẤP GIỚI THIỆU CHỈ 20 CẤP
# Giữ lại đúng 20 mốc đầu của hệ thống giới thiệu; cấp nạp vẫn dùng CAP_NAP_AMOUNT riêng.
MOC_CAP = MOC_CAP[:20]

GOI_NANG_CAP = {
    "goi_bac": {
        "ten": "Gói Bạc", "gia": 125000, "cap_moi": "Leader Bạc I",
        "gioi_han_xem": 5, "tien_moi_video": 2500,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP BAC",
    },
    "goi_vang": {
        "ten": "Gói Vàng", "gia": 250000, "cap_moi": "Leader Vàng I",
        "gioi_han_xem": 10, "tien_moi_video": 3000,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP VANG",
    },
    "goi_bachkim": {
        "ten": "Gói Bạch Kim", "gia": 1000000, "cap_moi": "Leader Bạch Kim I",
        "gioi_han_xem": 20, "tien_moi_video": 3500,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP BACHKIM",
    },
    "goi_kimcuong": {
        "ten": "Gói Kim Cương", "gia": 2000000, "cap_moi": "Leader Kim Cương I",
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
                so_du_nap BIGINT NOT NULL DEFAULT 0,
                video_da_xem INTEGER NOT NULL DEFAULT 0,
                video_ngay INTEGER NOT NULL DEFAULT 0,
                gioi_thieu BIGINT NOT NULL DEFAULT 0,
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

        video_id_type = "BIGSERIAL" if DATABASE_URL else "INTEGER"
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS video_links (
                id {video_id_type} PRIMARY KEY,
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
            CREATE TABLE IF NOT EXISTS daily_checkins (
                user_id BIGINT PRIMARY KEY,
                last_date TEXT NOT NULL,
                streak INTEGER NOT NULL DEFAULT 0,
                total_days INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Schema migration an toàn cho database cũ.
        if DATABASE_URL:
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "xac_minh_nguoi_that INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "so_du_nap BIGINT NOT NULL DEFAULT 0"
            )
            # Referral counters support the high-rank thresholds without INT overflow.
            try:
                conn.execute("ALTER TABLE users ALTER COLUMN gioi_thieu TYPE BIGINT")
            except Exception:
                conn.rollback()
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
                    "ALTER TABLE users ADD COLUMN so_du_nap "
                    "BIGINT NOT NULL DEFAULT 0"
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

        # Chuẩn hóa hai loại số dư: so_du = tiền kiếm được/được rút; so_du_nap = tiền nạp/dịch vụ.
        try:
            conn.execute("UPDATE users SET so_du=COALESCE(so_du,0), so_du_nap=COALESCE(so_du_nap,0)")
        except Exception:
            pass

        # PostgreSQL: các database cũ có thể đã tạo video_links.id là INTEGER
        # không có DEFAULT. Khi đó INSERT không truyền id sẽ lỗi NOT NULL.
        # Gắn sequence an toàn để cả database cũ lẫn database mới đều tự cấp id.
        if DATABASE_URL:
            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS video_links_id_seq")
                conn.execute("ALTER SEQUENCE video_links_id_seq OWNED BY video_links.id")
                conn.execute("ALTER TABLE video_links ALTER COLUMN id SET DEFAULT nextval('video_links_id_seq')")
                conn.execute("SELECT setval('video_links_id_seq', COALESCE((SELECT MAX(id) FROM video_links), 0) + 1, false)")
            except Exception:
                conn.rollback()
                LOGGER.exception("Không thể chuẩn hóa sequence video_links.id")

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
                so_du_nap=?,
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
                u.get("so_du_nap", 0),
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
        "so_du": int(get_setting("new_user_bonus", 0)),
        "so_du_nap": 0,
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
            (id, ten, username, cap_bac, so_du, so_du_nap, video_da_xem, video_ngay,
             gioi_thieu, ref_by, ngay_vao, captcha_da_xac_minh,
             ngay_reset, dang_xem, tai_khoan, xac_minh_nguoi_that)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                u["id"], u["ten"], u["username"], u["cap_bac"], u["so_du"], u.get("so_du_nap", 0),
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


def update_earned_balance(user_id, delta):
    """Cộng/trừ SỐ DƯ KIẾM ĐƯỢC (được phép rút)."""
    with db() as conn:
        conn.execute("UPDATE users SET so_du = so_du + ? WHERE id=?", (int(delta), user_id))


def update_deposit_balance(user_id, delta):
    """Cộng/trừ SỐ DƯ NẠP (chỉ dùng cho dịch vụ mạng xã hội)."""
    with db() as conn:
        conn.execute("UPDATE users SET so_du_nap = COALESCE(so_du_nap,0) + ? WHERE id=?", (int(delta), user_id))


def update_balance(user_id, delta):
    # Tương thích code cũ: balance mặc định là số dư kiếm được.
    update_earned_balance(user_id, delta)


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

# Runtime configuration: Admin có thể thay đổi mà không cần sửa code/Render.
def runtime_setting(key, fallback=""):
    try:
        return get_setting(key, fallback)
    except Exception:
        return fallback


def runtime_text(key, fallback):
    value = str(runtime_setting(key, fallback) or fallback).strip()
    return value or str(fallback)


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
    if not update.effective_user or is_admin(update.effective_user.id):
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
        [KeyboardButton("🛒 Dịch Vụ TikTok"), KeyboardButton("🎯 Nhiệm Vụ")],
        [KeyboardButton("🎁 Điểm Danh"), KeyboardButton("🏆 BXH")],
        [KeyboardButton("🎡 Vòng Quay"), KeyboardButton("🎁 Đổi Quà")],
        [KeyboardButton("🎉 Sự Kiện"), KeyboardButton("🎧 Hỗ Trợ")],
        [KeyboardButton("🔐 Nhập CaptCha")],
        [KeyboardButton("💳 Nạp Tiền"), KeyboardButton("💰 Rút Tiền")],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton("🎛 QUẢN LÝ ADMIN")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def kt_kenh(user_id, context):
    """Kiểm tra người dùng đã tham gia đủ 2 kênh bắt buộc."""
    channels = [runtime_text("required_channel_1", KENH_YEU_CAU_1), runtime_text("required_channel_2", KENH_YEU_CAU_2)]
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
        [InlineKeyboardButton("📢 THAM GIA @rutxutiktok", url=runtime_text("required_channel_link_1", _channel_url(KENH_YEU_CAU_1, "https://t.me/rutxutiktok")))],
        [InlineKeyboardButton("📢 THAM GIA @thongbaoxutiktok", url=runtime_text("required_channel_link_2", _channel_url(KENH_YEU_CAU_2, "https://t.me/thongbaoxutiktok")))],
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
        allowed = {str(runtime_text("required_channel_1", KENH_YEU_CAU_1)), str(runtime_text("required_channel_2", KENH_YEU_CAU_2))}
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

    if int(get_setting("maintenance_mode", 0)) and not is_admin(u.id):
        await update.message.reply_text(h(runtime_text("maintenance_message", "🚧 BOT ĐANG BẢO TRÌ\n\nVui lòng quay lại sau.")), parse_mode="HTML")
        return

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

    if int(get_setting("captcha_required", 1)) and not u["captcha_da_xac_minh"]:
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

    video_link = runtime_text("video_default_link", LINK_VIDEO)
    video_id = None
    try:
        with db() as conn:
            recent_prefix = now_vn().strftime("%d/%m/%Y")
            video_rows = conn.execute(
                """SELECT v.id, v.url FROM video_links v
                   WHERE v.active=1 AND NOT EXISTS (
                       SELECT 1 FROM video_watch_logs l
                       WHERE l.user_id=? AND l.video_id=v.id
                         AND l.watched_at LIKE ?
                   )
                   ORDER BY RANDOM() LIMIT 1""",
                (u["id"], recent_prefix + "%"),
            ).fetchall()
            if not video_rows:
                video_rows = conn.execute(
                    "SELECT id,url FROM video_links WHERE active=1 ORDER BY RANDOM() LIMIT 1"
                ).fetchall()
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

        tien = int(cfg["xu_moi_video"] * float(get_setting('video_reward_multiplier', 1)))
        # Sự kiện có thể tăng thưởng theo hệ số.
        try:
            with db() as evconn:
                ev = evconn.execute("SELECT multiplier,ends_at FROM event_settings WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
            if ev and ev["multiplier"]:
                if not ev["ends_at"] or now_vn() <= datetime.strptime(ev["ends_at"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=VN_TZ):
                    tien = int(tien * float(ev["multiplier"]))
        except Exception:
            pass

        # Atomic claim: 2 lần bấm cùng lúc chỉ một lần được cộng tiền.
        changed = conn.execute(
            """
            UPDATE users
            SET video_da_xem=video_da_xem+1,
                video_ngay=video_ngay+1,
                so_du=so_du+?,
                total_earned=COALESCE(total_earned,0)+?,
                dang_xem=0
            WHERE id=? AND dang_xem=1 AND video_ngay < ?
            """,
            (tien, tien, uid, cfg["gioi_han_xem_ngay"]),
        ).rowcount

        if changed != 1:
            conn.rollback()
            await query.answer("❌ Phần thưởng đã được xử lý.", show_alert=True)
            return

        updated = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        _wallet_ledger(conn, uid, 'earned', tien, int(updated['so_du'] or 0), 'video_reward', f'VIDEO:{message_id}', 'Thưởng hoàn thành video TikTok')

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
                parent_now = conn.execute("SELECT so_du FROM users WHERE id=?", (parent['id'],)).fetchone()
                _wallet_ledger(conn, parent['id'], 'earned', commission, int(parent_now['so_du'] or 0), 'referral_commission', f'VIDEO:{message_id}', 'Hoa hồng giới thiệu')
            ancestor_id = parent["ref_by"]

        video_id = context.user_data.get("watch_video_id")
        if video_id:
            try:
                conn.execute("UPDATE video_links SET views=COALESCE(views,0)+1, claimed=COALESCE(claimed,0)+1, reward_total=COALESCE(reward_total,0)+? WHERE id=?", (tien, video_id))
                conn.execute("INSERT INTO video_watch_logs(user_id,video_id,watched_at,claimed,reward) VALUES (?,?,?,?,?)", (uid, video_id, now_vn().strftime("%d/%m/%Y %H:%M:%S"), 1, tien))
            except Exception:
                pass
        conn.commit()
        log_user_activity(uid, 'video_reward', f'+{tien}đ video_id={video_id}')

    context.user_data.pop("watch_message_id", None)
    context.user_data.pop("watch_video_id", None)
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
        return
    today = today_vn()
    yesterday = (now_vn() - timedelta(days=1)).strftime("%d/%m/%Y")
    base = int(get_setting("thuong_diem_danh", 5000))

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM daily_checkins WHERE user_id=?", (u["id"],)
        ).fetchone()
        if row and row["last_date"] == today:
            streak_existing = int(row["streak"])
            already = True
            new_balance = None
            streak = streak_existing
            bonus = 0
        else:
            already = False
            streak = int(row["streak"]) + 1 if row and row["last_date"] == yesterday else 1
            bonus = base + min(streak, 7) * 1000 + (
                int(get_setting("thuong_tuan", 15000)) if streak % 7 == 0 else 0
            )
            if row:
                conn.execute(
                    "UPDATE daily_checkins SET last_date=?, streak=?, total_days=total_days+1 WHERE user_id=?",
                    (today, streak, u["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO daily_checkins (user_id,last_date,streak,total_days) VALUES (?,?,?,1)",
                    (u["id"], today, streak),
                )
            conn.execute(
                "UPDATE users SET so_du=so_du+?, total_earned=COALESCE(total_earned,0)+? WHERE id=?",
                (bonus, bonus, u["id"]),
            )
            new_balance = conn.execute(
                "SELECT so_du FROM users WHERE id=?", (u["id"],)
            ).fetchone()[0]

    if already:
        await update.message.reply_text(
            f"✅ Hôm nay bạn đã điểm danh rồi.\n🔥 Chuỗi: <b>{streak}</b> ngày",
            parse_mode="HTML",
            reply_markup=menu_chinh(u["id"]),
        )
        return
    await update.message.reply_text(
        f"🎁 <b>ĐIỂM DANH THÀNH CÔNG</b>\n\n"
        f"🔥 Chuỗi: <b>{streak} ngày</b>\n"
        f"💰 Thưởng: <b>+{bonus:,}đ</b>\n"
        f"💵 Số dư: <b>{new_balance:,}đ</b>",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )

async def bang_xep_hang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u: return
    with db() as conn:
        rows = conn.execute("SELECT id, ten, gioi_thieu, cap_bac FROM users ORDER BY gioi_thieu DESC, so_du DESC LIMIT 10").fetchall()
    text = "🏆 <b>BẢNG XẾP HẠNG GIỚI THIỆU</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(rows, 1):
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
        text += f"{icon} <b>#{i}</b> {h(r['ten'])} — {r['gioi_thieu']} người\n   🏆 {h(r['cap_bac'])}\n"
    text += "\n📌 Xếp hạng dựa trên số người giới thiệu."
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=menu_chinh(u["id"]))


def _hien_thi_moc_cap():
    lines=[]
    for ten,min_n,max_n in MOC_CAP:
        moc=f"{min_n:,}+" if max_n>=999999999 else f"{min_n:,}–{max_n:,}"
        lines.append(f"{CAP_BAC_CONFIG[ten].get('icon','⭐')} <b>{ten}</b> — {moc} người")
    return "\n".join(lines)


async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khu vực riêng cho cấp giới thiệu và link giới thiệu."""
    u = get_user(update.effective_user.id)
    if not u:
        return

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={u['id']}"

    thuong = CAP_BAC_CONFIG[u["cap_bac"]]["thuong_gioi_thieu"]
    moc_cap_text = _hien_thi_moc_cap()
    await update.message.reply_text(
        f"""👥 <b>CẤP GIỚI THIỆU</b>

👥 Người đã giới thiệu: <b>{u['gioi_thieu']}</b>
💰 Thưởng giới thiệu hiện tại: <b>{thuong:,}đ/người</b>

📈 <b>HỆ THỐNG {len(MOC_CAP)} CẤP BẬC</b>
━━━━━━━━━━━━━━━━━━━━
{moc_cap_text}
━━━━━━━━━━━━━━━━━━━━
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

    qr = _vietqr_url(g["gia"], ma_nap) if "_vietqr_url" in globals() else None
    copy_kb = _deposit_copy_keyboard(ma_nap, g["so_tk"], ma_nap) if "_deposit_copy_keyboard" in globals() else InlineKeyboardMarkup([[InlineKeyboardButton("📩 Tôi đã chuyển khoản", callback_data=f"dachuyen:{ma_nap}")]])
    text = f"""🏅 <b>{h(g['ten'])}</b>

💰 Nạp: {g['gia']:,}đ
📺 Xem: {g['gioi_han_xem']} video TikTok/ngày
💵 {g['tien_moi_video']:,}đ / video

🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>
Ngân hàng: <b>{h(g['ngan_hang'])}</b>
Chủ TK: <b>{h(g['chu_tk'])}</b>
Số TK: <code>{h(g['so_tk'])}</code>

💵 Số tiền: <b>{g['gia']:,}đ</b>
📝 Nội dung CK: <code>{h(ma_nap)}</code>

📋 <b>Nhấn giữ hoặc dùng nút để sao chép STK/nội dung.</b>
📷 Quét mã QR để chuyển khoản nhanh.

⚠️ Vui lòng chuyển đúng số tiền và đúng nội dung!"""
    if qr:
        await context.bot.send_photo(chat_id=query.from_user.id, photo=qr, caption=text, parse_mode="HTML", reply_markup=copy_kb)
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=copy_kb)
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
    support = runtime_text("support_username", "@hotroxutiktok")
    announce = runtime_text("announcement_channel", "@rutxutiktok")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 LIÊN HỆ HỖ TRỢ", url=_channel_url(support, "https://t.me/hotroxutiktok"))],
        [InlineKeyboardButton("📢 KÊNH THÔNG BÁO", url=_channel_url(announce, "https://t.me/rutxutiktok"))],
    ])
    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\n"
        "Bấm nút bên dưới để liên hệ hỗ trợ hoặc xem kênh thông báo.\n\n"
        f"⏰ {h(runtime_text('support_hours', '8:00 - 22:00 hàng ngày'))}",
        parse_mode="HTML", reply_markup=keyboard,
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
        f"👤 <b>Chủ TK:</b> {h(runtime_text("verify_account_name", XAC_MINH_CHU_TK))}\n"
        f"🔢 <b>Số TK:</b> <code>{h(runtime_text("verify_account_number", XAC_MINH_SO_TK))}</code>\n"
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
            chat_id=runtime_text("announcement_channel", KENH_THONG_BAO),
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
        await context.bot.send_message(chat_id=runtime_text("withdraw_announcement_channel", KENH_THONG_BAO_RUT), text=text, parse_mode="HTML")
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
💰 Số dư kiếm được (được rút): {u['so_du']:,}đ
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
            "SELECT thoi_gian FROM withdrawals WHERE user_id=? ORDER BY thoi_gian DESC, request_id DESC LIMIT 1",
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
    risk_score, account_hash, risk_flags = _withdraw_risk(u["tai_khoan"], u["id"], so_tien)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO withdrawals
            (request_id, user_id, ten, so_tien, tai_khoan, thoi_gian, status, risk_score, account_hash, risk_flags)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                request_id, u["id"], u["ten"], so_tien, u["tai_khoan"],
                now_vn().strftime("%d/%m/%Y %H:%M"), risk_score, account_hash, risk_flags,
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
📅 Thời gian: {now_vn().strftime('%d/%m/%Y %H:%M')}
🚨 Risk: <b>{risk_score}</b> — {h(risk_flags)}""",
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
        tong_so_du_nap = conn.execute("SELECT COALESCE(SUM(so_du_nap),0) FROM users").fetchone()[0]
        nguoi_bi_khoa = conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0]
        ngay_prefix = now_vn().strftime("%d/%m/%Y") + "%"
        nguoi_moi_hom_nay = conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao LIKE ?", (ngay_prefix,)).fetchone()[0]
        rut_hom_nay = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved' AND thoi_gian LIKE ?", (ngay_prefix,)).fetchone()[0]
        tien_rut_hom_nay = conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved' AND thoi_gian LIKE ?", (ngay_prefix,)).fetchone()[0]

    text = (
        "🎛 <b>ADMIN CONTROL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 User: <b>{tong_nguoi:,}</b>  •  🔒 Khóa: <b>{nguoi_bi_khoa:,}</b>\n"
        f"💰 Tổng số dư kiếm được: <b>{tong_so_du:,}đ</b>\n💳 Tổng số dư nạp: <b>{tong_so_du_nap:,}đ</b>\n\n"
        f"⏳ Chờ xử lý: 💸 <b>{tong_cho_rut}</b>  •  📥 <b>{tong_cho_nap}</b>  •  🛡 <b>{tong_cho_xac_minh}</b>\n"
        f"📈 Hôm nay: 💸 <b>{rut_hom_nay}</b> đơn  •  <b>{tien_rut_hom_nay:,}đ</b>  •  🆕 <b>{nguoi_moi_hom_nay}</b> user\n\n"
        "⚡ <b>Chọn chức năng quản lý</b>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Rút", callback_data="admin_ds_rut"),
            InlineKeyboardButton("📥 Nạp", callback_data="admin_ds_nap"),
            InlineKeyboardButton("🛡 Xác minh", callback_data="admin_ds_xacminh"),
        ],
        [
            InlineKeyboardButton("👥 Người dùng", callback_data="admin_ds_nguoi"),
            InlineKeyboardButton("🎬 Video", callback_data="admin_video"),
            InlineKeyboardButton("📢 Thông báo", callback_data="admin_gui_tb"),
        ],
        [
            InlineKeyboardButton("💰 + Tiền", callback_data="admin_cong_tien"),
            InlineKeyboardButton("💸 − Tiền", callback_data="admin_tru_tien"),
            InlineKeyboardButton("💰 + Tất cả", callback_data="admin_cong_tat_ca"),
        ],
        [
            InlineKeyboardButton("📜 Giao dịch", callback_data="admin_lich_su"),
            InlineKeyboardButton("🛡 Nhật ký", callback_data="admin_log"),
            InlineKeyboardButton("⚙️ Cài đặt", callback_data="admin_settings"),
        ],
        [InlineKeyboardButton("🚀 ADMIN SMART CENTER", callback_data="admin_v9:dashboard")],
        [InlineKeyboardButton("✅ DUYỆT TẤT CẢ ĐƠN", callback_data="admin_duyet_tat_ca")],
        [InlineKeyboardButton("🔄 Làm mới", callback_data="admin_refresh")],
    ])
    return text, keyboard


async def trang_quan_ly_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    # Giao diện compact: các thao tác thường dùng nằm 2-3 nút/hàng,
    # thao tác nguy hiểm được tách riêng để tránh bấm nhầm.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 + Tiền", callback_data=f"admin_edit:cong:{user_id}"),
            InlineKeyboardButton("💸 − Tiền", callback_data=f"admin_edit:tru:{user_id}"),
            InlineKeyboardButton("💵 Đặt dư", callback_data=f"admin_edit:setbal:{user_id}"),
        ],
        [
            InlineKeyboardButton("🏆 Cấp", callback_data=f"admin_edit:cap:{user_id}"),
            InlineKeyboardButton("✏️ Tên", callback_data=f"admin_edit:name:{user_id}"),
            InlineKeyboardButton("🏦 Tài khoản", callback_data=f"admin_edit:account:{user_id}"),
        ],
        [
            InlineKeyboardButton("👥 Giới thiệu", callback_data=f"admin_edit:gioithieu:{user_id}"),
            InlineKeyboardButton("🎬 Video", callback_data=f"admin_edit:video:{user_id}"),
            InlineKeyboardButton("📅 Video ngày", callback_data=f"admin_edit:video_ngay:{user_id}"),
        ],
        [
            InlineKeyboardButton("💰 Đã kiếm", callback_data=f"admin_edit:earned:{user_id}"),
            InlineKeyboardButton("💸 Đã rút", callback_data=f"admin_edit:withdrawn:{user_id}"),
            InlineKeyboardButton("📜 Lịch sử", callback_data=f"admin_history:{user_id}"),
        ],
        [
            InlineKeyboardButton("🛡 Xác minh", callback_data=f"admin_edit:verify:{user_id}"),
            InlineKeyboardButton("🔓 Bỏ XM", callback_data=f"admin_edit:unverify:{user_id}"),
            InlineKeyboardButton("🔄 CAPTCHA", callback_data=f"admin_edit:captcha:{user_id}"),
        ],
        [
            InlineKeyboardButton("🔒 Khóa", callback_data=f"admin_edit:lock:{user_id}"),
            InlineKeyboardButton("🔓 Mở khóa", callback_data=f"admin_edit:unlock:{user_id}"),
        ],
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

    if not is_admin(update.effective_user.id):
        await query.answer("❌ Không có quyền.", show_alert=True)
        return

    data = query.data


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
        if action in {"name", "account", "gioithieu", "video", "video_ngay", "earned", "withdrawn"}:
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

        if action == "resetday":
            with db() as conn:
                conn.execute("UPDATE users SET video_ngay=0, ngay_reset=?, dang_xem=0 WHERE id=?", (today_vn(), user_id))
            admin_log("Reset lượt video trong ngày", user_id)
            await query.answer("🔄 Đã reset lượt ngày.", show_alert=True)
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
            "cong": "💰 Nhập số tiền muốn CỘNG vào SỐ DƯ KIẾM ĐƯỢC (ví dụ: 50000):",
            "tru": "💸 Nhập số tiền muốn TRỪ khỏi SỐ DƯ KIẾM ĐƯỢC (ví dụ: 50000):",
            "setbal": "💵 Nhập SỐ DƯ KIẾM ĐƯỢC mới (ví dụ: 100000):",
            "congnap": "💳 Nhập số tiền muốn CỘNG vào SỐ DƯ NẠP:",
            "trunap": "💳 Nhập số tiền muốn TRỪ khỏi SỐ DƯ NẠP:",
            "setbalnap": "💳 Nhập SỐ DƯ NẠP mới:",
            "cap": "💳 Nhập cấp nạp mới:\n" + "\n".join(f"• {x}" for x in CAP_BAC_CONFIG),
            "capgt": "👥 Nhập cấp giới thiệu mới:\n" + "\n".join(f"• {x}" for x in CAP_BAC_CONFIG),
            "capnap": "💳 Nhập cấp nạp mới:\n" + "\n".join(f"• {x}" for x in CAP_BAC_CONFIG),
            "name": "✏️ Nhập tên mới của người dùng:",
            "account": "🏦 Nhập tài khoản rút tiền mới (hoặc nhập - để xóa):",
            "gioithieu": "👥 Nhập số người đã giới thiệu mới (số nguyên >= 0):",
            "video": "🎬 Nhập tổng số video đã xem mới (số nguyên >= 0):",
            "video_ngay": "📅 Nhập số video đã xem HÔM NAY mới (số nguyên >= 0):",
            "earned": "📈 Nhập tổng tiền đã kiếm mới (số nguyên >= 0):",
            "withdrawn": "💸 Nhập tổng tiền đã rút mới (số nguyên >= 0):",
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
                """UPDATE users SET cap_bac=?, so_du=0, so_du_nap=0, video_da_xem=0, video_ngay=0,
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
                if str(yc.get("deposit_type", "rank")) == "balance":
                    conn.execute("UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)+?, total_deposited=COALESCE(total_deposited,0)+? WHERE id=?", (yc["gia"], yc["gia"], yc["user_id"]))
                    user_now = conn.execute("SELECT total_deposited,so_du_nap FROM users WHERE id=?", (yc["user_id"],)).fetchone()
                    _wallet_ledger(conn, yc['user_id'], 'service', int(yc['gia']), int(user_now['so_du_nap'] or 0), 'deposit_approved', ma_nap, 'Nạp tiền được Admin duyệt')
                    new_rank = _v13_rank_by_deposit(user_now[0] if user_now else yc["gia"])
                    conn.execute("UPDATE users SET cap_nap=?, cap_bac=?, total_deposited=COALESCE(total_deposited,0) WHERE id=?", (new_rank,new_rank,yc["user_id"]))
                else:
                    conn.execute("UPDATE users SET cap_nap=?, cap_bac=? WHERE id=?", (yc["cap_moi"], yc["cap_moi"], yc["user_id"]))

                if str(yc.get("deposit_type", "rank")) == "balance":
                    user_now = conn.execute("SELECT so_du,so_du_nap,cap_nap FROM users WHERE id=?", (yc["user_id"],)).fetchone()
                    await context.bot.send_message(chat_id=yc["user_id"], text=(f"✅ <b>NẠP TIỀN THÀNH CÔNG!</b>\n\n💵 +{yc['gia']:,}đ\n💳 Số dư dịch vụ: <b>{user_now['so_du_nap']:,}đ</b>\n💰 Số dư kiếm được: <b>{user_now['so_du']:,}đ</b>\n💳 Cấp nạp: <b>{h(user_now['cap_nap'] or 'Thành viên')}</b>" if user_now else "✅ Nạp tiền thành công."), parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=yc["user_id"], text=f"""✅ <b>NÂNG CẤP THÀNH CÔNG!</b>\n\n🏆 Cấp nạp: {h(yc['cap_moi'])}\n📺 Giới hạn: {CAP_BAC_CONFIG[yc['cap_moi']]['gioi_han_xem_ngay']} video/ngày\n💵 Thưởng/video: {CAP_BAC_CONFIG[yc['cap_moi']]['xu_moi_video']:,}đ""", parse_mode="HTML")
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

                if str(yc.get("deposit_type", "rank")) == "balance":
                    conn.execute("UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)+?, total_deposited=COALESCE(total_deposited,0)+? WHERE id=?", (yc["gia"],yc["gia"],yc["user_id"]))
                    total_row=conn.execute("SELECT total_deposited FROM users WHERE id=?",(yc["user_id"],)).fetchone()
                    new_rank=_v13_rank_by_deposit(total_row[0] if total_row else yc["gia"])
                    conn.execute("UPDATE users SET cap_nap=?, cap_bac=? WHERE id=?",(new_rank,new_rank,yc["user_id"]))
                else:
                    conn.execute("UPDATE users SET cap_nap=?, cap_bac=? WHERE id=?",(yc["cap_moi"],yc["cap_moi"],yc["user_id"]))
                conn.execute("UPDATE deposits SET approved_by=?, approved_at=? WHERE request_id=?",(ADMIN_ID,now_vn().strftime('%d/%m/%Y %H:%M:%S'),yc["request_id"]))
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
                if str(yc.get("deposit_type", "rank")) == "balance":
                    user_now=get_user(yc["user_id"])
                    txt=(f"✅ <b>NẠP TIỀN THÀNH CÔNG!</b>\n\n💵 +{yc['gia']:,}đ\n💳 Số dư dịch vụ: <b>{user_now['so_du_nap']:,}đ</b>\n💰 Số dư kiếm được: <b>{user_now['so_du']:,}đ</b>\n🔔 Mã: <code>{h(yc['request_id'])}</code>" if user_now else "✅ Nạp tiền thành công.")
                else:
                    txt=("✅ <b>NÂNG CẤP THÀNH CÔNG!</b>\n\n"
                         f"🏆 Cấp nạp: {h(yc['cap_moi'])}\n"
                         f"📺 Giới hạn: {CAP_BAC_CONFIG[yc['cap_moi']]['gioi_han_xem_ngay']} video/ngày\n"
                         f"💵 Thưởng/video: {CAP_BAC_CONFIG[yc['cap_moi']]['xu_moi_video']:,}đ\n"
                         f"🔔 Mã: <code>{h(yc['request_id'])}</code>")
                await context.bot.send_message(chat_id=yc["user_id"],text=txt,parse_mode="HTML")
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
    if not is_admin(update.effective_user.id):
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


async def admin_xu_ly_them_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
        elif action == "congnap":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount <= 0: raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)+? WHERE id=?", (amount, user_id))
            msg = f"✅ Đã cộng {amount:,}đ vào <b>số dư nạp</b> của <code>{user_id}</code>."
        elif action == "trunap":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount <= 0: raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET so_du_nap=MAX(0,COALESCE(so_du_nap,0)-?) WHERE id=?", (amount, user_id))
            msg = f"✅ Đã trừ {amount:,}đ khỏi <b>số dư nạp</b> của <code>{user_id}</code>."
        elif action == "setbalnap":
            amount = int(raw.replace(",", "").replace(".", ""))
            if amount < 0: raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET so_du_nap=? WHERE id=?", (amount, user_id))
            msg = f"✅ Đã đặt <b>số dư nạp</b> thành {amount:,}đ cho <code>{user_id}</code>."
        elif action == "cap":
            if raw not in CAP_BAC_CONFIG:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET cap_nap=?, cap_bac=? WHERE id=?", (raw, raw, user_id))
            msg = f"✅ Đã đổi <b>cấp nạp</b> của <code>{user_id}</code> thành <b>{h(raw)}</b>."
        elif action == "capgt":
            if raw not in CAP_BAC_CONFIG:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET cap_gioi_thieu=? WHERE id=?", (raw, user_id))
            msg = f"✅ Đã đổi <b>cấp giới thiệu</b> của <code>{user_id}</code> thành <b>{h(raw)}</b>."
        elif action == "capnap":
            if raw not in CAP_BAC_CONFIG:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET cap_nap=?, cap_bac=? WHERE id=?", (raw, raw, user_id))
            msg = f"✅ Đã đổi <b>cấp nạp</b> của <code>{user_id}</code> thành <b>{h(raw)}</b>."
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
        elif action == "video_ngay":
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET video_ngay=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã đặt video hôm nay của <code>{user_id}</code> thành <b>{value}</b>."
        elif action == "earned":
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET total_earned=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã đặt tổng tiền đã kiếm của <code>{user_id}</code> thành <b>{value:,}đ</b>."
        elif action == "withdrawn":
            value = int(raw.replace(",", "").replace(".", ""))
            if value < 0:
                raise ValueError
            with db() as conn:
                conn.execute("UPDATE users SET total_withdrawn=? WHERE id=?", (value, user_id))
            msg = f"✅ Đã đặt tổng tiền đã rút của <code>{user_id}</code> thành <b>{value:,}đ</b>."
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    # Telegram callback queries expire quickly. A stale click is harmless and
    # must not trigger a second callback response (which creates another error).
    if isinstance(context.error, BadRequest) and "Query is too old" in str(context.error):
        LOGGER.warning("Ignoring expired callback query: %s", context.error)
        return
    LOGGER.exception("Unhandled Telegram error", exc_info=context.error)
    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.answer("⚠️ Có lỗi tạm thời. Vui lòng thử lại.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text("⚠️ Có lỗi tạm thời. Vui lòng thử lại hoặc bấm /start.")
    except Exception:
        LOGGER.exception("Could not send user-facing error message")



# ============================================================
# ENHANCED FEATURES V3
# ============================================================
import csv
import json
import tempfile
from datetime import date
from collections import Counter

# Multi-admin: ADMIN_ID luôn là owner, ADMIN_IDS có thể thêm nhiều ID.
try:
    _ENV_ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
except ValueError:
    _ENV_ADMIN_IDS = []
ADMIN_IDS = set(_ENV_ADMIN_IDS) | {ADMIN_ID}

RANK_ICONS = [cfg.get("icon", "⭐") for cfg in CAP_BAC_CONFIG.values()]
RANK_NAMES = list(CAP_BAC_CONFIG.keys())


def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        with db() as conn:
            row = conn.execute("SELECT active FROM admins WHERE admin_id=?", (int(user_id),)).fetchone()
            return bool(row and row["active"])
    except Exception:
        return False


def admin_role(user_id: int) -> str:
    if user_id == ADMIN_ID:
        return "owner"
    try:
        with db() as conn:
            row = conn.execute("SELECT role FROM admins WHERE admin_id=? AND active=1", (int(user_id),)).fetchone()
            return row["role"] if row else "none"
    except Exception:
        return "none"


def _safe_add_column(conn, table, column, definition):
    try:
        if DATABASE_URL:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception:
        # Migration idempotent: column may already exist.
        try:
            conn.rollback()
        except Exception:
            pass


_ORIGINAL_INIT_DB_V3 = init_db

def init_db():
    _ORIGINAL_INIT_DB_V3()
    serial_type = "BIGSERIAL" if DATABASE_URL else "INTEGER"
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_tasks (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                target INTEGER NOT NULL,
                reward BIGINT NOT NULL,
                period TEXT NOT NULL DEFAULT 'daily',
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_claims (
                user_id BIGINT NOT NULL,
                task_code TEXT NOT NULL,
                period_key TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, task_code, period_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                code TEXT PRIMARY KEY,
                reward BIGINT NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                service_type TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_code_uses (
                code TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                used_at TEXT NOT NULL,
                PRIMARY KEY (code, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_spins (
                user_id BIGINT PRIMARY KEY,
                spin_date TEXT NOT NULL,
                spins INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS video_watch_logs (
                id {serial_type} PRIMARY KEY,
                user_id BIGINT NOT NULL,
                video_id INTEGER,
                watched_at TEXT NOT NULL,
                claimed INTEGER NOT NULL DEFAULT 0,
                reward BIGINT NOT NULL DEFAULT 0
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS suspicious_events (
                id {serial_type} PRIMARY KEY,
                user_id BIGINT,
                kind TEXT NOT NULL,
                detail TEXT,
                risk INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS scheduled_notifications (
                id {serial_type} PRIMARY KEY,
                send_time TEXT NOT NULL,
                frequency TEXT NOT NULL DEFAULT 'once',
                target TEXT NOT NULL DEFAULT 'all',
                content TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                last_sent_date TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id BIGINT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'admin',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS event_settings (
                id {serial_type} PRIMARY KEY,
                name TEXT NOT NULL,
                multiplier REAL NOT NULL DEFAULT 1,
                starts_at TEXT,
                ends_at TEXT,
                active INTEGER NOT NULL DEFAULT 0
            )
        """)
        _safe_add_column(conn, "withdrawals", "risk_score", "INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "withdrawals", "account_hash", "TEXT")
        _safe_add_column(conn, "withdrawals", "risk_flags", "TEXT")
        _safe_add_column(conn, "withdrawals", "reviewed_at", "TEXT")
        _safe_add_column(conn, "withdrawals", "reject_reason", "TEXT")
        _safe_add_column(conn, "video_links", "active", "INTEGER NOT NULL DEFAULT 1")
        _safe_add_column(conn, "video_links", "views", "INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "video_links", "claimed", "INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "video_links", "reward_total", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_column(conn, "users", "risk_score", "INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "users", "last_active_at", "TEXT")
        _safe_add_column(conn, "users", "total_earned", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_column(conn, "users", "so_du_nap", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_column(conn, "users", "total_withdrawn", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_column(conn, "users", "last_withdraw_at", "TEXT")
        _safe_add_column(conn, "users", "new_user_bonus_claimed", "INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "withdrawals", "reject_reason", "TEXT")
        _safe_add_column(conn, "withdrawals", "approved_by", "BIGINT")
        _safe_add_column(conn, "withdrawals", "rejected_by", "BIGINT")
        _safe_add_column(conn, "video_links", "category", "TEXT NOT NULL DEFAULT 'default'")
        _safe_add_column(conn, "video_links", "created_at", "TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS user_activity_logs (
            id %s PRIMARY KEY, user_id BIGINT NOT NULL, action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
        )""" % serial_type)
        conn.execute("""CREATE TABLE IF NOT EXISTS referral_rewards (
            id %s PRIMARY KEY, referrer_id BIGINT NOT NULL, referred_id BIGINT NOT NULL, level INTEGER NOT NULL, amount BIGINT NOT NULL, created_at TEXT NOT NULL
        )""" % serial_type)

        tasks = [
            ("watch3", "🎬 Xem 3 video", "Hoàn thành 3 video trong ngày", 3, 10000, "daily"),
            ("watch10", "🔥 Xem 10 video", "Hoàn thành 10 video trong ngày", 10, 35000, "daily"),
            ("ref1", "👥 Mời 1 người", "Có thêm 1 người được giới thiệu", 1, 5000, "daily"),
            ("checkin", "🎁 Điểm danh", "Điểm danh hôm nay", 1, 5000, "daily"),
            ("week30", "🏆 Tuần bứt phá", "Hoàn thành 30 video trong tuần", 30, 80000, "weekly"),
        ]
        for t in tasks:
            conn.execute("""
                INSERT INTO daily_tasks(code,name,description,target,reward,period,active)
                VALUES (?,?,?,?,?,?,1)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name, description=excluded.description,
                target=excluded.target, reward=excluded.reward, period=excluded.period, active=1
            """, t)
        defaults = {
            "new_user_bonus": "5000",
            "thuong_diem_danh": "5000",
            "thuong_tuan": "15000",
            "risk_rut_lon": "1000000",
            "captcha_required": "1",
            "tasks_enabled": "1",
            "phi_xac_minh": "30000",
            "maintenance_mode": "0",
            "video_reward_multiplier": "1",
            "support_username": "@hotroxutiktok",
            "support_hours": "8:00 - 22:00 hàng ngày",
            "announcement_channel": "@rutxutiktok",
            "withdraw_announcement_channel": "@rutxutiktok",
            "required_channel_1": "@rutxutiktok",
            "required_channel_2": "@thongbaoxutiktok",
            "required_channel_link_1": "https://t.me/rutxutiktok",
            "required_channel_link_2": "https://t.me/thongbaoxutiktok",
            "video_default_link": "https://vt.tiktok.com/ZSb6JTwaf/",
            "verify_bank": "ACB",
            "verify_account_name": "HA QUANG MINH",
            "verify_account_number": "25607451",
            "maintenance_message": "🚧 BOT ĐANG BẢO TRÌ\n\nVui lòng quay lại sau.",
        }
        for _k,_v in defaults.items():
            conn.execute("INSERT INTO system_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING", (_k,_v))
        if not conn.execute("SELECT 1 FROM admins WHERE admin_id=?", (ADMIN_ID,)).fetchone():
            conn.execute(
                "INSERT INTO admins(admin_id,role,active,created_at) VALUES (?,?,1,?)",
                (ADMIN_ID, "owner", now_vn().strftime("%d/%m/%Y %H:%M:%S")),
            )
        # Migrate tên cấp cũ sang hệ thống cấp mới để database hiện tại không lỗi.
        rank_migrations={
            "Leader Bạc":"Leader Bạc I", "Leader Vàng":"Leader Vàng I",
            "Leader Bạch Kim":"Leader Bạch Kim I", "Leader Ruby":"Leader Ruby I",
            "Leader Sapphire":"Leader Sapphire I", "Leader Kim Cương":"Leader Kim Cương I",
            "Leader Titan":"Leader Titan I", "Leader Cao Thủ":"Leader Cao Thủ I",
            "Leader Đại Cao Thủ":"Leader Đại Cao Thủ I", "Leader Huyền Thoại":"Leader Huyền Thoại I",
            "Leader Bất Diệt":"Leader Bất Diệt I", "Leader Tối Thượng":"Leader Tối Thượng I",
            "Leader Thần Thoại":"Leader Thần Thoại I",
        }
        for _old,_new in rank_migrations.items():
            conn.execute("UPDATE users SET cap_bac=? WHERE cap_bac=?",(_new,_old))
            conn.execute("UPDATE deposits SET cap_moi=? WHERE cap_moi=?",(_new,_old))
        # Khôi phục thông số cấp bậc đã được Admin tùy chỉnh.
        for _name in CAP_BAC_CONFIG:
            try:
                _saved = conn.execute("SELECT value FROM system_settings WHERE key=?", ("rank_cfg:"+_name,)).fetchone()
                if _saved and _saved[0]:
                    _cfg=json.loads(_saved[0])
                    for _k in ("xu_moi_video","gioi_han_xem_ngay","thuong_gioi_thieu"):
                        if _k in _cfg: CAP_BAC_CONFIG[_name][_k]=int(_cfg[_k])
            except Exception:
                pass

        # V18: điều chỉnh thưởng xem video theo bảng 20 cấp giới thiệu mới.
        # Chỉ áp dụng một lần cho DB cũ, sau đó Admin vẫn có thể tự chỉnh từng cấp.
        try:
            reward_version = conn.execute("SELECT value FROM system_settings WHERE key=?", ("video_reward_version",)).fetchone()
            if not reward_version or str(reward_version[0]) != "2":
                _video_reward_v2 = [
                    1500, 1800, 2200, 2600, 3000, 3400, 3800, 4200, 4600, 5000,
                    5500, 6000, 6500, 7000, 7500, 8000, 8500, 9000, 9500, 10000
                ]
                for _idx, (_name, _lo, _hi) in enumerate(MOC_CAP[:20]):
                    if _name in CAP_BAC_CONFIG:
                        CAP_BAC_CONFIG[_name]["xu_moi_video"] = _video_reward_v2[_idx]
                        try:
                            conn.execute(
                                "INSERT INTO system_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                ("rank_cfg:"+_name, json.dumps(CAP_BAC_CONFIG[_name], ensure_ascii=False))
                            )
                        except Exception:
                            pass
                conn.execute("INSERT INTO system_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("video_reward_version", "2"))
        except Exception:
            pass

        # V18: phân loại lại các khoản NẠP TIỀN trực tiếp cũ nếu trước đây
        # từng bị ghi chung vào so_du. Chỉ lấy đơn nap_tien/balance, không đụng
        # các gói nâng cấp cấp bậc. Chạy đúng một lần.
        try:
            split_version = conn.execute("SELECT value FROM system_settings WHERE key=?", ("balance_split_version",)).fetchone()
            if not split_version or str(split_version[0]) != "1":
                rows = conn.execute("""
                    SELECT user_id, COALESCE(SUM(gia),0) AS total_nap
                    FROM deposits
                    WHERE status='approved'
                      AND (goi_key='nap_tien' OR deposit_type='balance')
                    GROUP BY user_id
                """).fetchall()
                for _r in rows:
                    _uid = _r['user_id']
                    _nap = int(_r['total_nap'] or 0)
                    _urow = conn.execute("SELECT so_du,so_du_nap FROM users WHERE id=?", (_uid,)).fetchone()
                    if not _urow or _nap <= 0:
                        continue
                    _existing_nap = int(_urow['so_du_nap'] or 0)
                    # Chỉ chuyển phần còn thiếu sang ví nạp; không làm âm ví kiếm được.
                    _missing = max(0, _nap - _existing_nap)
                    _move = min(_missing, int(_urow['so_du'] or 0))
                    if _move > 0:
                        conn.execute("UPDATE users SET so_du=so_du-?, so_du_nap=COALESCE(so_du_nap,0)+? WHERE id=?", (_move,_move,_uid))
                conn.execute("INSERT INTO system_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("balance_split_version", "1"))
        except Exception:
            pass



def log_user_activity(user_id, action, detail=""):
    try:
        with db() as conn:
            conn.execute("INSERT INTO user_activity_logs(user_id,action,detail,created_at) VALUES (?,?,?,?)",
                         (int(user_id), str(action), str(detail)[:1000], now_vn().strftime("%d/%m/%Y %H:%M:%S")))
    except Exception:
        pass


def get_active_event_multiplier():
    try:
        with db() as conn:
            ev=conn.execute("SELECT multiplier,ends_at FROM event_settings WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
        if not ev:
            return 1.0
        if ev['ends_at']:
            try:
                if now_vn() > datetime.strptime(ev['ends_at'], "%d/%m/%Y %H:%M:%S").replace(tzinfo=VN_TZ):
                    with db() as conn: conn.execute("UPDATE event_settings SET active=0 WHERE id=(SELECT MAX(id) FROM event_settings)")
                    return 1.0
            except Exception:
                pass
        return max(1.0, float(ev['multiplier'] or 1))
    except Exception:
        return 1.0


def _role_allows(user_id, action):
    role=admin_role(user_id)
    if role == 'owner': return True
    matrix={
        'view': {'admin','mod','support'},
        'users': {'admin','mod'},
        'money': {'admin'},
        'settings': {'admin'},
        'broadcast': {'admin','support'},
        'super': {'owner'},
    }
    return role in matrix.get(action, {'admin'})


def _target_users(target):
    with db() as conn:
        if target == 'all': return conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()
        if target == 'locked': return conn.execute("SELECT id FROM users WHERE bi_khoa=1").fetchall()
        if target == 'verified': return conn.execute("SELECT id FROM users WHERE xac_minh_nguoi_that=1 AND bi_khoa=0").fetchall()
        if target == 'unverified': return conn.execute("SELECT id FROM users WHERE xac_minh_nguoi_that=0 AND bi_khoa=0").fetchall()
        if target.startswith('rank:'): return conn.execute("SELECT id FROM users WHERE cap_bac=? AND bi_khoa=0", (target[5:],)).fetchall()
        return conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()


async def pro_withdraw_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    data=q.data
    if not is_admin(update.effective_user.id) or not _role_allows(update.effective_user.id,'money'):
        await q.answer("⛔ Bạn không có quyền thao tác tài chính.", show_alert=True); return
    if data.startswith('pro_wd_confirm:'):
        rid=data.split(':',1)[1]
        await _approve_withdrawal_by_admin(q, context, rid)
    elif data.startswith('pro_wd_reject:'):
        rid=data.split(':',1)[1]
        context.user_data['reject_withdrawal']=rid
        await q.answer()
        await q.message.reply_text("❌ Nhập lý do từ chối đơn rút (hoặc nhập - để bỏ qua):", reply_markup=ReplyKeyboardRemove())
        return ADMIN_EXT_INPUT


async def _approve_withdrawal_by_admin(q, context, request_id):
    with db() as conn:
        conn.execute("BEGIN")
        yc=conn.execute("SELECT * FROM withdrawals WHERE request_id=? AND status='pending'",(request_id,)).fetchone()
        if not yc:
            conn.rollback(); await q.edit_message_text("❌ Đơn không tồn tại hoặc đã xử lý."); return
        changed=conn.execute("UPDATE users SET so_du=so_du-?, total_withdrawn=COALESCE(total_withdrawn,0)+?, last_withdraw_at=? WHERE id=? AND so_du>=?",
                             (yc['so_tien'],yc['so_tien'],now_vn().strftime('%d/%m/%Y %H:%M:%S'),yc['user_id'],yc['so_tien'])).rowcount
        if changed!=1:
            conn.rollback(); await q.edit_message_text("❌ Số dư không đủ để duyệt."); return
        conn.execute("UPDATE withdrawals SET status='approved',approved_by=?,reviewed_at=? WHERE request_id=? AND status='pending'",
                     (q.from_user.id,now_vn().strftime('%d/%m/%Y %H:%M:%S'),request_id))
        earned_after=conn.execute('SELECT so_du FROM users WHERE id=?',(yc['user_id'],)).fetchone()
        _wallet_ledger(conn,yc['user_id'],'earned',-int(yc['so_tien']),int(earned_after['so_du'] or 0),'withdraw_approved',request_id,'Rút tiền được Admin duyệt')
        conn.commit()
    log_user_activity(yc['user_id'],'withdraw_approved',request_id)
    try:
        await context.bot.send_message(yc['user_id'], f"✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>\n\n📋 Mã: <code>{h(request_id)}</code>\n💵 Số tiền: {yc['so_tien']:,}đ\n🔗 Tài khoản: {h(yc['tai_khoan'])}\n\n✅ Đã duyệt.", parse_mode='HTML')
        await gui_thong_bao_rut_thanh_cong(context,request_id,yc['so_tien'],yc['tai_khoan'],yc['ten'])
    except Exception: pass
    await q.edit_message_text(f"✅ Đã duyệt {h(request_id)} — trừ {yc['so_tien']:,}đ.")


async def pro_withdraw_reject_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid=context.user_data.pop('reject_withdrawal',None)
    if not rid or not is_admin(update.effective_user.id): return ConversationHandler.END
    reason=(update.effective_message.text or '-').strip()
    with db() as conn:
        row=conn.execute("SELECT * FROM withdrawals WHERE request_id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            await update.message.reply_text('❌ Đơn đã được xử lý.',reply_markup=menu_chinh(update.effective_user.id)); return ConversationHandler.END
        conn.execute("UPDATE withdrawals SET status='rejected',reject_reason=?,rejected_by=?,reviewed_at=? WHERE request_id=? AND status='pending'",
                     ('' if reason=='-' else reason,update.effective_user.id,now_vn().strftime('%d/%m/%Y %H:%M:%S'),rid))
    log_user_activity(row['user_id'],'withdraw_rejected',rid)
    try:
        await context.bot.send_message(row['user_id'],f"❌ <b>RÚT TIỀN BỊ TỪ CHỐI</b>\n\n📋 Mã: <code>{h(rid)}</code>\n💵 Số tiền: {row['so_tien']:,}đ\n📝 Lý do: {h(reason if reason!='-' else 'Không ghi rõ')}",parse_mode='HTML')
    except Exception: pass
    await update.message.reply_text('✅ Đã từ chối đơn rút.',reply_markup=menu_chinh(update.effective_user.id))
    return ConversationHandler.END


async def admin_bulk_video_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    urls=[x.strip() for x in (update.effective_message.text or '').splitlines() if x.strip()]
    urls=[x for x in urls if ('tiktok.com/' in x or x.startswith('https://vt.tiktok.com/'))]
    added=0
    with db() as conn:
        for url in urls:
            exists=conn.execute("SELECT 1 FROM video_links WHERE url=?",(url,)).fetchone()
            if not exists:
                conn.execute("INSERT INTO video_links(url,active,views,claimed,reward_total,category,created_at) VALUES (?,1,0,0,0,'default',?)",(url,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
                added+=1
    await update.message.reply_text(f"✅ Đã thêm <b>{added}</b> video, bỏ qua {len(urls)-added} link trùng/không hợp lệ.",parse_mode='HTML',reply_markup=menu_chinh(update.effective_user.id))
    return ConversationHandler.END


async def admin_user_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try: uid=int(q.data.split(':')[1])
    except Exception: return
    with db() as conn:
        u=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        w=conn.execute("SELECT COUNT(*) c,COALESCE(SUM(so_tien),0) total FROM withdrawals WHERE user_id=? AND status='approved'",(uid,)).fetchone()
        a=conn.execute("SELECT action,detail,created_at FROM user_activity_logs WHERE user_id=? ORDER BY id DESC LIMIT 10",(uid,)).fetchall()
    if not u:
        await q.edit_message_text('❌ Không tìm thấy user.'); return
    logs='\n'.join(f"• {h(r['created_at'])} — {h(r['action'])} — {h(r['detail'] or '')}" for r in a) or 'Chưa có hoạt động.'
    text=f"📊 <b>THỐNG KÊ USER</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <code>{uid}</code>\n👤 {h(u['ten'])}\n👑 {h(u['cap_bac'])}\n💰 Số dư: <b>{u['so_du']:,}đ</b>\n💵 Đã rút: <b>{w['total']:,}đ</b> ({w['c']} đơn)\n🎬 Video: <b>{u['video_da_xem']:,}</b>\n👥 Giới thiệu: <b>{u['gioi_thieu']:,}</b>\n\n📜 <b>Hoạt động gần đây</b>\n{logs}"
    await q.edit_message_text(text,parse_mode='HTML',reply_markup=_admin_user_detail_keyboard(uid))


async def admin_pro_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data
    if not is_admin(update.effective_user.id): return
    if data.startswith('pro_user_stats:'): return await admin_user_stats_callback(update,context)
    if data.startswith('pro_wd_confirm:') or data.startswith('pro_wd_reject:'): return await pro_withdraw_confirm_callback(update,context)
    if data=='pro_video_bulk':
        context.user_data['admin_ext_mode']='video_bulk'
        await q.answer(); await q.message.reply_text('🎬 Gửi nhiều link TikTok, mỗi link một dòng:',reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT
    if data=='pro_broadcast:verified' or data=='pro_broadcast:unverified' or data=='pro_broadcast:rank':
        context.user_data['admin_ext_mode']=data.replace('pro_broadcast:','broadcast:')
        await q.answer(); await q.message.reply_text('📢 Nhập nội dung thông báo:',reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT
    if data=='pro_settings_more':
        await q.answer();
        keys=['new_user_bonus','risk_rut_lon','rut_toi_thieu','rut_toi_da','rut_so_lan_ngay','rut_cooldown_giay','captcha_enabled','tasks_enabled']
        with db() as conn: vals={k:get_setting(k,'0') for k in keys}
        await q.message.reply_text('⚙️ <b>CÀI ĐẶT NÂNG CAO</b>\n\n'+'\n'.join(f'• {k}: <b>{h(vals[k])}</b>' for k in keys),parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚙️ Quản lý dịch vụ',callback_data='admin_svc:list'), InlineKeyboardButton('⬅️ Admin',callback_data='admin_home')]])); return
    if data=='pro_wd_approve_list':
        await q.answer();
        with db() as conn: rows=conn.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY risk_score DESC,thoi_gian DESC LIMIT 30").fetchall()
        for r in rows:
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Xác nhận duyệt',callback_data=f"pro_wd_confirm:{r['request_id']}"),InlineKeyboardButton('❌ Từ chối',callback_data=f"pro_wd_reject:{r['request_id']}")]])
            await q.message.reply_text(f"💸 <b>{r['so_tien']:,}đ</b> — ID {r['user_id']}\n📋 <code>{h(r['request_id'])}</code>\n🚨 Risk: {r.get('risk_score',0)}",parse_mode='HTML',reply_markup=kb)
        return

def _rank_info(index):
    if index < 0 or index >= len(MOC_CAP):
        return None
    name, lo, hi = MOC_CAP[index]
    return {"index": index, "name": name, "min": lo, "max": hi, **CAP_BAC_CONFIG[name]}


def _rank_icon(name):
    return CAP_BAC_CONFIG.get(name, {}).get("icon", "⭐")


def _rank_progress(u):
    current = u.get("cap_bac") or "Thành viên"
    idx = RANK_NAMES.index(current) if current in RANK_NAMES else 0
    cur = MOC_CAP[idx]
    if idx >= len(MOC_CAP) - 1:
        return idx, cur, None, 0
    nxt = MOC_CAP[idx + 1]
    need = max(0, nxt[1] - int(u.get("gioi_thieu", 0)))
    span = max(1, nxt[1] - cur[1])
    done = min(span, max(0, int(u.get("gioi_thieu", 0)) - cur[1]))
    pct = int(done * 100 / span)
    return idx, cur, nxt, pct


def _rank_bar(pct, width=10):
    filled = max(0, min(width, int(width * pct / 100)))
    return "█" * filled + "░" * (width - filled)


async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return
    reset_daily_if_needed(u)
    idx, cur, nxt, pct = _rank_progress(u)
    cfg = CAP_BAC_CONFIG.get(u["cap_bac"], CAP_BAC_CONFIG["Thành viên"])
    xac = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that", 0) else "🔒 Chưa xác minh"
    if nxt:
        next_line = f"🎯 Còn <b>{max(0, nxt[1]-u['gioi_thieu']):,}</b> giới thiệu → {_rank_icon(nxt[0])} <b>{h(nxt[0])}</b>"
        progress = f"📊 <code>{_rank_bar(pct)}</code> {pct}%"
    else:
        next_line = "🏆 Bạn đang ở cấp cao nhất hệ thống!"
        progress = "📊 <code>██████████</code> 100%"
    await update.message.reply_text(
        f"👤 <b>HỒ SƠ THÀNH VIÊN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{u['id']}</code>\n"
        f"👤 Tên: <b>{h(u['ten'])}</b>\n"
        f"{_rank_icon(u['cap_bac'])} Cấp bậc: <b>{h(u['cap_bac'])}</b>\n"
        f"💰 Số dư: <b>{u['so_du']:,}đ</b>\n"
        f"👥 Giới thiệu: <b>{u['gioi_thieu']:,}</b>\n"
        f"🎬 Video: <b>{u['video_da_xem']:,}</b>\n"
        f"📺 Hôm nay: <b>{u['video_ngay']}/{cfg['gioi_han_xem_ngay']}</b>\n"
        f"💵 Thưởng/video: <b>{cfg['xu_moi_video']:,}đ</b>\n"
        f"🛡 Xác minh: {xac}\n"
        f"🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>\n\n"
        f"🚀 <b>TIẾN ĐỘ CẤP</b>\n{progress}\n{next_line}",
        parse_mode="HTML", reply_markup=menu_chinh(u["id"]),
    )


async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid) or {}
    current = u.get("cap_bac") or "Thành viên"
    icon = _rank_icon(current)
    progress = _rank_progress(u)
    idx, cur, nxt, pct = progress
    if nxt:
        need = max(0, nxt[1] - int(u.get("gioi_thieu", 0)))
        next_line = f"🚀 Còn <b>{need:,}</b> lượt giới thiệu để lên {h(_rank_icon(nxt[0]) + ' ' + nxt[0])}"
    else:
        next_line = "🏆 <b>Bạn đang ở cấp cao nhất!</b>"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥈 Gói Bạc", callback_data="goi_bac"), InlineKeyboardButton("🥇 Gói Vàng", callback_data="goi_vang")],
        [InlineKeyboardButton("💎 Gói Bạch Kim", callback_data="goi_bachkim"), InlineKeyboardButton("💠 Gói Kim Cương", callback_data="goi_kimcuong")],
        [InlineKeyboardButton(f"📜 XEM TOÀN BỘ {len(MOC_CAP)} CẤP", callback_data="rank_page:0")],
        [InlineKeyboardButton("📊 XEM CẤP TIẾP THEO", callback_data=f"rank_info:{min(idx+1, len(MOC_CAP)-1)}")],
    ])
    await update.message.reply_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{icon} Cấp hiện tại: <b>{h(current)}</b>\n"
        f"👥 Giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b>\n"
        f"📈 Tiến độ: <b>{pct}%</b> {_rank_bar(pct)}\n"
        f"{next_line}\n\n"
        f"✨ Hệ thống hiện có <b>{len(MOC_CAP)} cấp</b>, tự động thăng cấp theo số người giới thiệu.",
        parse_mode="HTML", reply_markup=keyboard,
    )


async def rank_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try: page = int(q.data.split(":")[1])
    except Exception: page = 0
    page_size = 7
    total = len(MOC_CAP)
    page = max(0, min(page, (total-1)//page_size))
    start = page * page_size
    rows = MOC_CAP[start:start+page_size]
    buttons = []
    for i,(name,lo,hi) in enumerate(rows, start):
        icon = _rank_icon(name)
        limit = f"{lo:,}+" if hi >= 999999999 else f"{lo:,}–{hi:,}"
        buttons.append([InlineKeyboardButton(f"{icon} {name} • {limit}", callback_data=f"rank_info:{i}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"rank_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"📖 {page+1}/{(total+page_size-1)//page_size}", callback_data="rank_noop"))
    if start+page_size<total: nav.append(InlineKeyboardButton("➡️", callback_data=f"rank_page:{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅️ Nâng cấp", callback_data="rank_back")])
    text = f"🏆 <b>HỆ THỐNG {len(MOC_CAP)} CẤP BẬC</b>\n━━━━━━━━━━━━━━━━━━━━\nChọn một cấp để xem quyền lợi:"
    try: await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception: await q.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def rank_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try: idx=int(q.data.split(":")[1])
    except Exception: return
    r=_rank_info(idx)
    if not r: return
    limit=f"{r['min']:,}+" if r['max']>=999999999 else f"{r['min']:,}–{r['max']:,}"
    u=get_user(update.effective_user.id)
    current = u and u.get("cap_bac") == r["name"]
    text=(f"{r['icon']} <b>{h(r['name'])}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"👥 Mốc giới thiệu: <b>{limit}</b>\n"
          f"💵 Thưởng/video: <b>{r['xu_moi_video']:,}đ</b>\n"
          f"📺 Giới hạn: <b>{r['gioi_han_xem_ngay']}</b> video/ngày\n"
          f"👥 Thưởng giới thiệu: <b>{r['thuong_gioi_thieu']:,}đ/người</b>\n\n"
          f"{'✅ CẤP HIỆN TẠI' if current else '🔒 Cấp mục tiêu'}")
    nav=[]
    if idx > 0: nav.append(InlineKeyboardButton("⬅️ Cấp trước", callback_data=f"rank_info:{idx-1}"))
    if idx < len(MOC_CAP)-1: nav.append(InlineKeyboardButton("Cấp sau ➡️", callback_data=f"rank_info:{idx+1}"))
    buttons=[]
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("📜 Danh sách cấp", callback_data=f"rank_page:{idx//7}")])
    buttons.append([InlineKeyboardButton("👑 Về nâng cấp", callback_data="rank_back")])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def rank_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not int(get_setting("tasks_enabled", 1)):
        await update.message.reply_text("🎯 Hệ thống nhiệm vụ đang tạm tắt.",reply_markup=menu_chinh(update.effective_user.id)); return
    u=get_user(update.effective_user.id)
    if not u: return
    today=today_vn()
    week=now_vn().strftime("%G-W%V")
    with db() as conn:
        rows=conn.execute("SELECT * FROM daily_tasks WHERE active=1 ORDER BY period, code").fetchall()
        claims=conn.execute("SELECT task_code,period_key FROM task_claims WHERE user_id=? AND period_key IN (?,?)", (u['id'],today,week)).fetchall()
    claimed={(r['task_code'],r['period_key']) for r in claims}
    lines=["🎯 <b>NHIỆM VỤ & PHẦN THƯỞNG</b>","━━━━━━━━━━━━━━━━━━━━"]
    buttons=[]
    for t in rows:
        key=t['period']; period_key=today if key=='daily' else week
        progress=0
        if t['code'].startswith('watch'): progress=u['video_ngay'] if key=='daily' else u['video_da_xem']
        elif t['code']=='ref1': progress=u['gioi_thieu']
        elif t['code']=='checkin':
            with db() as conn:
                ck=conn.execute("SELECT last_date FROM daily_checkins WHERE user_id=?",(u['id'],)).fetchone()
            progress=1 if ck and ck['last_date']==today else 0
        done=progress>=t['target']; was=(t['code'],period_key) in claimed
        status="🎁 ĐÃ NHẬN" if was else ("✅ HOÀN THÀNH" if done else f"{min(progress,t['target'])}/{t['target']}")
        lines.append(f"{h(t['name'])} — <b>+{t['reward']:,}đ</b>\n└ {h(t['description'])} • {status}")
        if done and not was: buttons.append([InlineKeyboardButton(f"🎁 Nhận {t['reward']:,}đ — {t['name']}", callback_data=f"task_claim:{t['code']}")])
    buttons.append([InlineKeyboardButton("🔄 Làm mới", callback_data="tasks_refresh"), InlineKeyboardButton("⬅️ Menu", callback_data="ve_menu_chinh")])
    await update.message.reply_text("\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))


async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    data=q.data
    if data in ("tasks_refresh",):
        u=get_user(update.effective_user.id)
        if not u: return
        # Re-render nhiệm vụ từ callback để không phụ thuộc update.message.
        await q.message.delete()
        await q.message.chat.send_message('🎯 Đang tải lại nhiệm vụ...')
        fake=type('Obj',(),{'message':q.message.chat, 'effective_user':update.effective_user})()
        # Gửi lại bằng hàm nội bộ đơn giản.
        today=today_vn(); week=now_vn().strftime('%G-W%V')
        with db() as conn:
            rows=conn.execute("SELECT * FROM daily_tasks WHERE active=1 ORDER BY period,code").fetchall()
            claims=conn.execute("SELECT task_code,period_key FROM task_claims WHERE user_id=? AND period_key IN (?,?)",(u['id'],today,week)).fetchall()
        claimed={(r['task_code'],r['period_key']) for r in claims}
        lines=['🎯 <b>NHIỆM VỤ & PHẦN THƯỞNG</b>','━━━━━━━━━━━━━━━━━━━━']; buttons=[]
        for t in rows:
            period_key=today if t['period']=='daily' else week
            if t['code'].startswith('watch'): progress=u['video_ngay'] if t['period']=='daily' else u['video_da_xem']
            elif t['code']=='ref1': progress=u['gioi_thieu']
            elif t['code']=='checkin':
                with db() as conn: ck=conn.execute("SELECT last_date FROM daily_checkins WHERE user_id=?",(u['id'],)).fetchone()
                progress=1 if ck and ck['last_date']==today else 0
            else: progress=0
            done=progress>=t['target']; was=(t['code'],period_key) in claimed
            status='🎁 ĐÃ NHẬN' if was else ('✅ HOÀN THÀNH' if done else f'{min(progress,t["target"])} / {t["target"]}')
            lines.append(f"{h(t['name'])} — <b>+{t['reward']:,}đ</b>\n└ {h(t['description'])} • {status}")
            if done and not was: buttons.append([InlineKeyboardButton(f'🎁 Nhận {t["reward"]:,}đ',callback_data=f'task_claim:{t["code"]}')])
        buttons.append([InlineKeyboardButton('🔄 Làm mới',callback_data='tasks_refresh'),InlineKeyboardButton('⬅️ Menu',callback_data='ve_menu_chinh')])
        await q.message.chat.send_message('\n'.join(lines),parse_mode='HTML',reply_markup=InlineKeyboardMarkup(buttons)); return
    if not data.startswith("task_claim:"): return
    code=data.split(":",1)[1]; u=get_user(update.effective_user.id)
    if not u: return
    today=today_vn(); week=now_vn().strftime("%G-W%V")
    with db() as conn:
        t=conn.execute("SELECT * FROM daily_tasks WHERE code=? AND active=1",(code,)).fetchone()
        if not t: await q.answer("Nhiệm vụ không tồn tại.",show_alert=True); return
        period_key=today if t['period']=='daily' else week
        old=conn.execute("SELECT 1 FROM task_claims WHERE user_id=? AND task_code=? AND period_key=?",(u['id'],code,period_key)).fetchone()
        if old: await q.answer("Bạn đã nhận nhiệm vụ này rồi.",show_alert=True); return
        if code.startswith('watch'): progress=u['video_ngay'] if t['period']=='daily' else u['video_da_xem']
        elif code=='ref1': progress=u['gioi_thieu']
        elif code=='checkin':
            ck=conn.execute("SELECT last_date FROM daily_checkins WHERE user_id=?",(u['id'],)).fetchone(); progress=1 if ck and ck['last_date']==today else 0
        else: progress=0
        if progress<int(t['target']): await q.answer("❌ Chưa hoàn thành nhiệm vụ.",show_alert=True); return
        conn.execute("INSERT INTO task_claims(user_id,task_code,period_key,claimed_at) VALUES (?,?,?,?)",(u['id'],code,period_key,now_vn().strftime("%d/%m/%Y %H:%M:%S")))
        conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?",(int(t['reward']),u['id']))
    await q.edit_message_text(f"🎉 <b>NHẬN NHIỆM VỤ THÀNH CÔNG</b>\n\n{h(t['name'])}\n💰 +{t['reward']:,}đ",parse_mode="HTML")


async def wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=get_user(update.effective_user.id)
    if not u: return
    await update.message.reply_text("🎡 <b>VÒNG QUAY MAY MẮN</b>\n━━━━━━━━━━━━━━━━━━━━\n🎁 Mỗi ngày 1 lượt quay.\n\n🎯 Phần thưởng: 0đ → 1.000đ → 2.000đ → 5.000đ → 10.000đ → 20.000đ",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎡 QUAY NGAY",callback_data="wheel_spin")],[InlineKeyboardButton("⬅️ Menu",callback_data="ve_menu_chinh")]]))


async def wheel_spin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=update.effective_user.id; today=today_vn()
    with db() as conn:
        row=conn.execute("SELECT * FROM daily_spins WHERE user_id=?",(uid,)).fetchone()
        if row and row['spin_date']==today and row['spins']>=1:
            await q.answer("⏳ Hôm nay bạn đã quay rồi.",show_alert=True); return
        reward=random.choices([0,1000,2000,5000,10000,20000],[5,25,25,20,15,10])[0]
        if row and row['spin_date']!=today:
            conn.execute("UPDATE daily_spins SET spin_date=?,spins=1 WHERE user_id=?",(today,uid))
        elif not row:
            conn.execute("INSERT INTO daily_spins(user_id,spin_date,spins) VALUES (?,?,1)",(uid,today))
        else:
            conn.execute("UPDATE daily_spins SET spins=spins+1 WHERE user_id=?",(uid,))
        if reward: conn.execute("UPDATE users SET so_du=so_du+? WHERE id=?",(reward,uid))
    await q.edit_message_text(f"🎉 <b>KẾT QUẢ VÒNG QUAY</b>\n\n🎁 Bạn nhận được: <b>+{reward:,}đ</b>\n💰 Hãy quay lại vào ngày mai!",parse_mode="HTML")


async def _gift_interrupt_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Thoát trạng thái Gift Code khi người dùng bấm menu khác.

    ConversationHandler group=0 sẽ kết thúc Gift Code, sau đó các
    ConversationHandler/MessageHandler ở group tiếp theo vẫn được phép
    xử lý cùng update (đặc biệt nút Rút Tiền). Đây là fix cho lỗi số tiền
    rút bị coi nhầm là Gift Code.
    """
    context.user_data.pop("gift_waiting", None)
    return ConversationHandler.END


async def _gift_interrupt_to_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("gift_waiting", None)
    # Trả END cho gift_conv; rut_conv ở group=1 sẽ xử lý chính nút này.
    return ConversationHandler.END


async def gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('dang_rut_tien', None)
    context.user_data.pop('dang_lien_ket', None)
    context.user_data['gift_waiting']=True
    await update.message.reply_text("🎁 <b>ĐỔI QUÀ / GIFT CODE</b>\n\nNhập mã quà tặng của bạn:",parse_mode="HTML",reply_markup=ReplyKeyboardRemove())
    return GIFT_INPUT


async def gift_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = (update.effective_message.text or '').strip().upper()
    uid = update.effective_user.id
    reward = 0
    expires_at = None

    with db() as conn:
        g = conn.execute(
            "SELECT * FROM gift_codes WHERE code=? AND active=1", (code,)
        ).fetchone()
        if not g:
            result = "missing"
        else:
            expires_at = g["expires_at"]
            result = "ok"
            if expires_at:
                try:
                    if now_vn() > datetime.strptime(
                        expires_at, "%d/%m/%Y %H:%M:%S"
                    ).replace(tzinfo=VN_TZ):
                        result = "expired"
                except ValueError:
                    result = "invalid_expiry"

            if result == "ok":
                used = conn.execute(
                    "SELECT 1 FROM gift_code_uses WHERE code=? AND user_id=?",
                    (code, uid),
                ).fetchone()
                if used:
                    result = "already_used"
                else:
                    # Atomic quota reservation. If two users redeem the last
                    # slot concurrently, only one UPDATE can reserve it.
                    changed = conn.execute(
                        """
                        UPDATE gift_codes
                        SET used_count=used_count+1
                        WHERE code=? AND active=1 AND used_count < max_uses
                        """,
                        (code,),
                    ).rowcount
                    if changed != 1:
                        result = "used_up"
                    else:
                        reward = int(g["reward"])
                        try:
                            conn.execute(
                                "INSERT INTO gift_code_uses(code,user_id,used_at) VALUES (?,?,?)",
                                (code, uid, now_vn().strftime("%d/%m/%Y %H:%M:%S")),
                            )
                        except Exception:
                            # The surrounding transaction rolls back the quota
                            # reservation too (important for duplicate clicks).
                            raise
                        conn.execute(
                            """
                            UPDATE users
                            SET so_du=so_du+?,
                                total_earned=COALESCE(total_earned,0)+?
                            WHERE id=?
                            """,
                            (reward, reward, uid),
                        )

    if result == "missing":
        await update.message.reply_text("❌ Gift code không tồn tại hoặc đã khóa.")
        return GIFT_INPUT
    if result == "expired":
        await update.message.reply_text("⏰ Gift code đã hết hạn.")
        context.user_data.pop("gift_waiting", None)
        return ConversationHandler.END
    if result == "invalid_expiry":
        await update.message.reply_text("⚠️ Gift code có thời hạn không hợp lệ.")
        context.user_data.pop("gift_waiting", None)
        return ConversationHandler.END
    if result == "already_used":
        await update.message.reply_text("❌ Bạn đã sử dụng mã này rồi.")
        return GIFT_INPUT
    if result == "used_up":
        await update.message.reply_text("❌ Gift code đã hết lượt sử dụng.")
        context.user_data.pop("gift_waiting", None)
        return ConversationHandler.END

    context.user_data.pop("gift_waiting", None)
    await update.message.reply_text(
        f"🎉 <b>ĐỔI QUÀ THÀNH CÔNG!</b>\n\n"
        f"🎁 Mã: <code>{h(code)}</code>\n"
        f"💰 Nhận: <b>+{reward:,}đ</b>",
        parse_mode="HTML",
        reply_markup=menu_chinh(uid),
    )
    return ConversationHandler.END

async def event_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        ev=conn.execute("SELECT * FROM event_settings WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not ev:
        await update.message.reply_text("🎉 Hiện chưa có sự kiện đặc biệt.",reply_markup=menu_chinh(update.effective_user.id)); return
    await update.message.reply_text(f"🎉 <b>{h(ev['name'])}</b>\n\n🔥 Hệ số thưởng: <b>x{ev['multiplier']}</b>\n⏰ Kết thúc: <b>{h(ev['ends_at'] or 'Chưa đặt')}</b>",parse_mode='HTML',reply_markup=menu_chinh(update.effective_user.id))


async def _admin_dashboard_content():
    with db() as conn:
        tong_nguoi=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        cho_rut=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        cho_nap=conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
        cho_xm=conn.execute("SELECT COUNT(*) FROM verification_requests WHERE status='pending'").fetchone()[0]
        so_du=conn.execute("SELECT COALESCE(SUM(so_du),0) FROM users").fetchone()[0]
        khoa=conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0]
        video=conn.execute("SELECT COUNT(*) FROM video_links WHERE active=1").fetchone()[0]
        risk=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending' AND risk_score>=50").fetchone()[0]
        total_out=conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved'").fetchone()[0]
        gift=conn.execute("SELECT COUNT(*) FROM gift_codes WHERE active=1").fetchone()[0]
        admins=conn.execute("SELECT COUNT(*) FROM admins WHERE active=1").fetchone()[0]
    text=("🎛 <b>BẢNG ĐIỀU KHIỂN ADMIN PRO</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"👥 Người dùng: <b>{tong_nguoi:,}</b> | 🔒 Khóa: <b>{khoa:,}</b>\n"
          f"💰 Tổng số dư: <b>{so_du:,}đ</b>\n"
          f"🎬 Video: <b>{video}</b> | 🎁 Gift code: <b>{gift}</b>\n"
          f"👮 Admin hoạt động: <b>{admins}</b>\n\n"
          f"📌 Chờ xử lý: 💸 {cho_rut} • 📥 {cho_nap} • 🛡 {cho_xm}\n"
          f"🚨 Rút có cảnh báo rủi ro: <b>{risk}</b>\n"
          f"💵 Tổng đã rút: <b>{total_out:,}đ</b>")
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Rút tiền",callback_data="admin_ds_rut"),InlineKeyboardButton("📥 Nạp / cấp",callback_data="admin_ds_nap")],
        [InlineKeyboardButton("🛡 Xác minh",callback_data="admin_ds_xacminh"),InlineKeyboardButton("👥 Người dùng",callback_data="admin_ds_nguoi")],
        [InlineKeyboardButton("🎬 Video & Thống kê",callback_data="admin_ext:video_stats"),InlineKeyboardButton("➕ Thêm nhiều Video",callback_data="pro_video_bulk")],
        [InlineKeyboardButton("🎯 Nhiệm vụ",callback_data="admin_ext:tasks"),InlineKeyboardButton("🎁 Gift code",callback_data="admin_ext:gift")],
        [InlineKeyboardButton("🎉 Sự kiện",callback_data="admin_ext:event"),InlineKeyboardButton("🛡 Anti-fraud",callback_data="admin_ext:fraud")],
        [InlineKeyboardButton("🧰 TRUNG TÂM QUẢN TRỊ",callback_data="admin_ext:panel"),InlineKeyboardButton("📊 Thống kê PRO",callback_data="admin_ext:stats")],
        [InlineKeyboardButton("🔎 Tìm đơn rút",callback_data="admin_ext:withdraw_search"),InlineKeyboardButton("📈 Lịch sử rút",callback_data="admin_ext:withdraw_stats")],
        [InlineKeyboardButton("✅ Duyệt rút 2 bước",callback_data="pro_wd_approve_list"),InlineKeyboardButton("⚙️ Cài đặt nâng cao",callback_data="pro_settings_more")],
        [InlineKeyboardButton("📢 Thông báo",callback_data="admin_gui_tb"),InlineKeyboardButton("⏰ Lịch thông báo",callback_data="admin_ext:schedule")],
        [InlineKeyboardButton("📢 Đã xác minh",callback_data="pro_broadcast:verified"),InlineKeyboardButton("📢 Chưa xác minh",callback_data="pro_broadcast:unverified")],
        [InlineKeyboardButton("💾 Backup DB",callback_data="admin_ext:backup"),InlineKeyboardButton("📤 Xuất CSV",callback_data="admin_ext:csv")],
        [InlineKeyboardButton("👮 Quản lý Admin",callback_data="admin_ext:admins"),InlineKeyboardButton("⚙️ Cài đặt PRO",callback_data="admin_ext:settings")],
        [InlineKeyboardButton("🛒 DỊCH VỤ ĐẶC BIỆT",callback_data="admin_svc:list"),InlineKeyboardButton("🧪 KIỂM TRA NÚT",callback_data="admin_button_audit")],
        [InlineKeyboardButton("🧩 Kênh / Liên hệ / Nội dung",callback_data="admin_ext:system")],
        [InlineKeyboardButton("🧰 ĐIỀU KHIỂN BOT",callback_data="admin_ext:control")],
        [InlineKeyboardButton("💰 Cộng tiền",callback_data="admin_cong_tien"),InlineKeyboardButton("💸 Trừ tiền",callback_data="admin_tru_tien")],
        [InlineKeyboardButton("🔄 Làm mới",callback_data="admin_refresh")],
    ])
    return text,kb


def _admin_user_detail_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Cộng tiền",callback_data=f"admin_edit:cong:{user_id}"),InlineKeyboardButton("💸 Trừ tiền",callback_data=f"admin_edit:tru:{user_id}")],
        [InlineKeyboardButton("💵 Đặt số dư",callback_data=f"admin_edit:setbal:{user_id}"),InlineKeyboardButton("🏆 Đổi cấp",callback_data=f"admin_edit:cap:{user_id}")],
        [InlineKeyboardButton("✏️ Sửa tên",callback_data=f"admin_edit:name:{user_id}"),InlineKeyboardButton("🏦 Sửa tài khoản",callback_data=f"admin_edit:account:{user_id}")],
        [InlineKeyboardButton("👥 Sửa giới thiệu",callback_data=f"admin_edit:gioithieu:{user_id}"),InlineKeyboardButton("🎬 Sửa video",callback_data=f"admin_edit:video:{user_id}")],
        [InlineKeyboardButton("📅 Sửa video hôm nay",callback_data=f"admin_edit:video_ngay:{user_id}"),InlineKeyboardButton("🎯 Reset lượt ngày",callback_data=f"admin_edit:resetday:{user_id}")],
        [InlineKeyboardButton("📈 Sửa tổng đã kiếm",callback_data=f"admin_edit:earned:{user_id}"),InlineKeyboardButton("💸 Sửa tổng đã rút",callback_data=f"admin_edit:withdrawn:{user_id}")],
        [InlineKeyboardButton("🛡 Xác minh",callback_data=f"admin_edit:verify:{user_id}"),InlineKeyboardButton("🔓 Bỏ xác minh",callback_data=f"admin_edit:unverify:{user_id}")],
        [InlineKeyboardButton("🔄 Reset CAPTCHA",callback_data=f"admin_edit:captcha:{user_id}")],
        [InlineKeyboardButton("🔒 Khóa",callback_data=f"admin_edit:lock:{user_id}"),InlineKeyboardButton("🔓 Mở khóa",callback_data=f"admin_edit:unlock:{user_id}")],
        [InlineKeyboardButton("🚨 Risk / Anti-fraud",callback_data=f"admin_ext:risk:{user_id}"),InlineKeyboardButton("📜 Lịch sử",callback_data=f"admin_history:{user_id}")],
        [InlineKeyboardButton("📊 Thống kê User",callback_data=f"pro_user_stats:{user_id}")],
        [InlineKeyboardButton("♻️ RESET TÀI KHOẢN",callback_data=f"admin_edit:reset:{user_id}")],
        [InlineKeyboardButton("⬅️ Danh sách",callback_data="admin_ds_nguoi")],
    ])


def _admin_control_values():
    keys = [
        "new_user_bonus", "thuong_diem_danh", "thuong_tuan", "phi_xac_minh",
        "rut_toi_thieu", "rut_toi_da", "rut_so_lan_ngay", "rut_cooldown_giay",
        "risk_rut_lon", "captcha_required", "tasks_enabled", "maintenance_mode",
        "video_reward_multiplier",
    ]
    return {k: get_setting(k, "0") for k in keys}


def _admin_control_text():
    v = _admin_control_values()
    on = lambda x: "🟢 BẬT" if str(x) == "1" else "🔴 TẮT"
    return (
        "🧰 <b>TRUNG TÂM ĐIỀU KHIỂN BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆕 Bonus user mới: <b>{int(v['new_user_bonus']):,}đ</b>\n"
        f"🎁 Điểm danh: <b>{int(v['thuong_diem_danh']):,}đ</b>\n"
        f"🏆 Thưởng tuần: <b>{int(v['thuong_tuan']):,}đ</b>\n"
        f"🛡 Phí xác minh: <b>{int(v['phi_xac_minh']):,}đ</b>\n"
        f"💰 Rút tối thiểu: <b>{int(v['rut_toi_thieu']):,}đ</b>\n"
        f"💰 Rút tối đa: <b>{int(v['rut_toi_da']):,}đ</b>\n"
        f"📅 Rút/ngày: <b>{int(v['rut_so_lan_ngay'])}</b>\n"
        f"⏱ Cooldown rút: <b>{int(v['rut_cooldown_giay'])} giây</b>\n"
        f"🚨 Ngưỡng rút lớn: <b>{int(v['risk_rut_lon']):,}đ</b>\n"
        f"🎬 Hệ số thưởng video: <b>x{float(v['video_reward_multiplier']):g}</b>\n"
        f"🔐 CAPTCHA: <b>{on(v['captcha_required'])}</b>\n"
        f"🎯 Nhiệm vụ: <b>{on(v['tasks_enabled'])}</b>\n"
        f"🚧 Bảo trì bot: <b>{on(v['maintenance_mode'])}</b>\n\n"
        "Chọn mục để chỉnh sửa. Giá trị được lưu ngay vào DB."
    )


def _admin_system_text():
    items = [
        ("support_username", "🎧 Hỗ trợ"), ("support_hours", "⏰ Giờ hỗ trợ"),
        ("announcement_channel", "📢 Kênh thông báo"), ("withdraw_announcement_channel", "💸 Kênh báo rút"),
        ("required_channel_1", "📢 Kênh bắt buộc 1"), ("required_channel_2", "📢 Kênh bắt buộc 2"),
        ("required_channel_link_1", "🔗 Link kênh 1"), ("required_channel_link_2", "🔗 Link kênh 2"),
        ("video_default_link", "🎬 Link video mặc định"), ("verify_bank", "🏦 Ngân hàng xác minh"),
        ("verify_account_name", "👤 Tên TK xác minh"), ("verify_account_number", "🔢 Số TK xác minh"),
        ("maintenance_message", "🚧 Nội dung bảo trì"),
    ]
    lines=["🧩 <b>CẤU HÌNH HỆ THỐNG</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for key,label in items:
        value=runtime_text(key, "")
        shown=value if len(value)<90 else value[:87]+"..."
        lines.append(f"{label}: <code>{h(shown)}</code>")
    lines.append("\nCác thay đổi được lưu ngay vào database.")
    return "\n".join(lines)


def _admin_system_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 Hỗ trợ",callback_data="admin_sys:support_username"),InlineKeyboardButton("⏰ Giờ hỗ trợ",callback_data="admin_sys:support_hours")],
        [InlineKeyboardButton("📢 Kênh thông báo",callback_data="admin_sys:announcement_channel"),InlineKeyboardButton("💸 Kênh báo rút",callback_data="admin_sys:withdraw_announcement_channel")],
        [InlineKeyboardButton("📢 Kênh bắt buộc 1",callback_data="admin_sys:required_channel_1"),InlineKeyboardButton("📢 Kênh bắt buộc 2",callback_data="admin_sys:required_channel_2")],
        [InlineKeyboardButton("🔗 Link kênh 1",callback_data="admin_sys:required_channel_link_1"),InlineKeyboardButton("🔗 Link kênh 2",callback_data="admin_sys:required_channel_link_2")],
        [InlineKeyboardButton("🎬 Link video mặc định",callback_data="admin_sys:video_default_link")],
        [InlineKeyboardButton("🏦 Ngân hàng",callback_data="admin_sys:verify_bank"),InlineKeyboardButton("👤 Tên TK",callback_data="admin_sys:verify_account_name")],
        [InlineKeyboardButton("🔢 Số TK",callback_data="admin_sys:verify_account_number")],
        [InlineKeyboardButton("🚧 Nội dung bảo trì",callback_data="admin_sys:maintenance_message")],
        [InlineKeyboardButton("⬅️ Cấu hình Bot",callback_data="admin_ext:config")],
    ])


async def _admin_system_message(q):
    await q.message.reply_text(_admin_system_text(),parse_mode="HTML",reply_markup=_admin_system_keyboard())


def _admin_control_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Bonus user mới", callback_data="admin_ctl:new_user_bonus"), InlineKeyboardButton("🎁 Điểm danh", callback_data="admin_ctl:thuong_diem_danh")],
        [InlineKeyboardButton("🏆 Thưởng tuần", callback_data="admin_ctl:thuong_tuan"), InlineKeyboardButton("🛡 Phí xác minh", callback_data="admin_ctl:phi_xac_minh")],
        [InlineKeyboardButton("💰 Rút tối thiểu", callback_data="admin_ctl:rut_toi_thieu"), InlineKeyboardButton("💰 Rút tối đa", callback_data="admin_ctl:rut_toi_da")],
        [InlineKeyboardButton("📅 Rút/ngày", callback_data="admin_ctl:rut_so_lan_ngay"), InlineKeyboardButton("⏱ Cooldown", callback_data="admin_ctl:rut_cooldown_giay")],
        [InlineKeyboardButton("🚨 Ngưỡng Risk", callback_data="admin_ctl:risk_rut_lon"), InlineKeyboardButton("🎬 Hệ số Video", callback_data="admin_ctl:video_reward_multiplier")],
        [InlineKeyboardButton("🔐 Bật/Tắt CAPTCHA", callback_data="admin_ctl:captcha_required"), InlineKeyboardButton("🎯 Bật/Tắt Nhiệm vụ", callback_data="admin_ctl:tasks_enabled")],
        [InlineKeyboardButton("🚧 Bật/Tắt Bảo trì", callback_data="admin_ctl:maintenance_mode")],
        [InlineKeyboardButton("🏆 Chỉnh thông số cấp bậc", callback_data="admin_ctl:rank")],
        [InlineKeyboardButton("⬅️ Quay lại Admin", callback_data="admin_home")],
    ])


def _admin_rank_keyboard():
    buttons=[]
    names=list(CAP_BAC_CONFIG.keys())
    for i in range(0,len(names),2):
        row=[]
        for name in names[i:i+2]:
            cfg=CAP_BAC_CONFIG[name]
            row.append(InlineKeyboardButton(f"{cfg.get('icon','⭐')} {name}", callback_data="admin_ctl_rank:"+str(names.index(name))))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Điều khiển bot", callback_data="admin_ext:control")])
    return InlineKeyboardMarkup(buttons)



def _admin_back_keyboard(target="admin_home"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data=target)]])


def _admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 QUẢN LÝ USER", callback_data="admin_ext:users"),
         InlineKeyboardButton("💸 TÀI CHÍNH", callback_data="admin_ext:finance")],
        [InlineKeyboardButton("⚙️ CẤU HÌNH BOT", callback_data="admin_ext:config"),
         InlineKeyboardButton("🎬 NỘI DUNG", callback_data="admin_ext:content")],
        [InlineKeyboardButton("📢 THÔNG BÁO", callback_data="admin_ext:notify"),
         InlineKeyboardButton("🛡 BẢO MẬT", callback_data="admin_ext:security")],
        [InlineKeyboardButton("📊 BÁO CÁO", callback_data="admin_ext:reports"),
         InlineKeyboardButton("👮 ADMIN / QUYỀN", callback_data="admin_ext:admins")],
        [InlineKeyboardButton("🧰 Điều khiển nhanh", callback_data="admin_ext:control")],
        [InlineKeyboardButton("🚀 ADMIN SMART CENTER", callback_data="admin_v9:dashboard")],
        [InlineKeyboardButton("⬅️ Bảng Admin", callback_data="admin_home")],
    ])


async def _admin_panel_message(q):
    text=(
        "🧰 <b>TRUNG TÂM QUẢN TRỊ ADMIN</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Tất cả công cụ quản trị được chia thành từng nhóm để thao tác nhanh trên điện thoại.\n\n"
        "👥 User • 💸 Tài chính • ⚙️ Cấu hình • 🎬 Nội dung\n"
        "📢 Thông báo • 🛡 Bảo mật • 📊 Báo cáo • 👮 Phân quyền"
    )
    await q.message.reply_text(text, parse_mode="HTML", reply_markup=_admin_panel_keyboard())


async def _admin_user_tools(q):
    with db() as conn:
        total=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        locked=conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0]
        verified=conn.execute("SELECT COUNT(*) FROM users WHERE xac_minh_nguoi_that=1").fetchone()[0]
        today=conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao LIKE ?", (today_vn()+"%",)).fetchone()[0]
    text=(f"👥 <b>QUẢN LÝ USER PRO</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"Tổng: <b>{total:,}</b> • 🔒 Khóa: <b>{locked:,}</b> • 🛡 Xác minh: <b>{verified:,}</b>\n"
          f"🆕 User mới: <b>{today:,}</b>\n\nChọn thao tác:")
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Tìm User",callback_data="admin_tim_nguoi"),InlineKeyboardButton("📋 Danh sách",callback_data="admin_ds_nguoi")],
        [InlineKeyboardButton("🔒 User bị khóa",callback_data="admin_ext:locked_users"),InlineKeyboardButton("🚨 User Risk",callback_data="admin_ext:risk_users")],
        [InlineKeyboardButton("💰 Top số dư",callback_data="admin_ext:top_balance"),InlineKeyboardButton("🆕 User mới",callback_data="admin_ext:new_users")],
        [InlineKeyboardButton("🔄 Reset lượt ngày toàn bộ",callback_data="admin_ext:reset_all_daily")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])
    await q.message.reply_text(text,parse_mode="HTML",reply_markup=kb)


async def _admin_finance_tools(q):
    with db() as conn:
        pending=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        approved=conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved'").fetchone()[0]
        rejected=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='rejected'").fetchone()[0]
    text=(f"💸 <b>TRUNG TÂM TÀI CHÍNH</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"⏳ Chờ duyệt: <b>{pending}</b>\n💰 Đã rút: <b>{approved:,}đ</b>\n❌ Đã từ chối: <b>{rejected}</b>")
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Đơn rút",callback_data="admin_ds_rut"),InlineKeyboardButton("📥 Nạp / cấp",callback_data="admin_ds_nap")],
        [InlineKeyboardButton("🔎 Tìm đơn",callback_data="admin_ext:withdraw_search"),InlineKeyboardButton("📈 Lịch sử rút",callback_data="admin_ext:withdraw_stats")],
        [InlineKeyboardButton("🛡 Đơn Risk",callback_data="admin_ext:fraud"),InlineKeyboardButton("✅ Duyệt rút 2 bước",callback_data="pro_wd_approve_list")],
        [InlineKeyboardButton("💰 Cộng tiền",callback_data="admin_cong_tien"),InlineKeyboardButton("💸 Trừ tiền",callback_data="admin_tru_tien")],
        [InlineKeyboardButton("💰 Cộng TẤT CẢ",callback_data="admin_cong_tat_ca")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])
    await q.message.reply_text(text,parse_mode="HTML",reply_markup=kb)


def _admin_config_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧰 Điều khiển thưởng/rút",callback_data="admin_ext:control")],
        [InlineKeyboardButton("🏆 Cấp bậc",callback_data="admin_ctl:rank"),InlineKeyboardButton("⚙️ Cài đặt PRO",callback_data="admin_ext:settings")],
        [InlineKeyboardButton("🧩 Kênh / Liên hệ / Nội dung",callback_data="admin_ext:system")],
        [InlineKeyboardButton("🎯 Nhiệm vụ",callback_data="admin_ext:tasks"),InlineKeyboardButton("🎉 Sự kiện",callback_data="admin_ext:event")],
        [InlineKeyboardButton("🚧 Bảo trì",callback_data="admin_ctl:maintenance_mode")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])


async def _admin_config_message(q):
    await q.message.reply_text(
        "⚙️ <b>CẤU HÌNH BOT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Admin có thể chỉnh thưởng, hạn mức rút, CAPTCHA, nhiệm vụ, sự kiện, bảo trì và thông số từng cấp.",
        parse_mode="HTML", reply_markup=_admin_config_keyboard())


def _admin_content_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Video & thống kê",callback_data="admin_ext:video_stats"),InlineKeyboardButton("➕ Thêm nhiều Video",callback_data="pro_video_bulk")],
        [InlineKeyboardButton("🎯 Nhiệm vụ",callback_data="admin_ext:tasks"),InlineKeyboardButton("🎁 Gift code",callback_data="admin_ext:gift")],
        [InlineKeyboardButton("🎉 Sự kiện",callback_data="admin_ext:event"),InlineKeyboardButton("⏹ Dừng sự kiện",callback_data="admin_ext:event_stop")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])


async def _admin_notify_message(q):
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Tất cả",callback_data="admin_gui_tb"),InlineKeyboardButton("📢 Đã xác minh",callback_data="pro_broadcast:verified")],
        [InlineKeyboardButton("📢 Chưa xác minh",callback_data="pro_broadcast:unverified"),InlineKeyboardButton("📢 Theo cấp",callback_data="pro_broadcast:rank")],
        [InlineKeyboardButton("⏰ Lịch thông báo",callback_data="admin_ext:schedule")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])
    await q.message.reply_text("📢 <b>TRUNG TÂM THÔNG BÁO</b>\n━━━━━━━━━━━━━━━━━━━━\nGửi thông báo theo nhóm hoặc đặt lịch tự động.",parse_mode="HTML",reply_markup=kb)


def _admin_security_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Anti-fraud",callback_data="admin_ext:fraud"),InlineKeyboardButton("🚨 User Risk",callback_data="admin_ext:risk_users")],
        [InlineKeyboardButton("👮 Admin / quyền",callback_data="admin_ext:admins")],
        [InlineKeyboardButton("🔐 CAPTCHA",callback_data="admin_ctl:captcha_required"),InlineKeyboardButton("🚧 Bảo trì",callback_data="admin_ctl:maintenance_mode")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])


def _admin_reports_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Thống kê PRO",callback_data="admin_ext:stats"),InlineKeyboardButton("📈 Lịch sử rút",callback_data="admin_ext:withdraw_stats")],
        [InlineKeyboardButton("📤 Xuất CSV",callback_data="admin_ext:csv"),InlineKeyboardButton("💾 Backup DB",callback_data="admin_ext:backup")],
        [InlineKeyboardButton("🎬 Video thống kê",callback_data="admin_ext:video_stats")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin",callback_data="admin_ext:panel")],
    ])

async def admin_ext_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data
    if not is_admin(update.effective_user.id): return
    await q.answer()
    if data=="admin_ext:panel":
        await _admin_panel_message(q); return
    if data=="admin_ext:users":
        await _admin_user_tools(q); return
    if data=="admin_ext:finance":
        await _admin_finance_tools(q); return
    if data=="admin_ext:config":
        await _admin_config_message(q); return
    if data=="admin_ext:content":
        await q.message.reply_text("🎬 <b>TRUNG TÂM NỘI DUNG</b>\n━━━━━━━━━━━━━━━━━━━━\nQuản lý video, nhiệm vụ, gift code và sự kiện.",parse_mode="HTML",reply_markup=_admin_content_keyboard()); return
    if data=="admin_ext:notify":
        await _admin_notify_message(q); return
    if data=="admin_ext:security":
        await q.message.reply_text("🛡 <b>TRUNG TÂM BẢO MẬT</b>\n━━━━━━━━━━━━━━━━━━━━\nTheo dõi Risk, khóa user, CAPTCHA, bảo trì và Admin.",parse_mode="HTML",reply_markup=_admin_security_keyboard()); return
    if data=="admin_ext:reports":
        await q.message.reply_text("📊 <b>TRUNG TÂM BÁO CÁO</b>\n━━━━━━━━━━━━━━━━━━━━\nThống kê, lịch sử rút, CSV và backup dữ liệu.",parse_mode="HTML",reply_markup=_admin_reports_keyboard()); return
    if data=="admin_ext:locked_users":
        with db() as conn: rows=conn.execute("SELECT id,ten,username,cap_bac,so_du FROM users WHERE bi_khoa=1 ORDER BY id DESC LIMIT 50").fetchall()
        text="🔒 <b>USER BỊ KHÓA</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"👤 {h(r['ten'] or 'Không tên')} • <code>{r['id']}</code> • {r['so_du']:,}đ" for r in rows) if rows else "🔒 Không có user bị khóa."
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"👤 {str(r['ten'] or 'User')[:18]}",callback_data=f"admin_user:{r['id']}")] for r in rows]+[[InlineKeyboardButton("⬅️ User",callback_data="admin_ext:users")]])
        await q.message.reply_text(text,parse_mode="HTML",reply_markup=kb); return
    if data=="admin_ext:risk_users":
        with db() as conn: rows=conn.execute("SELECT id,ten,risk_score,so_du,bi_khoa FROM users WHERE COALESCE(risk_score,0)>0 ORDER BY risk_score DESC LIMIT 50").fetchall()
        text="🚨 <b>USER CÓ RISK</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"🚨 {h(r['ten'] or 'Không tên')} • <code>{r['id']}</code> • Risk <b>{r['risk_score']}</b> • {r['so_du']:,}đ" for r in rows) if rows else "✅ Chưa có user có Risk."
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"🚨 {str(r['ten'] or 'User')[:18]} | {r['risk_score']}",callback_data=f"admin_user:{r['id']}")] for r in rows]+[[InlineKeyboardButton("⬅️ User",callback_data="admin_ext:users")]])
        await q.message.reply_text(text,parse_mode="HTML",reply_markup=kb); return
    if data=="admin_ext:top_balance":
        with db() as conn: rows=conn.execute("SELECT id,ten,cap_bac,so_du FROM users ORDER BY so_du DESC LIMIT 20").fetchall()
        text="💰 <b>TOP SỐ DƯ</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"#{i+1} • {h(r['ten'] or 'Không tên')} • {r['so_du']:,}đ • {h(r['cap_bac'])}" for i,r in enumerate(rows)) if rows else "Chưa có dữ liệu."
        await q.message.reply_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ User",callback_data="admin_ext:users")]])); return
    if data=="admin_ext:new_users":
        with db() as conn: rows=conn.execute("SELECT id,ten,username,cap_bac,so_du,ngay_vao FROM users ORDER BY id DESC LIMIT 30").fetchall()
        text="🆕 <b>USER MỚI NHẤT</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"👤 {h(r['ten'] or 'Không tên')} • <code>{r['id']}</code> • {h(r['cap_bac'])}\n└ {h(r['ngay_vao'] or '')}" for r in rows) if rows else "Chưa có user."
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"👤 {str(r['ten'] or 'User')[:18]}",callback_data=f"admin_user:{r['id']}")] for r in rows]+[[InlineKeyboardButton("⬅️ User",callback_data="admin_ext:users")]])
        await q.message.reply_text(text,parse_mode="HTML",reply_markup=kb); return
    if data=="admin_ext:reset_all_daily":
        await q.message.reply_text("⚠️ <b>RESET LƯỢT NGÀY TOÀN BỘ</b>\n\nThao tác này đưa video_ngay và dang_xem của tất cả user về 0. Xác nhận?",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Xác nhận",callback_data="admin_ext:reset_all_daily_confirm")],[InlineKeyboardButton("❌ Hủy",callback_data="admin_ext:users")]])); return
    if data=="admin_ext:reset_all_daily_confirm":
        with db() as conn: conn.execute("UPDATE users SET video_ngay=0,dang_xem=0,ngay_reset=?",(today_vn(),))
        admin_log("Reset lượt ngày toàn bộ",None)
        await q.answer("✅ Đã reset lượt ngày toàn bộ.",show_alert=True); await _admin_user_tools(q); return
    if data=="admin_ext:event_stop":
        with db() as conn: conn.execute("UPDATE event_settings SET active=0 WHERE active=1")
        admin_log("Dừng sự kiện",None)
        await q.answer("⏹ Đã dừng sự kiện.",show_alert=True); await q.message.reply_text("⏹ <b>Đã dừng toàn bộ sự kiện đang hoạt động.</b>",parse_mode="HTML",reply_markup=_admin_content_keyboard()); return
    if data=="admin_ext:system":
        await _admin_system_message(q); return
    if data.startswith("admin_sys:"):
        key=data.split(":",1)[1]
        allowed={"support_username","support_hours","announcement_channel","withdraw_announcement_channel","required_channel_1","required_channel_2","required_channel_link_1","required_channel_link_2","video_default_link","verify_bank","verify_account_name","verify_account_number","maintenance_message"}
        if key not in allowed:
            await q.answer("❌ Mục không hợp lệ.",show_alert=True); return
        context.user_data['admin_ext_mode']='system:'+key
        labels={"support_username":"@username hỗ trợ hoặc link Telegram","support_hours":"Khung giờ hỗ trợ","announcement_channel":"@username/ID kênh thông báo","withdraw_announcement_channel":"@username/ID kênh báo rút","required_channel_1":"@username/ID kênh bắt buộc 1","required_channel_2":"@username/ID kênh bắt buộc 2","required_channel_link_1":"Link tham gia kênh 1","required_channel_link_2":"Link tham gia kênh 2","video_default_link":"Link TikTok mặc định","verify_bank":"Tên ngân hàng","verify_account_name":"Tên chủ tài khoản","verify_account_number":"Số tài khoản","maintenance_message":"Nội dung hiện khi bot bảo trì"}
        current=runtime_text(key, "")
        await q.message.reply_text(f"🧩 <b>{h(labels[key])}</b>\n\nHiện tại: <code>{h(current)}</code>\n\nNhập giá trị mới:",parse_mode='HTML',reply_markup=ReplyKeyboardRemove())
        return ADMIN_EXT_INPUT
    if data=="admin_ext:control":
        await q.message.reply_text(_admin_control_text(), parse_mode='HTML', reply_markup=_admin_control_keyboard())
        return
    if data=="admin_ctl:rank":
        await q.message.reply_text("🏆 <b>CHỈNH THÔNG SỐ CẤP BẬC</b>\n\nChọn cấp cần sửa:", parse_mode='HTML', reply_markup=_admin_rank_keyboard())
        return
    if data.startswith("admin_ctl_rank:"):
        try:
            idx=int(data.split(':',1)[1]); name=list(CAP_BAC_CONFIG.keys())[idx]
        except Exception:
            await q.answer("❌ Cấp không hợp lệ.", show_alert=True); return
        cfg=CAP_BAC_CONFIG[name]
        context.user_data['admin_ext_mode']='rank:'+name
        await q.message.reply_text(
            f"🏆 <b>{h(name)}</b>\n\n"
            f"💵 Thưởng/video hiện tại: <b>{cfg['xu_moi_video']:,}đ</b>\n"
            f"📺 Giới hạn/ngày: <b>{cfg['gioi_han_xem_ngay']}</b>\n"
            f"👥 Thưởng giới thiệu: <b>{cfg['thuong_gioi_thieu']:,}đ</b>\n\n"
            "Nhập theo mẫu:\n<code>THUONG_VIDEO|GIOI_HAN_NGAY|THUONG_GIOI_THIEU</code>\n"
            "Ví dụ: <code>25000|150|12000</code>",
            parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        return ADMIN_EXT_INPUT
    if data.startswith("admin_ctl:"):
        key=data.split(':',1)[1]
        boolean_keys={'captcha_required','tasks_enabled','maintenance_mode'}
        if key in boolean_keys:
            current=int(get_setting(key,'0'))
            set_setting(key, 0 if current else 1)
            admin_log('Đổi trạng thái hệ thống',None,f'{key}={0 if current else 1}')
            await q.answer('✅ Đã cập nhật.', show_alert=True)
            await q.message.reply_text(_admin_control_text(), parse_mode='HTML', reply_markup=_admin_control_keyboard())
            return
        if key in {'new_user_bonus','thuong_diem_danh','thuong_tuan','phi_xac_minh','rut_toi_thieu','rut_toi_da','rut_so_lan_ngay','rut_cooldown_giay','risk_rut_lon','video_reward_multiplier'}:
            context.user_data['admin_ext_mode']='setting:'+key
            current=get_setting(key,'0')
            await q.message.reply_text(f"⚙️ Nhập giá trị mới cho <b>{h(key)}</b>.\nGiá trị hiện tại: <code>{h(current)}</code>",parse_mode='HTML',reply_markup=ReplyKeyboardRemove())
            return ADMIN_EXT_INPUT

    if data=="admin_ext:backup":
        with db() as conn:
            tables=["users","withdrawals","deposits","verification_requests","video_links","balance_history","admin_logs","system_settings","daily_checkins","daily_tasks","task_claims","gift_codes","gift_code_uses","daily_spins","video_watch_logs","suspicious_events","scheduled_notifications","admins","event_settings"]
            dump={}
            for table in tables:
                try: dump[table]=[dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
                except Exception: dump[table]=[]
        f=tempfile.NamedTemporaryFile(delete=False,suffix='.json',mode='w',encoding='utf-8')
        json.dump(dump,f,ensure_ascii=False,indent=2,default=str); f.close()
        try: await context.bot.send_document(update.effective_user.id,open(f.name,'rb'),caption="💾 Backup dữ liệu bot")
        finally:
            try: os.unlink(f.name)
            except Exception: pass
        return
    if data=="admin_ext:csv":
        with db() as conn: rows=conn.execute("SELECT id,ten,username,cap_bac,so_du,video_da_xem,gioi_thieu,ref_by,xac_minh_nguoi_that,bi_khoa,ngay_vao FROM users ORDER BY id").fetchall()
        f=tempfile.NamedTemporaryFile(delete=False,suffix='.csv',mode='w',encoding='utf-8-sig',newline='')
        w=csv.writer(f); w.writerow(["id","ten","username","cap_bac","so_du","video_da_xem","gioi_thieu","ref_by","xac_minh","bi_khoa","ngay_vao"])
        for r in rows: w.writerow([r[c] for c in ["id","ten","username","cap_bac","so_du","video_da_xem","gioi_thieu","ref_by","xac_minh_nguoi_that","bi_khoa","ngay_vao"]])
        f.close()
        try: await context.bot.send_document(update.effective_user.id,open(f.name,'rb'),caption=f"📤 CSV {len(rows)} người dùng")
        finally:
            try: os.unlink(f.name)
            except Exception: pass
        return
    if data=="admin_ext:gift":
        context.user_data['admin_ext_mode']='gift'
        await q.message.reply_text("🎁 <b>TẠO GIFT CODE</b>\nGửi: CODE SỐ_TIỀN SỐ_LƯỢT [SỐ_NGÀY]\nVí dụ: TIKTOK2026 50000 100 7",parse_mode='HTML',reply_markup=ReplyKeyboardRemove())
        return ADMIN_EXT_INPUT
    if data=="admin_ext:schedule":
        context.user_data['admin_ext_mode']='schedule'
        await q.message.reply_text("⏰ <b>LỊCH THÔNG BÁO</b>\nGửi: HH:MM|once|all|Nội dung\nhoặc: HH:MM|daily|all|Nội dung\nCó thể target rank: rank:Leader Vàng",parse_mode='HTML',reply_markup=ReplyKeyboardRemove())
        return ADMIN_EXT_INPUT
    if data=="admin_ext:admins":
        with db() as conn: rows=conn.execute("SELECT * FROM admins WHERE active=1 ORDER BY admin_id").fetchall()
        text="👮 <b>QUẢN LÝ ADMIN</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"🆔 <code>{r['admin_id']}</code> • {h(r['role'])}" for r in rows)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Thêm / sửa Admin",callback_data="admin_ext:add_admin")],[InlineKeyboardButton("➖ Xóa Admin",callback_data="admin_ext:del_admin")],[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=kb); return
    if data in ("admin_ext:add_admin","admin_ext:del_admin"):
        context.user_data['admin_ext_mode']='add_admin' if data.endswith('add_admin') else 'del_admin'
        prompt="➕ Gửi: ID role (owner/admin/mod)" if data.endswith('add_admin') else "➖ Gửi ID Admin cần xóa"
        await q.message.reply_text(prompt,reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT
    if data=="admin_ext:tasks":
        with db() as conn: rows=conn.execute("SELECT * FROM daily_tasks ORDER BY period,code").fetchall()
        text="🎯 <b>NHIỆM VỤ HỆ THỐNG</b>\n"+"\n".join(f"{r['code']} • {h(r['name'])} • +{r['reward']:,}đ • {'ON' if r['active'] else 'OFF'}" for r in rows)
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])); return
    if data=="admin_ext:event":
        context.user_data['admin_ext_mode']='event'
        await q.message.reply_text("🎉 Gửi: TÊN|HỆ_SỐ|KẾT_THÚC(dd/mm/YYYY HH:MM:SS)\nVí dụ: Đại Tiệc XU|2|30/09/2026 23:59:59",reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT
    if data=="admin_ext:withdraw_search":
        context.user_data['admin_ext_mode']='withdraw_search'
        await q.message.reply_text("🔎 Nhập mã đơn rút (ví dụ RUT...) hoặc ID người dùng:",reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT
    if data=="admin_ext:withdraw_stats":
        with db() as conn:
            rows=conn.execute("SELECT user_id,COUNT(*) AS c,COALESCE(SUM(so_tien),0) AS total FROM withdrawals WHERE status='approved' GROUP BY user_id ORDER BY total DESC LIMIT 20").fetchall()
        text="📈 <b>TOP LỊCH SỬ RÚT</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"🆔 {r['user_id']} • {r['c']} đơn • {r['total']:,}đ" for r in rows) or "Chưa có dữ liệu."
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])); return
    if data=="admin_ext:fraud":
        with db() as conn:
            rows=conn.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY risk_score DESC, thoi_gian DESC LIMIT 30").fetchall()
        text="🛡 <b>ANTI-FRAUD / ĐƠN RÚT</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"{'🚨' if r.get('risk_score',0)>=50 else '⚠️' if r.get('risk_score',0)>=20 else '✅'} {r['request_id']} • ID {r['user_id']} • {r['so_tien']:,}đ • risk {r.get('risk_score',0)}\n└ {h(r.get('risk_flags') or 'Không có')}" for r in rows) or "Không có đơn đang chờ."
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])); return
    if data=="admin_ext:stats":
        with db() as conn:
            total=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active=conn.execute("SELECT COUNT(*) FROM users WHERE last_active_at IS NOT NULL").fetchone()[0]
            out=conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved'").fetchone()[0]
            pending=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
            video=conn.execute("SELECT COALESCE(SUM(views),0) FROM video_links").fetchone()[0]
            rewards=conn.execute("SELECT COALESCE(SUM(reward_total),0) FROM video_links").fetchone()[0]
        text=f"📊 <b>THỐNG KÊ PRO</b>\n━━━━━━━━━━━━━━━━━━━━\n👥 Tổng user: <b>{total:,}</b>\n🟢 Có hoạt động: <b>{active:,}</b>\n🎬 Lượt xem video: <b>{video:,}</b>\n💰 Thưởng video: <b>{rewards:,}đ</b>\n💸 Đã rút: <b>{out:,}đ</b>\n⏳ Rút chờ duyệt: <b>{pending}</b>"
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])); return
    if data=="admin_ext:video_stats":
        with db() as conn: rows=conn.execute("SELECT id,url,active,views,claimed,reward_total FROM video_links ORDER BY views DESC LIMIT 50").fetchall()
        text="🎬 <b>VIDEO & THỐNG KÊ</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"#{r['id']} • 👁 {r['views']} • 🎁 {r['claimed']} • 💰 {r['reward_total']:,}đ\n└ {h(r['url'])}" for r in rows) or "Chưa có video."
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])); return
    if data=="admin_ext:risk" or data.startswith("admin_ext:risk:"):
        uid=int(data.split(":")[-1])
        with db() as conn:
            rows=conn.execute("SELECT * FROM suspicious_events WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()
        text=f"🚨 <b>RISK USER {uid}</b>\n"+"\n".join(f"{r['created_at']} • +{r['risk']} • {h(r['kind'])}\n└ {h(r['detail'] or '')}" for r in rows) or "Không có cảnh báo."
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Người dùng",callback_data=f"admin_user:{uid}")]])); return
    if data=="admin_ext:settings":
        keys=["rut_toi_thieu","rut_toi_da","rut_so_lan_ngay","rut_cooldown_giay","thuong_diem_danh","thuong_tuan"]
        with db() as conn: vals={k:get_setting(k,"0") for k in keys}
        text="⚙️ <b>CÀI ĐẶT PRO</b>\n━━━━━━━━━━━━━━━━━━━━\n"+"\n".join(f"{k}: <b>{h(vals[k])}</b>" for k in keys)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Rút tối thiểu",callback_data="admin_set2:rut_toi_thieu"),InlineKeyboardButton("💰 Rút tối đa",callback_data="admin_set2:rut_toi_da")],[InlineKeyboardButton("🎁 Điểm danh",callback_data="admin_set2:thuong_diem_danh"),InlineKeyboardButton("📅 Thưởng tuần",callback_data="admin_set2:thuong_tuan")],[InlineKeyboardButton("🆕 Bonus user mới",callback_data="admin_set2:new_user_bonus"),InlineKeyboardButton("🛡 Phí xác minh",callback_data="admin_set2:phi_xac_minh")],[InlineKeyboardButton("🔐 CAPTCHA",callback_data="admin_set2:captcha_required"),InlineKeyboardButton("🎯 Nhiệm vụ",callback_data="admin_set2:tasks_enabled")],[InlineKeyboardButton("⏱ Cooldown",callback_data="admin_set2:rut_cooldown_giay"),InlineKeyboardButton("📅 Lần rút/ngày",callback_data="admin_set2:rut_so_lan_ngay")],[InlineKeyboardButton("⬅️ Admin",callback_data="admin_home")]])
        await q.message.reply_text(text,parse_mode='HTML',reply_markup=kb); return
    if data.startswith("admin_set2:"):
        context.user_data['admin_ext_mode']='setting:'+data.split(":",1)[1]
        await q.message.reply_text("⚙️ Nhập giá trị mới:",reply_markup=ReplyKeyboardRemove()); return ADMIN_EXT_INPUT


async def admin_ext_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    raw=(update.effective_message.text or '').strip(); mode=context.user_data.get('admin_ext_mode','')
    try:
        if mode.startswith('system:'):
            key=mode.split(':',1)[1]
            raw_value=raw.strip()
            if not raw_value or len(raw_value)>1000: raise ValueError
            if key in {"required_channel_1","required_channel_2","announcement_channel","withdraw_announcement_channel"} and not (raw_value.startswith('@') or raw_value.startswith('-100') or raw_value.startswith('https://t.me/')): raise ValueError
            if key in {"required_channel_link_1","required_channel_link_2","video_default_link"} and not raw_value.startswith(('http://','https://')): raise ValueError
            set_setting(key, raw_value)
            admin_log('Đổi cấu hình hệ thống',None,f'{key}={raw_value}')
            context.user_data.pop('admin_ext_mode',None)
            await update.message.reply_text('✅ <b>Đã cập nhật.</b>\n\n'+_admin_system_text(),parse_mode='HTML',reply_markup=_admin_system_keyboard())
            return ConversationHandler.END
        if mode.startswith('setting:'):
            key=mode.split(':',1)[1]
            raw_value=raw.replace(',','').replace('đ','').strip()
            if key=='video_reward_multiplier':
                value=float(raw_value)
                if value < 0.1 or value > 20: raise ValueError
                set_setting(key, value)
            else:
                value=int(raw_value)
                if value < 0: raise ValueError
                set_setting(key, value)
            admin_log('Đổi cài đặt điều khiển bot',None,f'{key}={value}')
            context.user_data.pop('admin_ext_mode',None)
            await update.message.reply_text('✅ <b>Đã cập nhật cài đặt.</b>\n\n'+_admin_control_text(),parse_mode='HTML',reply_markup=_admin_control_keyboard())
            return ConversationHandler.END
        if mode.startswith('rank:'):
            name=mode.split(':',1)[1]
            parts=[x.strip() for x in raw.split('|')]
            if len(parts)!=3: raise ValueError
            reward=int(parts[0].replace(',','').replace('.','')); limit=int(parts[1]); ref=int(parts[2].replace(',','').replace('.',''))
            if reward<0 or limit<0 or ref<0 or name not in CAP_BAC_CONFIG: raise ValueError
            CAP_BAC_CONFIG[name]['xu_moi_video']=reward
            CAP_BAC_CONFIG[name]['gioi_han_xem_ngay']=limit
            CAP_BAC_CONFIG[name]['thuong_gioi_thieu']=ref
            set_setting('rank_cfg:'+name, json.dumps(CAP_BAC_CONFIG[name],ensure_ascii=False))
            admin_log('Sửa thông số cấp bậc',None,f'{name}|{reward}|{limit}|{ref}')
            context.user_data.pop('admin_ext_mode',None)
            await update.message.reply_text(f'✅ Đã cập nhật <b>{h(name)}</b>.\n💵 {reward:,}đ/video\n📺 {limit} video/ngày\n👥 {ref:,}đ/giới thiệu',parse_mode='HTML',reply_markup=_admin_control_keyboard())
            return ConversationHandler.END

        if mode=='video_bulk':
            urls=[x.strip() for x in raw.splitlines() if x.strip()]
            urls=[x for x in urls if 'tiktok.com/' in x]
            added=0
            with db() as conn:
                for url in urls:
                    if not conn.execute('SELECT 1 FROM video_links WHERE url=?',(url,)).fetchone():
                        conn.execute("INSERT INTO video_links(url,active,views,claimed,reward_total,category,created_at) VALUES (?,1,0,0,0,'default',?)",(url,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
                        added+=1
            await update.message.reply_text(f'✅ Thêm {added} video thành công.',reply_markup=menu_chinh(update.effective_user.id)); return ConversationHandler.END
        if mode.startswith('broadcast:'):
            target=mode.split(':',1)[1]
            with db() as conn:
                if target=='verified': rows=conn.execute('SELECT id FROM users WHERE xac_minh_nguoi_that=1 AND bi_khoa=0').fetchall()
                elif target=='unverified': rows=conn.execute('SELECT id FROM users WHERE xac_minh_nguoi_that=0 AND bi_khoa=0').fetchall()
                else: rows=conn.execute('SELECT id FROM users WHERE bi_khoa=0').fetchall()
            sent=0
            for r in rows:
                try:
                    await context.bot.send_message(r['id'],f'📢 <b>THÔNG BÁO</b>\n\n{h(raw)}',parse_mode='HTML'); sent+=1
                except Exception: pass
            await update.message.reply_text(f'✅ Đã gửi {sent}/{len(rows)} người dùng.',reply_markup=menu_chinh(update.effective_user.id)); return ConversationHandler.END
        if mode=='gift':
            parts=raw.split();
            if len(parts)<3: raise ValueError
            code=parts[0].upper(); reward=int(parts[1].replace(',','').replace('.','')); maxuses=int(parts[2]); days=int(parts[3]) if len(parts)>3 else 0
            expires=(now_vn()+timedelta(days=days)).strftime('%d/%m/%Y %H:%M:%S') if days>0 else None
            with db() as conn: conn.execute("INSERT INTO gift_codes(code,reward,max_uses,expires_at,created_at) VALUES (?,?,?,?,?)",(code,reward,maxuses,expires,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
            await update.message.reply_text(f"✅ Đã tạo gift code <code>{h(code)}</code> • +{reward:,}đ • {maxuses} lượt",parse_mode='HTML',reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode=='schedule':
            parts=raw.split('|',3)
            if len(parts)!=4: raise ValueError
            hhmm,freq,target,content=parts
            datetime.strptime(hhmm,'%H:%M')
            if freq not in ('once','daily'): raise ValueError
            with db() as conn: conn.execute("INSERT INTO scheduled_notifications(send_time,frequency,target,content,created_at) VALUES (?,?,?,?,?)",(hhmm,freq,target,content,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
            await update.message.reply_text("✅ Đã tạo lịch thông báo.",reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode=='withdraw_search':
            with db() as conn:
                if raw.isdigit():
                    rows=conn.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY thoi_gian DESC LIMIT 20",(int(raw),)).fetchall()
                else:
                    rows=conn.execute("SELECT * FROM withdrawals WHERE request_id LIKE ? ORDER BY thoi_gian DESC LIMIT 20",('%'+raw+'%',)).fetchall()
            text='🔎 <b>KẾT QUẢ ĐƠN RÚT</b>\n━━━━━━━━━━━━━━━━━━━━\n'+"\n".join(f"{r['request_id']} • ID {r['user_id']} • {r['so_tien']:,}đ • {r['status']} • risk {r.get('risk_score',0)}" for r in rows) or 'Không tìm thấy.'
            await update.message.reply_text(text,parse_mode='HTML',reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode=='event':
            name,multi,end=raw.split('|',2); multi=float(multi)
            with db() as conn:
                conn.execute("UPDATE event_settings SET active=0")
                conn.execute("INSERT INTO event_settings(name,multiplier,ends_at,active) VALUES (?,?,?,1)",(name,multi,end))
            await update.message.reply_text("✅ Sự kiện đã bật.",reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode=='add_admin':
            parts=raw.split(); uid=int(parts[0]); role=parts[1] if len(parts)>1 else 'admin'
            if uid==ADMIN_ID: raise ValueError
            with db() as conn: conn.execute("INSERT INTO admins(admin_id,role,active,created_at) VALUES (?,?,1,?) ON CONFLICT(admin_id) DO UPDATE SET role=excluded.role,active=1",(uid,role,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
            await update.message.reply_text(f"✅ Đã thêm Admin <code>{uid}</code> ({h(role)}).",parse_mode='HTML',reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode=='del_admin':
            uid=int(raw)
            if uid==ADMIN_ID: raise ValueError
            with db() as conn: conn.execute("UPDATE admins SET active=0 WHERE admin_id=?",(uid,))
            await update.message.reply_text(f"✅ Đã vô hiệu hóa Admin <code>{uid}</code>.",parse_mode='HTML',reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
        if mode.startswith('setting:'):
            key=mode.split(':',1)[1]; value=int(raw.replace(',','').replace('.',''))
            if value<0: raise ValueError
            set_setting(key,value)
            await update.message.reply_text("✅ Đã cập nhật cài đặt.",reply_markup=menu_chinh(ADMIN_ID)); return ConversationHandler.END
    except Exception:
        await update.message.reply_text("❌ Dữ liệu không hợp lệ. Vui lòng nhập lại đúng định dạng.")
        return ADMIN_EXT_INPUT
    return ConversationHandler.END


async def job_process_scheduled_notifications(context: ContextTypes.DEFAULT_TYPE):
    now=now_vn(); hhmm=now.strftime('%H:%M'); today=now.strftime('%d/%m/%Y')
    try:
        with db() as conn: rows=conn.execute("SELECT * FROM scheduled_notifications WHERE active=1 AND send_time=?",(hhmm,)).fetchall()
    except Exception:
        LOGGER.exception("Scheduled notification query failed; attempting schema self-heal")
        try:
            _v172_create_critical_tables(); _v172_add_columns()
        except Exception: LOGGER.exception("Scheduled notification self-heal failed")
        return
    for row in rows:
        if row['last_sent_date']==today: continue
        target=row['target']; users=[]
        with db() as conn:
            if target=='all': users=conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()
            elif target=='locked': users=conn.execute("SELECT id FROM users WHERE bi_khoa=1").fetchall()
            elif target.startswith('rank:'): users=conn.execute("SELECT id FROM users WHERE cap_bac=? AND bi_khoa=0",(target[5:],)).fetchall()
            else: users=conn.execute("SELECT id FROM users WHERE bi_khoa=0").fetchall()
        for u in users:
            try: await context.bot.send_message(u['id'],f"📢 <b>THÔNG BÁO HỆ THỐNG</b>\n\n{h(row['content'])}",parse_mode='HTML')
            except Exception: pass
        with db() as conn:
            conn.execute("UPDATE scheduled_notifications SET last_sent_date=?,active=? WHERE id=?",(today,1 if row['frequency']=='daily' else 0,row['id']))


def _withdraw_risk(tai_khoan, user_id, so_tien):
    normalized=' '.join((tai_khoan or '').upper().split())
    import hashlib
    ah=hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    score=0; flags=[]
    with db() as conn:
        shared=conn.execute("SELECT COUNT(DISTINCT user_id) FROM withdrawals WHERE account_hash=? AND user_id<>?",(ah,user_id)).fetchone()[0]
        if shared: score+=40; flags.append(f"Tài khoản đã dùng bởi {shared} user")
        recent=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND thoi_gian LIKE ?",(user_id,now_vn().strftime('%d/%m/%Y')+'%')).fetchone()[0]
        if recent>=2: score+=20; flags.append('Nhiều lần rút trong ngày')
    if so_tien>=int(get_setting('risk_rut_lon',1000000)): score+=20; flags.append('Đơn rút lớn')
    flag_text='; '.join(flags) if flags else 'Bình thường'
    if score>0:
        try:
            with db() as conn:
                conn.execute("UPDATE users SET risk_score=COALESCE(risk_score,0)+? WHERE id=?", (score, user_id))
                conn.execute("INSERT INTO suspicious_events(user_id,kind,detail,risk,created_at) VALUES (?,?,?,?,?)", (user_id,'withdrawal',flag_text,score,now_vn().strftime('%d/%m/%Y %H:%M:%S')))
        except Exception:
            pass
    return score,ah,flag_text


# ===================== ADMIN V9: SMART CONTROL CENTER =====================
def _admin_v9_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard LIVE", callback_data="admin_v9:dashboard"), InlineKeyboardButton("❤️ Sức khỏe Bot", callback_data="admin_v9:health")],
        [InlineKeyboardButton("👥 Hoạt động User", callback_data="admin_v9:activity"), InlineKeyboardButton("💸 Hàng đợi Rút", callback_data="admin_v9:withdraw_queue")],
        [InlineKeyboardButton("🏆 Top User", callback_data="admin_v9:top_users"), InlineKeyboardButton("🎬 Top Video", callback_data="admin_v9:top_videos")],
        [InlineKeyboardButton("📜 Nhật ký Admin", callback_data="admin_v9:admin_logs"), InlineKeyboardButton("🧹 Bảo trì dữ liệu", callback_data="admin_v9:data_tools")],
        [InlineKeyboardButton("📢 Soạn thông báo", callback_data="admin_v9:broadcast_start"), InlineKeyboardButton("🔄 Làm mới", callback_data="admin_v9:dashboard")],
        [InlineKeyboardButton("⬅️ Trung tâm Admin", callback_data="admin_ext:panel")],
    ])

def _admin_v9_dashboard_text():
    with db() as conn:
        users=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active=conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=0").fetchone()[0]
        locked=conn.execute("SELECT COUNT(*) FROM users WHERE bi_khoa=1").fetchone()[0]
        verified=conn.execute("SELECT COUNT(*) FROM users WHERE xac_minh_nguoi_that=1").fetchone()[0]
        balance=conn.execute("SELECT COALESCE(SUM(so_du),0) FROM users").fetchone()[0]
        pending=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        approved=conn.execute("SELECT COALESCE(SUM(so_tien),0) FROM withdrawals WHERE status='approved'").fetchone()[0]
        today=now_vn().strftime('%d/%m/%Y')
        new_today=conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao LIKE ?",(today+'%',)).fetchone()[0]
        video=conn.execute("SELECT COUNT(*) FROM video_links WHERE COALESCE(active,1)=1").fetchone()[0]
        risk=conn.execute("SELECT COUNT(*) FROM users WHERE COALESCE(risk_score,0)>0").fetchone()[0]
    return ("📊 <b>DASHBOARD LIVE</b>\n━━━━━━━━━━━━━━━━━━━━\n" f"👥 Người dùng: <b>{users:,}</b> | 🟢 Hoạt động: <b>{active:,}</b>\n" f"🔒 Bị khóa: <b>{locked:,}</b> | 🛡 Xác minh: <b>{verified:,}</b>\n" f"🆕 User hôm nay: <b>{new_today:,}</b>\n\n" f"💰 Tổng số dư hệ thống: <b>{balance:,}đ</b>\n" f"💸 Chờ rút: <b>{pending:,}</b>\n" f"✅ Tổng đã duyệt: <b>{approved:,}đ</b>\n" f"🚨 User có Risk: <b>{risk:,}</b>\n" f"🎬 Video đang hoạt động: <b>{video:,}</b>\n\n" f"🕒 Cập nhật: <code>{now_vn().strftime('%H:%M:%S %d/%m/%Y')}</code>")

async def _admin_v9_message(q, mode='dashboard'):
    await q.answer()
    if mode=='dashboard': text=_admin_v9_dashboard_text()
    elif mode=='health':
        with db() as conn:
            checks=[]
            for table in ('users','withdrawals','video_links','system_settings','admin_logs'):
                try: checks.append(f"✅ {table}: <b>{conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:,}</b>")
                except Exception as e: checks.append(f"❌ {table}: {h(str(e)[:80])}")
        text="❤️ <b>SỨC KHỎE HỆ THỐNG</b>\n━━━━━━━━━━━━━━━━━━━━\n"+'\n'.join(checks)+"\n\n✅ DB truy vấn thành công."
    elif mode=='activity':
        with db() as conn: rows=conn.execute("SELECT id,ten,last_active_at,so_du,cap_bac FROM users WHERE last_active_at IS NOT NULL ORDER BY last_active_at DESC LIMIT 12").fetchall()
        lines=["👥 <b>USER HOẠT ĐỘNG GẦN ĐÂY</b>","━━━━━━━━━━━━━━━━━━━━"]
        for r in rows: lines.append(f"• <code>{r['id']}</code> • {h(r['ten'] or 'User')} • {h(r['cap_bac'] or '')}\n  🕒 {h(r['last_active_at'] or '-')} • 💰 {int(r['so_du'] or 0):,}đ")
        text='\n'.join(lines) if rows else 'Chưa có dữ liệu hoạt động.'
    elif mode=='withdraw_queue':
        with db() as conn: rows=conn.execute("SELECT request_id,user_id,so_tien,status,thoi_gian,risk_score FROM withdrawals ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, thoi_gian DESC LIMIT 15").fetchall()
        lines=["💸 <b>HÀNG ĐỢI RÚT TIỀN</b>","━━━━━━━━━━━━━━━━━━━━"]
        for r in rows: lines.append(f"• <code>{h(r['request_id'])}</code> | ID {r['user_id']} | <b>{int(r['so_tien'] or 0):,}đ</b> | {h(r['status'])} | Risk {int(r['risk_score'] or 0)}")
        text='\n'.join(lines) if rows else 'Không có đơn.'
    elif mode=='top_users':
        with db() as conn: rows=conn.execute("SELECT id,ten,so_du,gioi_thieu,cap_bac FROM users ORDER BY so_du DESC LIMIT 15").fetchall()
        lines=["🏆 <b>TOP USER THEO SỐ DƯ</b>","━━━━━━━━━━━━━━━━━━━━"]
        for i,r in enumerate(rows,1): lines.append(f"{i}. {h(r['ten'] or 'User')} — <b>{int(r['so_du'] or 0):,}đ</b> | GT {int(r['gioi_thieu'] or 0)} | {h(r['cap_bac'] or '')}")
        text='\n'.join(lines) if rows else 'Chưa có dữ liệu.'
    elif mode=='top_videos':
        with db() as conn:
            try: rows=conn.execute("SELECT video_id,url,COUNT(*) AS c FROM video_watch_logs GROUP BY video_id,url ORDER BY c DESC LIMIT 15").fetchall()
            except Exception: rows=[]
        lines=["🎬 <b>TOP VIDEO THEO LƯỢT XEM</b>","━━━━━━━━━━━━━━━━━━━━"]
        for i,r in enumerate(rows,1): lines.append(f"{i}. Video <code>{h(str(r['video_id']))}</code> • <b>{int(r['c'])}</b> lượt\n   {h((r['url'] or '')[:90])}")
        text='\n'.join(lines) if rows else 'Chưa có dữ liệu lượt xem.'
    elif mode=='admin_logs':
        with db() as conn: rows=conn.execute("SELECT admin_id,action,target_user_id,detail,created_at FROM admin_logs ORDER BY created_at DESC LIMIT 20").fetchall()
        lines=["📜 <b>NHẬT KÝ ADMIN</b>","━━━━━━━━━━━━━━━━━━━━"]
        for r in rows: lines.append(f"• Admin <code>{r['admin_id']}</code> → {h(r['action'] or '')} | User {r['target_user_id'] or '-'}\n  {h((r['detail'] or '')[:120])} • {h(r['created_at'] or '')}")
        text='\n'.join(lines) if rows else 'Chưa có nhật ký.'
    elif mode=='data_tools':
        text="🧹 <b>BẢO TRÌ DỮ LIỆU</b>\n━━━━━━━━━━━━━━━━━━━━\n• Kiểm tra bảng DB\n• Kiểm tra user Risk\n• Theo dõi hàng đợi rút\n• Theo dõi hoạt động User\n\n⚠️ Không có nút xóa hàng loạt để tránh mất dữ liệu ngoài ý muốn."
    else: text="📢 <b>SOẠN THÔNG BÁO</b>\n\nBấm nút bên dưới để chọn nhóm người nhận, xem trước và xác nhận trước khi gửi."
    await q.message.reply_text(text,parse_mode='HTML',reply_markup=_admin_v9_keyboard())


async def admin_v9_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.callback_query.answer('Không có quyền.', show_alert=True)
        return ConversationHandler.END
    q=update.callback_query
    await q.answer()
    context.user_data.pop('admin_v9_broadcast', None)
    await q.message.reply_text(
        '📢 <b>SOẠN THÔNG BÁO PRO</b>\n━━━━━━━━━━━━━━━━━━━━\n'
        'Chọn nhóm người nhận:', parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('👥 Tất cả User', callback_data='admin_v9:bcast_target:all')],
            [InlineKeyboardButton('🛡 Đã xác minh', callback_data='admin_v9:bcast_target:verified'),
             InlineKeyboardButton('🔓 Chưa xác minh', callback_data='admin_v9:bcast_target:unverified')],
            [InlineKeyboardButton('🏆 Theo cấp', callback_data='admin_v9:bcast_target:rank')],
            [InlineKeyboardButton('❌ Hủy', callback_data='admin_v9:bcast_cancel')],
        ])
    )
    return ADMIN_V9_BROADCAST_INPUT

async def admin_v9_broadcast_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not is_admin(update.effective_user.id):
        await q.answer('Không có quyền.', show_alert=True); return ConversationHandler.END
    await q.answer()
    target=q.data.rsplit(':',1)[1]
    context.user_data['admin_v9_broadcast_target']=target
    if target=='rank':
        context.user_data['admin_v9_broadcast_wait_rank']=True
        await q.message.reply_text(
            '🏆 Nhập <b>tên cấp</b> chính xác (ví dụ: Thành viên):',
            parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
    else:
        await q.message.reply_text(
            '✍️ Nhập nội dung thông báo.\n\n'
            'Bot sẽ gửi bản xem trước để bạn xác nhận trước khi gửi hàng loạt.',
            reply_markup=ReplyKeyboardRemove())
    return ADMIN_V9_BROADCAST_INPUT

async def admin_v9_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    raw=(update.effective_message.text or '').strip()
    if not raw or len(raw)>3500:
        await update.message.reply_text('❌ Nội dung phải từ 1 đến 3500 ký tự. Nhập lại:')
        return ADMIN_V9_BROADCAST_INPUT
    if context.user_data.get('admin_v9_broadcast_wait_rank'):
        if raw not in CAP_BAC_CONFIG:
            await update.message.reply_text('❌ Không tìm thấy cấp này. Hãy nhập đúng tên cấp trong hệ thống:')
            return ADMIN_V9_BROADCAST_INPUT
        context.user_data['admin_v9_broadcast_target']='rank:'+raw
        context.user_data.pop('admin_v9_broadcast_wait_rank',None)
        await update.message.reply_text('✍️ Nhập nội dung thông báo:', reply_markup=ReplyKeyboardRemove())
        return ADMIN_V9_BROADCAST_INPUT

    target=context.user_data.get('admin_v9_broadcast_target','all')
    with db() as conn:
        if target=='verified':
            count=conn.execute('SELECT COUNT(*) FROM users WHERE xac_minh_nguoi_that=1 AND bi_khoa=0').fetchone()[0]
        elif target=='unverified':
            count=conn.execute('SELECT COUNT(*) FROM users WHERE xac_minh_nguoi_that=0 AND bi_khoa=0').fetchone()[0]
        elif target.startswith('rank:'):
            count=conn.execute('SELECT COUNT(*) FROM users WHERE cap_bac=? AND bi_khoa=0',(target[5:],)).fetchone()[0]
        else:
            count=conn.execute('SELECT COUNT(*) FROM users WHERE bi_khoa=0').fetchone()[0]
    context.user_data['admin_v9_broadcast_content']=raw
    context.user_data['admin_v9_broadcast_target']=target
    target_label={'all':'Tất cả User','verified':'Đã xác minh','unverified':'Chưa xác minh'}.get(target, target.replace('rank:','Cấp: '))
    await update.message.reply_text(
        f'📢 <b>XÁC NHẬN GỬI THÔNG BÁO</b>\n━━━━━━━━━━━━━━━━━━━━\n'
        f'👥 Đối tượng: <b>{h(target_label)}</b>\n'
        f'📊 Số người dự kiến: <b>{count:,}</b>\n\n'
        f'📝 <b>Nội dung:</b>\n{h(raw)}',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ XÁC NHẬN GỬI', callback_data='admin_v9:bcast_confirm'),
             InlineKeyboardButton('✏️ Sửa', callback_data='admin_v9:bcast_edit')],
            [InlineKeyboardButton('❌ Hủy', callback_data='admin_v9:bcast_cancel')],
        ])
    )
    return ADMIN_V9_BROADCAST_INPUT

async def admin_v9_broadcast_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not is_admin(update.effective_user.id):
        await q.answer('Không có quyền.', show_alert=True); return ConversationHandler.END
    await q.answer()
    action=q.data.rsplit(':',1)[1]
    if action=='cancel':
        context.user_data.pop('admin_v9_broadcast',None)
        for k in ('admin_v9_broadcast_target','admin_v9_broadcast_content','admin_v9_broadcast_wait_rank'):
            context.user_data.pop(k,None)
        await q.message.reply_text('❌ Đã hủy soạn thông báo.', reply_markup=menu_chinh(update.effective_user.id))
        return ConversationHandler.END
    if action=='edit':
        await q.message.reply_text('✏️ Nhập lại nội dung thông báo:', reply_markup=ReplyKeyboardRemove())
        return ADMIN_V9_BROADCAST_INPUT
    target=context.user_data.get('admin_v9_broadcast_target','all')
    content=context.user_data.get('admin_v9_broadcast_content','').strip()
    if not content:
        await q.message.reply_text('❌ Chưa có nội dung để gửi.')
        return ADMIN_V9_BROADCAST_INPUT
    with db() as conn:
        if target=='verified': rows=conn.execute('SELECT id FROM users WHERE xac_minh_nguoi_that=1 AND bi_khoa=0').fetchall()
        elif target=='unverified': rows=conn.execute('SELECT id FROM users WHERE xac_minh_nguoi_that=0 AND bi_khoa=0').fetchall()
        elif target.startswith('rank:'): rows=conn.execute('SELECT id FROM users WHERE cap_bac=? AND bi_khoa=0',(target[5:],)).fetchall()
        else: rows=conn.execute('SELECT id FROM users WHERE bi_khoa=0').fetchall()
    sent=failed=0
    await q.message.reply_text(f'🚀 Bắt đầu gửi cho <b>{len(rows):,}</b> người...',parse_mode='HTML')
    for r in rows:
        try:
            await context.bot.send_message(r['id'], f'📢 <b>THÔNG BÁO</b>\n\n{h(content)}', parse_mode='HTML')
            sent += 1
        except Exception:
            failed += 1
        if (sent+failed) % 20 == 0:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.05)
    admin_log('Gửi thông báo PRO',None,f'target={target}|sent={sent}|failed={failed}')
    for k in ('admin_v9_broadcast_target','admin_v9_broadcast_content','admin_v9_broadcast_wait_rank'):
        context.user_data.pop(k,None)
    await q.message.reply_text(
        f'✅ <b>ĐÃ GỬI XONG</b>\n\n📨 Thành công: <b>{sent:,}</b>\n❌ Lỗi: <b>{failed:,}</b>',
        parse_mode='HTML', reply_markup=_admin_v9_keyboard())
    return ConversationHandler.END

async def admin_v9_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not is_admin(update.effective_user.id):
        await q.answer('Không có quyền.', show_alert=True); return
    await _admin_v9_message(q, q.data.split(':',1)[1] if ':' in q.data else 'dashboard')

async def extra_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data
    if data.startswith('rank_page:'): return await rank_page_callback(update,context)
    if data.startswith('rank_info:'): return await rank_info_callback(update,context)
    if data=='rank_noop': return await rank_noop(update,context)
    if data=='rank_back':
        await q.answer(); await q.message.reply_text('👑 Bấm "👑 Nâng Cấp Bậc" để xem các gói.',reply_markup=menu_chinh(update.effective_user.id)); return
    if data.startswith('task_claim:') or data=='tasks_refresh': return await task_callback(update,context)
    if data=='wheel_spin': return await wheel_spin_callback(update,context)
    if data.startswith('admin_video_toggle:'):
        q=update.callback_query
        if not is_admin(update.effective_user.id): return
        await q.answer()
        vid=int(data.split(':')[1])
        with db() as conn:
            conn.execute('UPDATE video_links SET active=CASE WHEN COALESCE(active,1)=1 THEN 0 ELSE 1 END WHERE id=?',(vid,))
        await _admin_video_list_message(q)
        return
    if data.startswith('admin_ctl:') or data.startswith('admin_ctl_rank:'):
        return await admin_ext_callback(update,context)
    if data.startswith('admin_ext:') or data.startswith('admin_set2:'): return await admin_ext_callback(update,context)


# Ghi nhận hoạt động của user mà không ảnh hưởng luồng cũ.
_ORIGINAL_START_V3 = start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=await _ORIGINAL_START_V3(update,context)
    try:
        with db() as conn: conn.execute("UPDATE users SET last_active_at=? WHERE id=?",(now_vn().strftime('%d/%m/%Y %H:%M:%S'),update.effective_user.id))
    except Exception: pass
    return u


def menu_chinh(user_id=None):
    rows=[
        [KeyboardButton('👤 Hồ Sơ'),KeyboardButton('🔍 Xem TikTok')],
        [KeyboardButton('👥 Cấp Giới Thiệu'),KeyboardButton('👑 Nâng Cấp Bậc')],
        [KeyboardButton('💳 Nạp Tiền'),KeyboardButton('💰 Rút Tiền')],
        [KeyboardButton('🛒 Dịch Vụ TikTok'),KeyboardButton('🎯 Nhiệm Vụ')],
        [KeyboardButton('🎁 Điểm Danh'),KeyboardButton('🏆 BXH')],
        [KeyboardButton('🎡 Vòng Quay'),KeyboardButton('🎁 Đổi Quà')],
        [KeyboardButton('🎉 Sự Kiện'),KeyboardButton('🎧 Hỗ Trợ')],
        [KeyboardButton('🔐 Nhập CaptCha')],
    ]
    if is_admin(user_id or 0):
        rows.append([KeyboardButton('🎛 QUẢN LÝ ADMIN')])
    return ReplyKeyboardMarkup(rows,resize_keyboard=True)


async def admin_xu_ly_them_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    raw=update.effective_message.text or ''
    urls=[]
    for line in raw.replace(',', '\n').splitlines():
        url=line.strip()
        if url and url.startswith('https://') and 'tiktok.com' in url.lower(): urls.append(url)
    urls=list(dict.fromkeys(urls))
    if not urls:
        await update.effective_message.reply_text('❌ Không có link TikTok hợp lệ. Gửi mỗi dòng 1 link, có thể gửi nhiều link cùng lúc.')
        return ADMIN_VIDEO_ADD
    added=0
    with db() as conn:
        for url in urls:
            try:
                conn.execute('INSERT INTO video_links(url,created_at,active) VALUES (?,?,1)',(url,now_vn().strftime('%d/%m/%Y %H:%M')))
                added+=1
            except Exception: pass
    await update.effective_message.reply_text(f'✅ Đã thêm <b>{added}</b> video mới / {len(urls)} link.',parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🎬 Quản lý Video',callback_data='admin_video')]]))
    return ConversationHandler.END


def _admin_video_keyboard(rows=None):
    buttons=[[InlineKeyboardButton('➕ Thêm video',callback_data='admin_video_add')],[InlineKeyboardButton('📊 Thống kê video',callback_data='admin_ext:video_stats')]]
    if rows:
        for row in rows[:40]:
            status='🟢' if row.get('active',1) else '🔴'
            buttons.append([InlineKeyboardButton(f"{status} #{row['id']} • 👁{row.get('views',0)}",callback_data=f"admin_video_toggle:{row['id']}")])
            buttons.append([InlineKeyboardButton('🗑 Xóa',callback_data=f"admin_video_del:{row['id']}")])
    buttons.append([InlineKeyboardButton('⬅️ Admin',callback_data='admin_home')])
    return InlineKeyboardMarkup(buttons)


async def _admin_video_list_message(query):
    with db() as conn: rows=conn.execute('SELECT * FROM video_links ORDER BY id DESC LIMIT 100').fetchall()
    text='🎬 <b>QUẢN LÝ VIDEO</b>\n━━━━━━━━━━━━━━━━━━━━\n'+(f'Tổng: <b>{len(rows)}</b> video\n\n' if rows else 'Chưa có video.\n')
    if rows:
        text += '\n'.join(f"#{r['id']} • {'🟢 hoạt động' if r.get('active',1) else '🔴 ẩn'} • 👁 {r.get('views',0)} • 🎁 {r.get('claimed',0)}\n└ {h(r['url'])}" for r in rows)
    await query.message.reply_text(text,parse_mode='HTML',reply_markup=_admin_video_keyboard(rows))


# ============================================================
# V13 UPGRADE: TÁCH CẤP GIỚI THIỆU / CẤP NẠP + NẠP TIỀN + DỊCH VỤ TIKTOK
# ============================================================
CAP_NAP_AMOUNT = {
    "Thành viên": 0,
    "Leader Bạc I": 125_000,
    "Leader Vàng I": 250_000,
    "Leader Bạch Kim I": 1_000_000,
    "Leader Kim Cương I": 2_000_000,
    "Leader Titan I": 5_000_000,
    "Leader Cao Thủ I": 10_000_000,
    "Leader Đại Cao Thủ I": 25_000_000,
    "Leader Huyền Thoại I": 50_000_000,
    "Leader Chí Tôn": 100_000_000,
}

NAP_TIEN_AMOUNT = 40
NAP_TIEN_RECEIPT = 41
DV_TIKTOK_INPUT = 50

SOCIAL_SERVICE_DEFAULTS = [
    ("followers", "👥 Tăng người theo dõi TikTok", "Gói theo dõi theo số lượng đặt; Admin xử lý thủ công/qua nhà cung cấp được phép.", 120, 100, 100000),
    ("likes", "❤️ Tăng tim video TikTok", "Gói lượt thích theo số lượng đặt; Admin xử lý thủ công/qua nhà cung cấp được phép.", 80, 100, 100000),
    ("views", "👀 Tăng người xem video TikTok", "Gói lượt xem theo số lượng đặt; Admin xử lý thủ công/qua nhà cung cấp được phép.", 40, 500, 1000000),
    ("audit", "🔎 Kiểm tra tài khoản TikTok", "Kiểm tra tình trạng tài khoản và đề xuất cải thiện.", 15000, 1, 1),
    ("content", "✍️ Tư vấn nội dung TikTok", "Tư vấn chủ đề, lịch đăng và hướng phát triển nội dung.", 50000, 1, 10),
    ("edit", "🎬 Biên tập video TikTok", "Nhận yêu cầu biên tập/cắt ghép video theo nội dung hợp lệ.", 80000, 1, 20),
]


def _v13_rank_by_deposit(total):
    total = int(total or 0)
    chosen = "Thành viên"
    for name, amount in sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1]):
        if total >= amount:
            chosen = name
    return chosen


def _v13_rank_by_referral(total):
    return cap_bac_tu_so_nguoi(int(total or 0))


async def _v13_init_db_migration():
    """Migration V13, chạy sau init_db cũ để không phá DB đang chạy."""
    with db() as conn:
        _safe_add_column(conn, "users", "cap_gioi_thieu", "TEXT NOT NULL DEFAULT 'Thành viên'")
        _safe_add_column(conn, "users", "cap_nap", "TEXT NOT NULL DEFAULT 'Thành viên'")
        _safe_add_column(conn, "users", "total_deposited", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_column(conn, "deposits", "deposit_type", "TEXT NOT NULL DEFAULT 'rank'")
        _safe_add_column(conn, "deposits", "approved_by", "BIGINT")
        _safe_add_column(conn, "deposits", "approved_at", "TEXT")
        serial = "BIGSERIAL" if DATABASE_URL else "INTEGER"
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS social_services (
                id {serial} PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                unit_price BIGINT NOT NULL DEFAULT 0,
                min_qty INTEGER NOT NULL DEFAULT 1,
                max_qty INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                service_type TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS service_orders (
                order_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                service_id INTEGER NOT NULL,
                link TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT,
                admin_id BIGINT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                provider_order TEXT
            )
        """)
        for code,name,desc,price,mn,mx in SOCIAL_SERVICE_DEFAULTS:
            conn.execute("""
                INSERT INTO social_services(code,name,description,unit_price,min_qty,max_qty,active,service_type,created_at)
                VALUES (?,?,?,?,?,?,1,?,?)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name, description=excluded.description,
                unit_price=excluded.unit_price, min_qty=excluded.min_qty, max_qty=excluded.max_qty, service_type=excluded.service_type
            """, (code,name,desc,price,mn,mx,"manual",now_vn().strftime("%d/%m/%Y %H:%M:%S")))

        # Đồng bộ dữ liệu cũ: cấp giới thiệu lấy từ cap_bac cũ; cấp nạp lấy theo đơn nạp đã duyệt.
        users = conn.execute("SELECT id, cap_bac, gioi_thieu, total_deposited FROM users").fetchall()
        for u in users:
            gt = _v13_rank_by_referral(u[2] or 0)
            approved = conn.execute("""
                SELECT COALESCE(SUM(gia),0) FROM deposits
                WHERE user_id=? AND status='approved' AND COALESCE(deposit_type,'rank') IN ('rank','balance')
            """, (u[0],)).fetchone()[0] or 0
            old_total = int(u[3] or 0)
            total = max(old_total, int(approved))
            nap_rank = _v13_rank_by_deposit(total)
            conn.execute("UPDATE users SET cap_gioi_thieu=?, cap_nap=?, total_deposited=?, cap_bac=? WHERE id=?",
                         (gt, nap_rank, total, nap_rank, u[0]))


# init_db được gọi từ build_application; bọc thêm migration V13.
_v12_init_db = init_db
def init_db():
    _v12_init_db()
    try:
        import asyncio as _asyncio
        # Hàm migration chỉ chứa thao tác sync DB; chạy trực tiếp tránh tạo event loop thừa.
        with db() as conn:
            _safe_add_column(conn, "users", "cap_gioi_thieu", "TEXT NOT NULL DEFAULT 'Thành viên'")
            _safe_add_column(conn, "users", "cap_nap", "TEXT NOT NULL DEFAULT 'Thành viên'")
            _safe_add_column(conn, "users", "total_deposited", "BIGINT NOT NULL DEFAULT 0")
            _safe_add_column(conn, "deposits", "deposit_type", "TEXT NOT NULL DEFAULT 'rank'")
            _safe_add_column(conn, "deposits", "approved_by", "BIGINT")
            _safe_add_column(conn, "deposits", "approved_at", "TEXT")
            _safe_add_column(conn, "social_services", "service_type", "TEXT NOT NULL DEFAULT 'manual'")
            _safe_add_column(conn, "service_orders", "provider_order", "TEXT")
            serial = "BIGSERIAL" if DATABASE_URL else "INTEGER"
            conn.execute(f"CREATE TABLE IF NOT EXISTS social_services (id {serial} PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', unit_price BIGINT NOT NULL DEFAULT 0, min_qty INTEGER NOT NULL DEFAULT 1, max_qty INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, service_type TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL)")
            conn.execute(f"CREATE TABLE IF NOT EXISTS service_orders (order_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, service_id INTEGER NOT NULL, link TEXT NOT NULL, quantity INTEGER NOT NULL, total BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', note TEXT, admin_id BIGINT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, provider_order TEXT)")
            for code,name,desc,price,mn,mx in SOCIAL_SERVICE_DEFAULTS:
                conn.execute("INSERT INTO social_services(code,name,description,unit_price,min_qty,max_qty,active,service_type,created_at) VALUES (?,?,?,?,?,?,1,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name, description=excluded.description, unit_price=excluded.unit_price, min_qty=excluded.min_qty, max_qty=excluded.max_qty, service_type=excluded.service_type", (code,name,desc,price,mn,mx,"manual",now_vn().strftime("%d/%m/%Y %H:%M:%S")))
            users = conn.execute("SELECT id, cap_bac, gioi_thieu, total_deposited FROM users").fetchall()
            for u in users:
                approved = conn.execute("SELECT COALESCE(SUM(gia),0) FROM deposits WHERE user_id=? AND status='approved'", (u[0],)).fetchone()[0] or 0
                total = max(int(u[3] or 0), int(approved))
                gt = _v13_rank_by_referral(u[2] or 0)
                nap = _v13_rank_by_deposit(total)
                conn.execute("UPDATE users SET cap_gioi_thieu=?, cap_nap=?, total_deposited=?, cap_bac=? WHERE id=?", (gt,nap,total,nap,u[0]))
    except Exception:
        LOGGER.exception("V13 migration warning")


def _v13_profile_rank_text(u):
    gt = u.get("cap_gioi_thieu") or _v13_rank_by_referral(u.get("gioi_thieu",0))
    nap = u.get("cap_nap") or _v13_rank_by_deposit(u.get("total_deposited",0))
    return gt, nap


async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Vui lòng gõ /start trước.")
        return
    reset_daily_if_needed(u)
    gt, nap = _v13_profile_rank_text(u)
    cfg = CAP_BAC_CONFIG.get(nap, CAP_BAC_CONFIG["Thành viên"])
    xac = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that",0) else "🔒 Chưa xác minh"
    await update.message.reply_text(
        f"👤 <b>HỒ SƠ THÀNH VIÊN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{u['id']}</code>\n"
        f"👤 Tên: <b>{h(u['ten'])}</b>\n"
        f"💰 Số dư kiếm được: <b>{int(u.get('so_du',0) or 0):,}đ</b>\n"
        f"💳 Số dư nạp: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>\n"
        f"📥 Tổng nạp: <b>{int(u.get('total_deposited',0) or 0):,}đ</b>\n"
        f"👥 Cấp giới thiệu: <b>{h(gt)}</b>\n"
        f"💳 Cấp nạp: <b>{h(nap)}</b>\n"
        f"👥 Người giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b>\n"
        f"🎬 Video: <b>{int(u.get('video_da_xem',0)):,}</b> • Hôm nay: <b>{int(u.get('video_ngay',0))}/{cfg['gioi_han_xem_ngay']}</b>\n"
        f"💵 Thưởng/video: <b>{cfg['xu_moi_video']:,}đ</b>\n"
        f"🛡 Xác minh: {xac}\n"
        f"🏦 Tài khoản rút: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>\n\n"
        "ℹ️ Cấp giới thiệu và cấp nạp được tính độc lập.",
        parse_mode="HTML", reply_markup=menu_chinh(u['id'])
    )


async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u: return
    gt, nap = _v13_profile_rank_text(u)
    total = int(u.get('total_deposited',0) or 0)
    next_tiers = [(n,a) for n,a in sorted(CAP_NAP_AMOUNT.items(), key=lambda x:x[1]) if a > total]
    next_line = f"🎯 Còn {next_tiers[0][1]-total:,}đ để lên {next_tiers[0][0]}" if next_tiers else "🏆 Đã đạt cấp nạp cao nhất trong bảng hiện tại."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 CẤP GIỚI THIỆU", callback_data="rank_type:ref"), InlineKeyboardButton("💳 CẤP NẠP", callback_data="rank_type:deposit")],
        [InlineKeyboardButton("💳 NẠP TIỀN", callback_data="nap_tien_start")],
        [InlineKeyboardButton("📜 Bảng cấp giới thiệu", callback_data="rank_type:ref"), InlineKeyboardButton("📜 Bảng cấp nạp", callback_data="rank_type:deposit")],
    ])
    await update.message.reply_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Cấp giới thiệu hiện tại: <b>{h(gt)}</b>\n"
        f"💳 Cấp nạp hiện tại: <b>{h(nap)}</b>\n"
        f"💰 Tổng nạp: <b>{total:,}đ</b>\n"
        f"{next_line}\n\n"
        "📌 Hai hệ thống được tách riêng: giới thiệu không tự nâng cấp cấp nạp.",
        parse_mode="HTML", reply_markup=kb
    )


async def v13_rank_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    typ=q.data.split(":",1)[1]
    if typ == "ref":
        lines=["👥 <b>BẢNG CẤP GIỚI THIỆU</b>","━━━━━━━━━━━━━━━━━━━━"]
        for name,lo,hi in MOC_CAP[:40]:
            lines.append(f"{_rank_icon(name)} <b>{h(name)}</b> — {lo:,} người trở lên")
        lines.append("\n📌 Cấp này chỉ dựa trên số người giới thiệu.")
    else:
        lines=["💳 <b>BẢNG CẤP NẠP</b>","━━━━━━━━━━━━━━━━━━━━"]
        for name,amount in sorted(CAP_NAP_AMOUNT.items(), key=lambda x:x[1]):
            lines.append(f"{_rank_icon(name)} <b>{h(name)}</b> — tổng nạp từ {amount:,}đ")
        lines.append("\n📌 Cấp này chỉ dựa trên tổng tiền nạp đã được Admin duyệt.")
    await q.message.reply_text("\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Nâng cấp bậc",callback_data="rank_type:back")]]))



def _deposit_bank_info():
    bank = runtime_text('deposit_bank', 'ACB').strip()
    owner = runtime_text('deposit_account_name', 'HA QUANG MINH').strip()
    account = runtime_text('deposit_account_number', '25607451').strip()
    # VietQR dùng mã BIN ngân hàng. Có thể đổi bằng setting deposit_bank_bin.
    known_bins = {
        'ACB': '970416',
        'VCB': '970436', 'VIETCOMBANK': '970436',
        'BIDV': '970418', 'TCB': '970407', 'TECHCOMBANK': '970407',
        'MB': '970422', 'MBBANK': '970422',
        'VPB': '970432', 'VPBANK': '970432',
        'VIB': '970441', 'TPB': '970423', 'TPBANK': '970423',
        'STB': '970403', 'SACOMBANK': '970403',
        'OCB': '970448', 'SHB': '970443', 'MSB': '970426',
        'HDB': '970437', 'HDBANK': '970437',
    }
    bin_code = runtime_text('deposit_bank_bin', known_bins.get(bank.upper(), '')).strip()
    return bank, owner, account, bin_code


def _vietqr_url(amount: int, transfer_content: str):
    bank, owner, account, bin_code = _deposit_bank_info()
    if not bin_code or not account:
        return None
    return (
        f"https://img.vietqr.io/image/{quote(bin_code)}-{quote(account)}-compact2.png"
        f"?amount={int(amount)}&addInfo={quote(transfer_content)}&accountName={quote(owner)}"
    )


def _copy_text_button(label: str, value: str):
    """Tạo nút sao chép nếu phiên bản python-telegram-bot hỗ trợ CopyTextButton."""
    try:
        from telegram import CopyTextButton
        return InlineKeyboardButton(label, copy_text=CopyTextButton(text=str(value)))
    except Exception:
        return None


def _deposit_copy_keyboard(transfer_content: str, account: str, rid: str):
    rows = []
    b1 = _copy_text_button('📋 Sao chép STK', account)
    b2 = _copy_text_button('📝 Sao chép nội dung', transfer_content)
    if b1 and b2:
        rows.append([b1, b2])
    elif b1:
        rows.append([b1])
    elif b2:
        rows.append([b2])
    rows.append([InlineKeyboardButton('📩 Tôi đã chuyển khoản', callback_data=f'dachuyen:{rid}')])
    return InlineKeyboardMarkup(rows)


def _menu_button_texts():
    return {
        '👤 Hồ Sơ', '🔍 Xem TikTok', '👥 Cấp Giới Thiệu', '👑 Nâng Cấp Bậc',
        '💳 Nạp Tiền', '💰 Rút Tiền', '🛒 Dịch Vụ TikTok', '🎯 Nhiệm Vụ',
        '🎁 Điểm Danh', '🏆 BXH', '🎡 Vòng Quay', '🎁 Đổi Quà',
        '🎉 Sự Kiện', '🎧 Hỗ Trợ', '🔐 Nhập CaptCha', '🎛 QUẢN LÝ ADMIN'
    }


async def _conversation_menu_interrupt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Thoát luồng nhập và xử lý ngay nút menu vừa bấm.

    ConversationHandler đã nhận update nên handler MessageHandler ở group sau
    không được chạy lại. Vì vậy phải dispatch trực tiếp để nút không bị mất.
    """
    text = (update.effective_message.text or '').strip()
    if text not in _menu_button_texts():
        return None

    for key in (
        'v13_deposit_id', 'v13_deposit_amount', 'service_id',
        'dang_lien_ket', 'dang_rut_tien', 'ma_nap_dang_xu_ly',
        'admin_hanh_dong', 'admin_setting', 'admin_service_id',
        'admin_service_mode', 'captcha_code', 'captcha_created_at',
    ):
        context.user_data.pop(key, None)

    handlers = {
        '👤 Hồ Sơ': ho_so,
        '🔍 Xem TikTok': xem_tiktok,
        '👥 Cấp Giới Thiệu': khu_vuc_leader,
        '👑 Nâng Cấp Bậc': nang_cap,
        '💳 Nạp Tiền': v13_nap_tien_message_start,
        '💰 Rút Tiền': rut_tien_bat_dau,
        '🛒 Dịch Vụ TikTok': v13_social_menu,
        '🎯 Nhiệm Vụ': tasks_menu,
        '🎁 Điểm Danh': diem_danh,
        '🏆 BXH': bang_xep_hang,
        '🎡 Vòng Quay': wheel,
        '🎁 Đổi Quà': gift_menu,
        '🎉 Sự Kiện': event_menu,
        '🎧 Hỗ Trợ': ho_tro,
        '🔐 Nhập CaptCha': captcha,
        '🎛 QUẢN LÝ ADMIN': trang_quan_ly_admin,
    }
    fn = handlers.get(text)
    if fn is not None:
        await fn(update, context)
    return ConversationHandler.END


async def v13_nap_tien_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    u=get_user(q.from_user.id)
    if not u: return ConversationHandler.END
    bank, owner, account, _ = _deposit_bank_info()
    await q.message.reply_text(
        "💳 <b>NẠP TIỀN VÀO SỐ DƯ DỊCH VỤ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Số dư kiếm được: <b>{int(u.get('so_du',0) or 0):,}đ</b>\n"
        f"💳 Số dư dịch vụ: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>\n"
        "🔒 Tiền nạp chỉ dùng cho Dịch Vụ TikTok, không dùng để rút.\n\n"
        "🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>\n"
        f"🏦 Ngân hàng: <b>{h(bank)}</b>\n"
        f"👤 Chủ TK: <b>{h(owner)}</b>\n"
        f"🔢 Số TK: <code>{h(account)}</code>\n\n"
        "💵 Nhập số tiền muốn nạp (tối thiểu <b>10.000đ</b>):\n"
        "📌 Bạn có thể nhập: <code>10000</code>, <code>10.000đ</code> hoặc <code>10,000đ</code>.",
        parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    return NAP_TIEN_AMOUNT

async def v13_nap_tien_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận số tiền nạp với xử lý lỗi đầy đủ, không để lỗi DB/QR làm bot im lặng."""
    try:
        raw = (update.effective_message.text or '').strip()
        # Chỉ nhận số tiền; không nhận tên nút/menu trong state này.
        if not re.fullmatch(r'[0-9\s.,₫đĐ]+', raw):
            await update.message.reply_text(
                "❌ Số tiền không hợp lệ.\n\nVí dụ: <code>50000</code>, <code>50.000đ</code> hoặc <code>50,000đ</code>.",
                parse_mode='HTML')
            return NAP_TIEN_AMOUNT

        digits = re.sub(r'\D', '', raw)
        if not digits:
            await update.message.reply_text("❌ Vui lòng nhập số tiền bằng số.", parse_mode='HTML')
            return NAP_TIEN_AMOUNT
        amount = int(digits)
        if amount < 10000:
            await update.message.reply_text(
                "❌ Số tiền nạp tối thiểu là <b>10.000đ</b>.\n\nVui lòng nhập lại:",
                parse_mode='HTML')
            return NAP_TIEN_AMOUNT
        if amount > 2_000_000_000:
            await update.message.reply_text(
                "❌ Số tiền nạp tối đa là <b>2.000.000.000đ</b>.\n\nVui lòng nhập số nhỏ hơn.",
                parse_mode='HTML')
            return NAP_TIEN_AMOUNT

        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Không tìm thấy tài khoản. Vui lòng bấm /start.")
            return ConversationHandler.END

        # Mã duy nhất hơn, tránh trùng khi người dùng tạo 2 đơn liên tiếp.
        rid = f"NAP{u['id']}{int(time.time()*1000)}{uuid.uuid4().hex[:6].upper()}"
        bank, owner, account, _ = _deposit_bank_info()
        if not account:
            await update.message.reply_text(
                "❌ Hệ thống chưa cấu hình số tài khoản nhận tiền. Vui lòng liên hệ Admin.",
                reply_markup=menu_chinh(u['id']))
            return ConversationHandler.END

        # Một số DB cũ có thể chưa chạy migration deposit_type. Tự đảm bảo cột trước khi INSERT.
        try:
            with db() as conn:
                _safe_add_column(conn, 'deposits', 'deposit_type', "TEXT NOT NULL DEFAULT 'rank'")
                _safe_add_column(conn, 'deposits', 'approved_by', 'BIGINT')
                _safe_add_column(conn, 'deposits', 'approved_at', 'TEXT')
                conn.execute(
                    "INSERT INTO deposits(request_id,user_id,ten,goi_key,cap_moi,gia,thoi_gian,status,deposit_type) VALUES (?,?,?,?,?,?,?,'pending','balance')",
                    (rid, u['id'], u['ten'], 'nap_tien', u.get('cap_nap','Thành viên'), amount, now_vn().strftime('%d/%m/%Y %H:%M'))
                )
        except Exception as exc:
            LOGGER.exception('Lỗi tạo đơn nạp tiền %s', rid)
            await update.message.reply_text(
                "❌ <b>Không tạo được đơn nạp tiền.</b>\n\n"
                "Hệ thống gặp lỗi khi lưu yêu cầu. Vui lòng thử lại sau vài giây.\n"
                "Nếu vẫn lỗi, hãy báo Admin.",
                parse_mode='HTML', reply_markup=menu_chinh(u['id']))
            return ConversationHandler.END

        context.user_data['v13_deposit_id'] = rid
        context.user_data['v13_deposit_amount'] = amount

        qr = _vietqr_url(amount, rid)
        kb = _deposit_copy_keyboard(rid, account, rid)
        text = (
            f"💳 <b>XÁC NHẬN NẠP TIỀN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Mã nạp: <code>{h(rid)}</code>\n"
            f"💵 Số tiền: <b>{amount:,}đ</b>\n\n"
            f"🏦 Ngân hàng: <b>{h(bank)}</b>\n"
            f"👤 Chủ TK: <b>{h(owner)}</b>\n"
            f"🔢 Số TK: <code>{h(account)}</code>\n"
            f"📝 Nội dung CK: <code>{h(rid)}</code>\n\n"
            "📋 <b>STK và nội dung chuyển khoản có thể sao chép.</b>\n"
            "📷 Quét mã QR để chuyển khoản nhanh.\n\n"
            "⚠️ Chuyển <b>đúng số tiền</b> và <b>đúng nội dung</b>, sau đó bấm <b>📩 Tôi đã chuyển khoản</b> và gửi biên lai.\n\n"
            "💳 Khoản nạp sau khi Admin duyệt sẽ vào <b>Số dư dịch vụ</b> và không thể rút."
        )
        try:
            if qr:
                await update.message.reply_photo(photo=qr, caption=text, parse_mode='HTML', reply_markup=kb)
            else:
                await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)
        except Exception:
            # QR có thể lỗi mạng; vẫn gửi được thông tin chuyển khoản dạng text.
            LOGGER.exception('Không gửi được QR nạp tiền %s', rid)
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)
        return NAP_TIEN_RECEIPT
    except Exception:
        LOGGER.exception('Unhandled error trong v13_nap_tien_amount')
        await update.message.reply_text(
            "❌ Có lỗi khi xử lý số tiền nạp. Vui lòng thử lại bằng /start → 💳 Nạp Tiền.",
            reply_markup=menu_chinh(update.effective_user.id))
        context.user_data.pop('v13_deposit_id', None)
        context.user_data.pop('v13_deposit_amount', None)
        return ConversationHandler.END

async def v13_da_chuyen_khoan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xác nhận đã chuyển khoản, giữ nguyên state để nhận biên lai."""
    q = update.callback_query
    rid = context.user_data.get('v13_deposit_id')
    if not rid:
        await q.answer('❌ Phiên nạp tiền đã hết. Vui lòng bấm Nạp Tiền lại.', show_alert=True)
        return ConversationHandler.END
    try:
        await q.answer()
        with db() as conn:
            yc = conn.execute(
                "SELECT request_id, gia, status FROM deposits WHERE request_id=? AND user_id=?",
                (rid, update.effective_user.id),
            ).fetchone()
        if not yc or yc['status'] != 'pending':
            context.user_data.pop('v13_deposit_id', None)
            context.user_data.pop('v13_deposit_amount', None)
            await q.message.reply_text(
                '❌ Đơn nạp không còn hiệu lực. Vui lòng tạo đơn nạp mới.',
                reply_markup=menu_chinh(update.effective_user.id),
            )
            return ConversationHandler.END
        await q.message.reply_text(
            f"📩 <b>ĐÃ CHUYỂN KHOẢN</b>\n\n"
            f"💵 Số tiền: <b>{int(yc['gia']):,}đ</b>\n"
            f"🔔 Mã nạp: <code>{h(rid)}</code>\n\n"
            "📸 Bây giờ hãy gửi <b>ảnh hoặc file biên lai</b> chuyển khoản để Admin kiểm tra.",
            parse_mode='HTML',
        )
        return NAP_TIEN_RECEIPT
    except Exception:
        LOGGER.exception('Lỗi xác nhận đã chuyển khoản %s', rid)
        await q.message.reply_text('❌ Không kiểm tra được đơn nạp. Vui lòng thử lại.', reply_markup=menu_chinh(update.effective_user.id))
        return ConversationHandler.END


async def v13_nap_tien_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = context.user_data.get('v13_deposit_id')
    if not rid:
        await update.message.reply_text('❌ Phiên nạp tiền đã hết. Vui lòng bấm Nạp Tiền lại.', reply_markup=menu_chinh(update.effective_user.id))
        return ConversationHandler.END
    photo = update.effective_message.photo[-1] if update.effective_message.photo else None
    document = update.effective_message.document if update.effective_message.document else None
    file_id = photo.file_id if photo else (document.file_id if document else None)
    if not file_id:
        await update.message.reply_text('❌ Vui lòng gửi ảnh hoặc file biên lai chuyển khoản.')
        return NAP_TIEN_RECEIPT
    try:
        with db() as conn:
            yc = conn.execute(
                "SELECT * FROM deposits WHERE request_id=? AND status='pending'", (rid,)
            ).fetchone()
            if not yc:
                await update.message.reply_text('❌ Đơn nạp không còn hiệu lực.', reply_markup=menu_chinh(update.effective_user.id))
                return ConversationHandler.END
            conn.execute("UPDATE deposits SET photo_file_id=? WHERE request_id=? AND status='pending'", (file_id, rid))
        caption = (
            f"📥 <b>ĐƠN NẠP TIỀN</b>\n\n🆔 <code>{yc['user_id']}</code>\n👤 {h(yc['ten'])}\n"
            f"💵 {yc['gia']:,}đ\n🔔 <code>{h(rid)}</code>\n📌 Loại: Nạp số dư dịch vụ"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton('✅ DUYỆT', callback_data=f'duyet_nap_ok:{rid}'),
            InlineKeyboardButton('❌ TỪ CHỐI', callback_data=f'duyet_nap_no:{rid}')
        ]])
        if photo:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=caption, parse_mode='HTML', reply_markup=kb)
        else:
            await context.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=caption, parse_mode='HTML', reply_markup=kb)
        await update.message.reply_text(
            '✅ <b>Đã gửi biên lai!</b>\n\n⏳ Đơn đang chờ Admin duyệt.\n💳 Khi duyệt, tiền sẽ cộng vào <b>Số dư dịch vụ</b>.',
            parse_mode='HTML', reply_markup=menu_chinh(update.effective_user.id))
        context.user_data.pop('v13_deposit_id', None)
        context.user_data.pop('v13_deposit_amount', None)
        return ConversationHandler.END
    except Exception:
        LOGGER.exception('Lỗi nhận biên lai nạp tiền %s', rid)
        await update.message.reply_text(
            '❌ Không thể gửi biên lai lúc này. Đơn vẫn được giữ lại, vui lòng thử gửi lại sau.',
            reply_markup=menu_chinh(update.effective_user.id))
        return NAP_TIEN_RECEIPT


async def v13_social_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return
    if not _v15_special_unlocked(u):
        await update.message.reply_text(
            '🔒 <b>DỊCH VỤ ĐẶC BIỆT</b>\n━━━━━━━━━━━━━━━━━━━━\n'
            'Bạn chưa đủ điều kiện sử dụng dịch vụ.\n\n'
            f'{_v15_special_progress(u)}\n\n'
            '📌 Điều kiện mở:\n' + '\n'.join(_v15_special_condition_lines()),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('👑 Xem cấp bậc', callback_data='rank_type:special')],
                [InlineKeyboardButton('💳 Nạp tiền', callback_data='nap_tien_start'), InlineKeyboardButton('🏠 Menu', callback_data='ve_menu_chinh')],
            ]),
        )
        return

    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM social_services WHERE active=1 ORDER BY CASE code WHEN 'followers' THEN 1 WHEN 'likes' THEN 2 WHEN 'views' THEN 3 ELSE 9 END, id"
        ).fetchall()
    icon_map = {'followers':'👥', 'likes':'❤️', 'views':'👁️', 'comments':'💬', 'shares':'🔁', 'views_video':'👁️'}
    buttons = []
    for r in rows:
        icon = icon_map.get(r['code'], '🛒')
        label = str(r['name'])[:28]
        buttons.append([InlineKeyboardButton(
            f'{icon} {label}\n💰 {int(r["unit_price"]):,}đ/1 • 📦 {int(r["min_qty"]):,}-{int(r["max_qty"]):,}',
            callback_data=f"svc:{r['id']}"
        )])
    buttons += [
        [InlineKeyboardButton('📋 Đơn của tôi', callback_data='svc:orders'), InlineKeyboardButton('💳 Nạp số dư DV', callback_data='nap_tien_start')],
        [InlineKeyboardButton('👑 Cấp dịch vụ', callback_data='rank_type:special'), InlineKeyboardButton('🏠 Menu', callback_data='ve_menu_chinh')],
    ]
    special = _v15_rank_state(u)[2]
    text = (
        '🛒 <b>DỊCH VỤ ĐẶC BIỆT TIKTOK</b>\n'
        '━━━━━━━━━━━━━━━━━━━━\n'
        f'✨ Cấp dịch vụ: <b>{h(special)}</b>\n'
        f'💳 Số dư dịch vụ: <b>{int(u.get("so_du_nap", 0) or 0):,}đ</b>\n\n'
        '👇 Chọn dịch vụ để xem chi tiết, giá, giới hạn và đặt đơn.\n'
        '💡 Mỗi dịch vụ hiển thị riêng một nút để dễ chọn trên điện thoại.'
    )
    if not rows:
        text += '\n\n⚠️ Hiện chưa có dịch vụ đang mở.'
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def v13_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    data=q.data
    if data == 'svc:orders':
        with db() as conn:
            rows=conn.execute("SELECT o.order_id,s.name,o.quantity,o.total,o.status,o.created_at,o.provider_order FROM service_orders o JOIN social_services s ON s.id=o.service_id WHERE o.user_id=? ORDER BY o.created_at DESC LIMIT 20",(q.from_user.id,)).fetchall()
        st={'pending':'⏳ Chờ xử lý','processing':'🔄 Đang xử lý','done':'✅ Hoàn tất','refunded':'↩️ Hoàn tiền','rejected':'❌ Từ chối','cancelled':'🚫 Đã hủy'}
        text="📋 <b>ĐƠN DỊCH VỤ</b>\n━━━━━━━━━━━━━━━━━━━━\n"+ ("\n\n".join(f"<code>{r['order_id']}</code> • {h(r['name'])}\n🔢 {r['quantity']:,} • 💵 {r['total']:,}đ\n📌 {st.get(r['status'],r['status'])}" for r in rows) if rows else 'Chưa có đơn.')
        await q.message.reply_text(text,parse_mode='HTML'); return
    try: sid=int(data.split(':',1)[1])
    except Exception: return
    with db() as conn: r=conn.execute("SELECT * FROM social_services WHERE id=? AND active=1",(sid,)).fetchone()
    if not r: await q.answer('Dịch vụ không tồn tại.',show_alert=True); return
    context.user_data['service_id']=sid
    await q.message.reply_text(f"🛒 <b>{h(r['name'])}</b>\n\n{h(r['description'])}\n💵 Đơn giá: <b>{int(r['unit_price']):,}đ / 1</b>\n📦 Số lượng: {int(r['min_qty']):,}–{int(r['max_qty']):,}\n\nGửi: <code>link | số_lượng</code>",parse_mode='HTML',reply_markup=ReplyKeyboardRemove())
    return DV_TIKTOK_INPUT


async def v13_service_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw=(update.effective_message.text or '').strip()
    if '|' not in raw:
        await update.message.reply_text('❌ Sai định dạng. Ví dụ: https://www.tiktok.com/@abc/video/123 | 1000'); return DV_TIKTOK_INPUT
    link,qtys=[x.strip() for x in raw.split('|',1)]
    if 'tiktok.com' not in link.lower():
        await update.message.reply_text('❌ Link phải là TikTok hợp lệ.'); return DV_TIKTOK_INPUT
    try: qty=int(qtys.replace(',',''))
    except Exception: qty=0
    u=get_user(update.effective_user.id); sid=int(context.user_data.get('service_id',0))
    with db() as conn: r=conn.execute("SELECT * FROM social_services WHERE id=? AND active=1",(sid,)).fetchone()
    if not r or not u: return ConversationHandler.END
    if qty<r['min_qty'] or qty>r['max_qty']:
        await update.message.reply_text(f"❌ Số lượng phải từ {int(r['min_qty']):,} đến {int(r['max_qty']):,}."); return DV_TIKTOK_INPUT
    total=int(r['unit_price'])*qty; now=now_vn().strftime('%d/%m/%Y %H:%M:%S'); oid=f"DV{u['id']}{int(time.time()*1000)}"
    with db() as conn:
        changed=conn.execute("UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)-? WHERE id=? AND COALESCE(so_du_nap,0)>=?",(total,u['id'],total)).rowcount
        if changed!=1:
            await update.message.reply_text(f"❌ Số dư không đủ. Cần {total:,}đ, hiện có {int(u.get('so_du_nap',0) or 0):,}đ trong số dư nạp.",reply_markup=menu_chinh(u['id'])); return ConversationHandler.END
        conn.execute("INSERT INTO service_orders(order_id,user_id,service_id,link,quantity,total,status,created_at,updated_at) VALUES (?,?,?,?,?,?, 'pending',?,?)",(oid,u['id'],sid,link,qty,total,now,now))
        service_after = conn.execute('SELECT so_du_nap FROM users WHERE id=?',(u['id'],)).fetchone()
        _wallet_ledger(conn, u['id'], 'service', -total, int(service_after['so_du_nap'] or 0), 'service_order', oid, f'Thanh toán dịch vụ: {r["name"]}')
    kb=InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Nhận xử lý',callback_data=f'svc_admin:process:{oid}'),InlineKeyboardButton('❌ Từ chối + hoàn tiền',callback_data=f'svc_admin:reject:{oid}')]])
    await context.bot.send_message(chat_id=ADMIN_ID,text=f"🛒 <b>ĐƠN DỊCH VỤ TIKTOK</b>\n\n🆔 <code>{u['id']}</code>\n👤 {h(u['ten'])}\n📦 {h(r['name'])}\n🔗 {h(link)}\n🔢 SL: <b>{qty:,}</b>\n💵 Tổng: <b>{total:,}đ</b>\n🔔 <code>{oid}</code>",parse_mode='HTML',reply_markup=kb)
    await update.message.reply_text(f"✅ <b>Đã tạo đơn {oid}</b>\n💳 Đã giữ {total:,}đ từ số dư nạp.\n⏳ Chờ Admin xử lý.",parse_mode='HTML',reply_markup=menu_chinh(u['id']))
    context.user_data.pop('service_id',None); return ConversationHandler.END


async def v13_service_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    try: action,oid=q.data.split(':')[1:]
    except Exception: return
    with db() as conn:
        row=conn.execute("SELECT o.*,s.name FROM service_orders o JOIN social_services s ON s.id=o.service_id WHERE o.order_id=?",(oid,)).fetchone()
        if not row: await q.answer('Đơn không tồn tại.',show_alert=True); return
        now=now_vn().strftime('%d/%m/%Y %H:%M:%S')
        if action=='process' and row['status']=='pending':
            conn.execute("UPDATE service_orders SET status='processing',admin_id=?,updated_at=? WHERE order_id=? AND status='pending'",(q.from_user.id,now,oid)); msg='🔄 Đơn đã chuyển sang ĐANG XỬ LÝ.'
        elif action=='done' and row['status']=='processing':
            conn.execute("UPDATE service_orders SET status='done',admin_id=?,updated_at=? WHERE order_id=? AND status='processing'",(q.from_user.id,now,oid)); msg='✅ Đơn đã HOÀN TẤT.'
        elif action in ('reject','refund') and row['status'] in ('pending','processing'):
            conn.execute("UPDATE service_orders SET status='refunded',admin_id=?,updated_at=?,note=? WHERE order_id=? AND status=?",(q.from_user.id,now,'Admin hoàn tiền',oid,row['status']))
            conn.execute("UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)+? WHERE id=?",(row['total'],row['user_id']));
            service_after=conn.execute('SELECT so_du_nap FROM users WHERE id=?',(row['user_id'],)).fetchone()
            _wallet_ledger(conn,row['user_id'],'service',int(row['total']),int(service_after['so_du_nap'] or 0),'service_refund',row['order_id'],'Hoàn tiền đơn dịch vụ')
            msg=f"↩️ Đã hoàn {int(row['total']):,}đ."
        else:
            await q.answer('Trạng thái đơn không phù hợp.',show_alert=True); return
    try: await context.bot.send_message(chat_id=row['user_id'],text=msg)
    except Exception: pass
    kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Hoàn tất',callback_data=f'svc_admin:done:{oid}'),InlineKeyboardButton('↩️ Hoàn tiền',callback_data=f'svc_admin:refund:{oid}')]]) if action=='process' else None
    await q.edit_message_text(f"{msg}\n🔔 <code>{h(oid)}</code>",parse_mode='HTML',reply_markup=kb)


async def v13_admin_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    with db() as conn:
        rows=conn.execute("SELECT o.order_id,o.user_id,o.quantity,o.total,o.status,o.created_at,o.link,s.name FROM service_orders o JOIN social_services s ON s.id=o.service_id ORDER BY CASE o.status WHEN 'pending' THEN 1 WHEN 'processing' THEN 2 ELSE 9 END,o.created_at DESC LIMIT 50").fetchall()
    st={'pending':'⏳ Chờ xử lý','processing':'🔄 Đang xử lý','done':'✅ Hoàn tất','refunded':'↩️ Hoàn tiền','rejected':'❌ Từ chối'}
    text="🛒 <b>QUẢN LÝ DỊCH VỤ TIKTOK</b>\n━━━━━━━━━━━━━━━━━━━━\n"+("\n\n".join(f"<code>{r['order_id']}</code> • {h(r['name'])}\n👤 {r['user_id']} • 🔢 {r['quantity']:,} • 💵 {r['total']:,}đ\n📌 {st.get(r['status'],r['status'])}" for r in rows) if rows else 'Chưa có đơn.')
    await q.message.reply_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Admin',callback_data='admin_home')]]))

def _v13_admin_dashboard_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💸 Rút',callback_data='admin_ds_rut'),InlineKeyboardButton('📥 Nạp',callback_data='admin_ds_nap'),InlineKeyboardButton('🛡 Xác minh',callback_data='admin_ds_xacminh')],
        [InlineKeyboardButton('👥 User',callback_data='admin_ds_nguoi'),InlineKeyboardButton('🎬 Video',callback_data='admin_video'),InlineKeyboardButton('🛒 Dịch vụ',callback_data='admin_svc:list')],
        [InlineKeyboardButton('💰 + Tiền',callback_data='admin_cong_tien'),InlineKeyboardButton('💸 - Tiền',callback_data='admin_tru_tien'),InlineKeyboardButton('📢 Thông báo',callback_data='admin_gui_tb')],
        [InlineKeyboardButton('📊 Báo cáo',callback_data='admin_ext:reports'),InlineKeyboardButton('🛡 Anti-fraud',callback_data='admin_ext:fraud'),InlineKeyboardButton('⚙️ Cài đặt',callback_data='admin_ext:config')],
        [InlineKeyboardButton('🚀 Smart Center',callback_data='admin_v9:dashboard'),InlineKeyboardButton('🔄 Làm mới',callback_data='admin_refresh')],
    ])


async def _v13_admin_dashboard_content():
    try:
        with db() as conn:
            u=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            bal=conn.execute('SELECT COALESCE(SUM(so_du),0) FROM users').fetchone()[0]
            wd=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
            dep=conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
            svc=conn.execute("SELECT COUNT(*) FROM service_orders WHERE status='pending'").fetchone()[0]
            today=conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao=?",(today_vn(),)).fetchone()[0]
    except Exception:
        LOGGER.exception("Admin dashboard query failed; attempting schema self-heal")
        _v172_create_critical_tables(); _v172_add_columns()
        with db() as conn:
            u=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            bal=conn.execute('SELECT COALESCE(SUM(so_du),0) FROM users').fetchone()[0]
            wd=conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
            dep=conn.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
            svc=conn.execute("SELECT COUNT(*) FROM service_orders WHERE status='pending'").fetchone()[0]
            today=conn.execute("SELECT COUNT(*) FROM users WHERE ngay_vao=?",(today_vn(),)).fetchone()[0]
    text=("🎛 <b>ADMIN CONTROL V13</b>\n━━━━━━━━━━━━━━━━━━━━\n"
          f"👥 User: <b>{u:,}</b> • 🆕 Hôm nay: <b>{today:,}</b>\n"
          f"💰 Tổng số dư: <b>{int(bal):,}đ</b>\n"
          f"⏳ Chờ: 💸 {wd} • 📥 {dep} • 🛒 {svc}\n\n"
          "⚡ Chọn chức năng:")
    return text,_v13_admin_dashboard_keyboard()


async def v13_admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data
    if not is_admin(q.from_user.id): return
    if data=='admin_v13:services': return await v13_admin_services(update,context)
    if data=='admin_v13:home':
        await q.answer(); text,kb=await _v13_admin_dashboard_content(); await q.edit_message_text(text,parse_mode='HTML',reply_markup=kb)


def _v13_override_admin_dashboard():
    global _admin_dashboard_content
    async def _new(): return await _v13_admin_dashboard_content()
    _admin_dashboard_content=_new

_v13_override_admin_dashboard()


async def v13_nap_tien_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=get_user(update.effective_user.id)
    if not u: return ConversationHandler.END
    bank = runtime_text('deposit_bank','ACB')
    owner = runtime_text('deposit_account_name','HA QUANG MINH')
    account = runtime_text('deposit_account_number','25607451')
    await update.message.reply_text(
        "💳 <b>NẠP TIỀN VÀO SỐ DƯ DỊCH VỤ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Số dư kiếm được: <b>{int(u.get('so_du',0) or 0):,}đ</b>\n"
        f"💳 Số dư dịch vụ: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>\n"
        "🔒 Tiền nạp chỉ dùng cho Dịch Vụ TikTok, không dùng để rút.\n\n"
        "🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>\n"
        f"🏦 Ngân hàng: <b>{h(bank)}</b>\n"
        f"👤 Chủ TK: <b>{h(owner)}</b>\n"
        f"🔢 Số TK: <code>{h(account)}</code>\n\n"
        "💵 Nhập số tiền muốn nạp (tối thiểu <b>10.000đ</b>):",
        parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    return NAP_TIEN_AMOUNT


_NAP_MENU_TEXTS = (
    '👤 Hồ Sơ|🔍 Xem TikTok|👥 Cấp Giới Thiệu|👑 Nâng Cấp Bậc|'
    '💳 Nạp Tiền|💰 Rút Tiền|🛒 Dịch Vụ TikTok|🎯 Nhiệm Vụ|'
    '🎁 Điểm Danh|🏆 BXH|🎡 Vòng Quay|🎁 Đổi Quà|🎉 Sự Kiện|'
    '🎧 Hỗ Trợ|🔐 Nhập CaptCha|🎛 QUẢN LÝ ADMIN'
)


async def _nap_tien_interrupt_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Thoát luồng nạp và xử lý luôn nút menu vừa bấm.

    ConversationHandler đã nhận update nên handler group phía sau không được
    chạy lại; vì vậy phải dispatch trực tiếp để tránh nút menu bị hiểu là số tiền.
    """
    context.user_data.pop('v13_deposit_id', None)
    context.user_data.pop('v13_deposit_amount', None)
    text = (update.effective_message.text or '').strip()
    handlers = {
        '👤 Hồ Sơ': ho_so,
        '🔍 Xem TikTok': xem_tiktok,
        '👥 Cấp Giới Thiệu': khu_vuc_leader,
        '👑 Nâng Cấp Bậc': nang_cap,
        '🛒 Dịch Vụ TikTok': v13_social_menu,
        '🎯 Nhiệm Vụ': tasks_menu,
        '🎁 Điểm Danh': diem_danh,
        '🏆 BXH': bang_xep_hang,
        '🎡 Vòng Quay': wheel,
        '🎁 Đổi Quà': gift_menu,
        '🎉 Sự Kiện': event_menu,
        '🎧 Hỗ Trợ': ho_tro,
        '🔐 Nhập CaptCha': captcha,
        '🎛 QUẢN LÝ ADMIN': trang_quan_ly_admin,
        '💰 Rút Tiền': rut_tien_bat_dau,
    }
    if text == '💳 Nạp Tiền':
        return await v13_nap_tien_message_start(update, context)
    fn = handlers.get(text)
    if fn:
        await fn(update, context)
    return ConversationHandler.END


# V13: giữ cấp nạp độc lập với cấp giới thiệu trong mọi thao tác cũ.
_v13_old_save_user = save_user

def save_user(u):
    _v13_old_save_user(u)
    try:
        cap_ref = u.get('cap_gioi_thieu') or _v13_rank_by_referral(u.get('gioi_thieu',0))
        cap_nap = u.get('cap_nap') or _v13_rank_by_deposit(u.get('total_deposited',0))
        with db() as conn:
            conn.execute("UPDATE users SET cap_gioi_thieu=?, cap_nap=?, total_deposited=COALESCE(total_deposited,0), cap_bac=? WHERE id=?", (cap_ref,cap_nap,cap_nap,u['id']))
    except Exception:
        pass

_v13_old_init_user = init_user

def init_user(user_id, ten, ref_by=None, username=None):
    u = _v13_old_init_user(user_id, ten, ref_by, username)
    try:
        with db() as conn:
            row=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
            if row:
                cap_nap=row['cap_nap'] if row['cap_nap'] else _v13_rank_by_deposit(row.get('total_deposited',0) if hasattr(row,'get') else 0)
                cap_ref=_v13_rank_by_referral(row['gioi_thieu'])
                conn.execute("UPDATE users SET cap_gioi_thieu=?, cap_nap=?, cap_bac=? WHERE id=?",(cap_ref,cap_nap,cap_nap,user_id))
            if ref_by and ref_by != user_id:
                parent=conn.execute("SELECT id,gioi_thieu,cap_nap FROM users WHERE id=?",(ref_by,)).fetchone()
                if parent:
                    conn.execute("UPDATE users SET cap_gioi_thieu=?, cap_bac=? WHERE id=?",(_v13_rank_by_referral(parent['gioi_thieu']),parent['cap_nap'] or 'Thành viên',parent['id']))
        return get_user(user_id)
    except Exception:
        return u


async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=get_user(update.effective_user.id)
    if not u: return
    me=await context.bot.get_me()
    link=f"https://t.me/{me.username}?start={u['id']}"
    cap_ref=u.get('cap_gioi_thieu') or _v13_rank_by_referral(u.get('gioi_thieu',0))
    reward=CAP_BAC_CONFIG.get(cap_ref,CAP_BAC_CONFIG['Thành viên'])['thuong_gioi_thieu']
    await update.message.reply_text(
        f"👥 <b>CẤP GIỚI THIỆU</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Cấp hiện tại: <b>{h(cap_ref)}</b>\n"
        f"👥 Đã giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b> người\n"
        f"💰 Thưởng hiện tại: <b>{reward:,}đ/người</b>\n\n"
        f"🔗 Link giới thiệu:\n<code>{link}</code>\n\n"
        "📌 Cấp giới thiệu chỉ tính theo số người bạn mời thành công.",
        parse_mode='HTML', reply_markup=menu_chinh(u['id']))


async def _admin_user_detail_text_v13(u):
    return (
        f"👤 <b>CHI TIẾT USER</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{u['id']}</code>\n👤 {h(u.get('ten',''))}"
        f"\n🔗 @{h(u.get('username') or '—')}"
        f"\n💰 Số dư: <b>{int(u.get('so_du',0)):,}đ</b>"
        f"\n📥 Tổng nạp: <b>{int(u.get('total_deposited',0) or 0):,}đ</b>"
        f"\n👥 Cấp giới thiệu: <b>{h(u.get('cap_gioi_thieu') or _v13_rank_by_referral(u.get('gioi_thieu',0)))}</b>"
        f"\n💳 Cấp nạp: <b>{h(u.get('cap_nap') or 'Thành viên')}</b>"
        f"\n👥 Giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b>"
        f"\n🎬 Video: <b>{int(u.get('video_da_xem',0)):,}</b> • Hôm nay: <b>{int(u.get('video_ngay',0)):,}</b>"
        f"\n🛡 Xác minh: {'✅' if u.get('xac_minh_nguoi_that',0) else '❌'}"
        f"\n🔒 Trạng thái: {'🔒 Khóa' if u.get('bi_khoa',0) else '🟢 Hoạt động'}"
        f"\n🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>"
    )


def _admin_user_detail_text(u):
    return _admin_user_detail_text_v13_sync(u)

def _admin_user_detail_text_v13_sync(u):
    return (
        f"👤 <b>CHI TIẾT USER</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{u['id']}</code>\n👤 {h(u.get('ten',''))}\n"
        f"🔗 @{h(u.get('username') or '—')}\n"
        f"💰 Số dư kiếm được: <b>{int(u.get('so_du',0)):,}đ</b>\n"
        f"💳 Số dư nạp: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>\n"
        f"📥 Tổng nạp: <b>{int(u.get('total_deposited',0) or 0):,}đ</b>\n"
        f"👥 Cấp giới thiệu: <b>{h(u.get('cap_gioi_thieu') or _v13_rank_by_referral(u.get('gioi_thieu',0)))}</b>\n"
        f"💳 Cấp nạp: <b>{h(u.get('cap_nap') or 'Thành viên')}</b>\n"
        f"👥 Giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b>\n"
        f"🎬 Video: <b>{int(u.get('video_da_xem',0)):,}</b>\n"
        f"🛡 Xác minh: {'✅' if u.get('xac_minh_nguoi_that',0) else '❌'}\n"
        f"🔒 {'ĐANG KHÓA' if u.get('bi_khoa',0) else 'Hoạt động'}\n"
        f"🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>"
    )


def _admin_user_detail_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 + Kiếm",callback_data=f"admin_edit:cong:{user_id}"),InlineKeyboardButton("💸 - Kiếm",callback_data=f"admin_edit:tru:{user_id}")],
        [InlineKeyboardButton("💰 Đặt số dư kiếm",callback_data=f"admin_edit:setbal:{user_id}"),InlineKeyboardButton("💳 Đặt số dư nạp",callback_data=f"admin_edit:setbalnap:{user_id}")],
        [InlineKeyboardButton("💳 + Số dư nạp",callback_data=f"admin_edit:congnap:{user_id}"),InlineKeyboardButton("💳 - Số dư nạp",callback_data=f"admin_edit:trunap:{user_id}")],
        [InlineKeyboardButton("👥 Đổi cấp GT",callback_data=f"admin_edit:capgt:{user_id}"),InlineKeyboardButton("💳 Đổi cấp nạp",callback_data=f"admin_edit:capnap:{user_id}")],
        [InlineKeyboardButton("✏️ Tên",callback_data=f"admin_edit:name:{user_id}"),InlineKeyboardButton("🏦 Tài khoản",callback_data=f"admin_edit:account:{user_id}"),InlineKeyboardButton("👥 Giới thiệu",callback_data=f"admin_edit:gioithieu:{user_id}")],
        [InlineKeyboardButton("🎬 Video",callback_data=f"admin_edit:video:{user_id}"),InlineKeyboardButton("📅 Video ngày",callback_data=f"admin_edit:video_ngay:{user_id}"),InlineKeyboardButton("🎯 Reset ngày",callback_data=f"admin_edit:resetday:{user_id}")],
        [InlineKeyboardButton("🛡 Xác minh",callback_data=f"admin_edit:verify:{user_id}"),InlineKeyboardButton("🔓 Bỏ XM",callback_data=f"admin_edit:unverify:{user_id}"),InlineKeyboardButton("🔄 CAPTCHA",callback_data=f"admin_edit:captcha:{user_id}")],
        [InlineKeyboardButton("🔒 Khóa",callback_data=f"admin_edit:lock:{user_id}"),InlineKeyboardButton("🔓 Mở",callback_data=f"admin_edit:unlock:{user_id}"),InlineKeyboardButton("📜 Lịch sử",callback_data=f"admin_history:{user_id}")],
        [InlineKeyboardButton("♻️ RESET TÀI KHOẢN",callback_data=f"admin_edit:reset:{user_id}")],
        [InlineKeyboardButton("⬅️ Danh sách",callback_data="admin_ds_nguoi")],
    ])


# ============================================================
# V15 UPGRADE: 3 LOẠI CẤP BẬC + DỊCH VỤ ĐẶC BIỆT + HARDENING
# ============================================================
V15_REF_UNLOCK_LEVEL = 5       # Giá trị mặc định, có thể chỉnh trong Admin
V15_DEPOSIT_UNLOCK_LEVEL = 4   # Giá trị mặc định, có thể chỉnh trong Admin
V15_SPECIAL_RANKS = [
    'Chưa mở', 'Đặc Quyền I', 'Đặc Quyền II', 'Đặc Quyền III', 'VIP', 'VIP+'
]


def _v15_unlock_requirements():
    """Điều kiện mở dịch vụ đặc biệt, có thể thay đổi từ Admin."""
    try:
        ref_max = max(1, len(MOC_CAP))
        dep_names = sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1])
        dep_max = max(1, len(dep_names))
        ref = int(get_setting('special_ref_unlock_level', V15_REF_UNLOCK_LEVEL))
        dep = int(get_setting('special_deposit_unlock_level', V15_DEPOSIT_UNLOCK_LEVEL))
        ref = max(1, min(ref, ref_max))
        dep = max(1, min(dep, dep_max))
        return ref, dep
    except Exception:
        return V15_REF_UNLOCK_LEVEL, V15_DEPOSIT_UNLOCK_LEVEL


def _v15_unlock_names():
    ref_level, dep_level = _v15_unlock_requirements()
    ref_name = MOC_CAP[ref_level - 1][0] if 0 < ref_level <= len(MOC_CAP) else '—'
    dep_names = [x[0] for x in sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1])]
    dep_name = dep_names[dep_level - 1] if 0 < dep_level <= len(dep_names) else '—'
    return ref_level, dep_level, ref_name, dep_name


def _v15_ref_level(name):
    names = [x[0] for x in MOC_CAP]
    try:
        return names.index(name) + 1
    except ValueError:
        return 1


def _v15_deposit_level(name):
    names = [x[0] for x in sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1])]
    try:
        return names.index(name) + 1
    except ValueError:
        return 1


def _v15_special_rank(ref_name, deposit_name):
    ref_level = _v15_ref_level(ref_name)
    dep_level = _v15_deposit_level(deposit_name)
    ref_req, dep_req = _v15_unlock_requirements()
    if ref_level < ref_req or dep_level < dep_req:
        return 'Chưa mở'
    score = min(ref_level - ref_req + 1, dep_level - dep_req + 1)
    return V15_SPECIAL_RANKS[min(score, len(V15_SPECIAL_RANKS) - 1)]


def _v15_rank_state(u):
    ref = u.get('cap_gioi_thieu') or _v13_rank_by_referral(u.get('gioi_thieu', 0))
    dep = u.get('cap_nap') or _v13_rank_by_deposit(u.get('total_deposited', 0))
    special = _v15_special_rank(ref, dep)
    return ref, dep, special, _v15_ref_level(ref), _v15_deposit_level(dep)


def _v15_special_unlocked(u):
    _, _, special, ref_level, dep_level = _v15_rank_state(u)
    ref_req, dep_req = _v15_unlock_requirements()
    return ref_level >= ref_req and dep_level >= dep_req and special != 'Chưa mở'


def _v15_special_condition_lines():
    ref_req, dep_req, ref_name, dep_name = _v15_unlock_names()
    return [
        f'• Cấp giới thiệu ≥ {ref_req} ({ref_name})',
        f'• Cấp nạp ≥ {dep_req} ({dep_name})',
    ]


def _v15_special_progress(u):
    ref, dep, special, ref_level, dep_level = _v15_rank_state(u)
    ref_req, dep_req, _, _ = _v15_unlock_names()
    ref_ok = ref_level >= ref_req
    dep_ok = dep_level >= dep_req
    return (
        f"🎯 Điều kiện mở dịch vụ đặc biệt:\n"
        f"{'✅' if ref_ok else '🔒'} Cấp giới thiệu ≥ {ref_req}: <b>{h(ref)}</b> (cấp {ref_level})\n"
        f"{'✅' if dep_ok else '🔒'} Cấp nạp ≥ {dep_req}: <b>{h(dep)}</b> (cấp {dep_level})\n"
        f"✨ Cấp dịch vụ đặc biệt: <b>{h(special)}</b>"
    )


_v15_old_init_db = init_db

def init_db():
    _v15_old_init_db()
    try:
        with db() as conn:
            _safe_add_column(conn, 'users', 'cap_dac_biet', "TEXT NOT NULL DEFAULT 'Chưa mở'")
            rows = conn.execute('SELECT id, gioi_thieu, cap_gioi_thieu, cap_nap, total_deposited FROM users').fetchall()
            for r in rows:
                ref = r['cap_gioi_thieu'] or _v13_rank_by_referral(r['gioi_thieu'] or 0)
                dep = r['cap_nap'] or _v13_rank_by_deposit(r['total_deposited'] or 0)
                special = _v15_special_rank(ref, dep)
                conn.execute('UPDATE users SET cap_gioi_thieu=?, cap_nap=?, cap_dac_biet=?, cap_bac=? WHERE id=?',
                             (ref, dep, special, dep, r['id']))
    except Exception:
        LOGGER.exception('V15 migration warning')


async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text('Vui lòng gõ /start trước.')
        return
    reset_daily_if_needed(u)
    ref, dep, special, ref_level, dep_level = _v15_rank_state(u)
    cfg = CAP_BAC_CONFIG.get(dep, CAP_BAC_CONFIG['Thành viên'])
    xac = '✅ Đã xác minh' if u.get('xac_minh_nguoi_that', 0) else '🔒 Chưa xác minh'
    await update.message.reply_text(
        f"👤 <b>HỒ SƠ THÀNH VIÊN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{u['id']}</code>\n"
        f"👤 Tên: <b>{h(u['ten'])}</b>\n"
        f"💰 <b>Số dư kiếm được</b>: <b>{int(u.get('so_du', 0) or 0):,}đ</b>\n"
        f"💳 <b>Số dư nạp</b>: <b>{int(u.get('so_du_nap', 0) or 0):,}đ</b>\n"
        f"📥 Tổng nạp: <b>{int(u.get('total_deposited', 0) or 0):,}đ</b>\n\n"
        f"1️⃣ <b>CẤP GIỚI THIỆU</b>\n└ {h(ref)} • Cấp {ref_level}\n"
        f"└ 👥 {int(u.get('gioi_thieu', 0) or 0):,} người\n\n"
        f"2️⃣ <b>CẤP NẠP</b>\n└ {h(dep)} • Cấp {dep_level}\n"
        f"└ 📺 {int(u.get('video_ngay', 0) or 0):,}/{cfg['gioi_han_xem_ngay']} video hôm nay\n"
        f"└ 💵 {cfg['xu_moi_video']:,}đ/video\n\n"
        f"3️⃣ <b>CẤP DỊCH VỤ ĐẶC BIỆT</b>\n└ ✨ {h(special)}\n"
        f"└ {'🟢 Được sử dụng dịch vụ đặc biệt' if _v15_special_unlocked(u) else '🔒 Chưa đủ điều kiện'}\n\n"
        f"🛡 Xác minh: {xac}\n🏦 Tài khoản rút: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>",
        parse_mode='HTML', reply_markup=menu_chinh(u['id'])
    )


async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return
    ref, dep, special, ref_level, dep_level = _v15_rank_state(u)
    total = int(u.get('total_deposited', 0) or 0)
    next_tiers = [(n, a) for n, a in sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1]) if a > total]
    next_line = f"🎯 Còn {next_tiers[0][1]-total:,}đ để lên {next_tiers[0][0]}" if next_tiers else '🏆 Đã đạt cấp nạp cao nhất trong bảng hiện tại.'
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('1️⃣ Cấp giới thiệu', callback_data='rank_type:ref'), InlineKeyboardButton('2️⃣ Cấp nạp', callback_data='rank_type:deposit')],
        [InlineKeyboardButton('3️⃣ Cấp dịch vụ đặc biệt', callback_data='rank_type:special')],
        [InlineKeyboardButton('💳 Nạp tiền', callback_data='nap_tien_start')],
    ])
    await update.message.reply_text(
        '👑 <b>HỆ THỐNG 3 CẤP BẬC</b>\n━━━━━━━━━━━━━━━━━━━━\n\n'
        f'1️⃣ Cấp giới thiệu: <b>{h(ref)}</b> • cấp {ref_level}\n'
        f'2️⃣ Cấp nạp: <b>{h(dep)}</b> • cấp {dep_level}\n'
        f'3️⃣ Cấp dịch vụ: <b>{h(special)}</b>\n\n'
        f'📥 Tổng nạp: <b>{total:,}đ</b>\n{next_line}\n\n'
        '📌 Cấp giới thiệu và cấp nạp độc lập. Cấp dịch vụ đặc biệt chỉ mở khi đạt đủ cả hai điều kiện.',
        parse_mode='HTML', reply_markup=kb
    )


async def v13_rank_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    typ = q.data.split(':', 1)[1]
    if typ == 'back':
        u = get_user(q.from_user.id)
        if not u:
            await q.edit_message_text('Vui lòng gõ /start trước.')
            return
        ref, dep, special, ref_level, dep_level = _v15_rank_state(u)
        await q.edit_message_text(
            f'👑 <b>HỆ THỐNG 3 CẤP BẬC</b>\n\n'
            f'1️⃣ Giới thiệu: <b>{h(ref)}</b> (cấp {ref_level})\n'
            f'2️⃣ Nạp: <b>{h(dep)}</b> (cấp {dep_level})\n'
            f'3️⃣ Dịch vụ đặc biệt: <b>{h(special)}</b>',
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('1️⃣ Giới thiệu', callback_data='rank_type:ref'), InlineKeyboardButton('2️⃣ Nạp', callback_data='rank_type:deposit')],
                [InlineKeyboardButton('3️⃣ Dịch vụ đặc biệt', callback_data='rank_type:special')],
            ])
        )
        return
    if typ == 'ref':
        lines = ['1️⃣ <b>BẢNG CẤP GIỚI THIỆU</b>', '━━━━━━━━━━━━━━━━━━━━']
        for idx, (name, lo, hi) in enumerate(MOC_CAP, 1):
            lines.append(f'{idx}. {_rank_icon(name)} <b>{h(name)}</b> — {lo:,} người trở lên')
        lines.append('\n📌 Chỉ tính số người giới thiệu thành công.')
    elif typ == 'deposit':
        lines = ['2️⃣ <b>BẢNG CẤP NẠP</b>', '━━━━━━━━━━━━━━━━━━━━']
        for idx, (name, amount) in enumerate(sorted(CAP_NAP_AMOUNT.items(), key=lambda x: x[1]), 1):
            lines.append(f'{idx}. {_rank_icon(name)} <b>{h(name)}</b> — từ {amount:,}đ')
        lines.append('\n📌 Chỉ tính tổng tiền nạp đã được Admin duyệt.')
    else:
        u = get_user(q.from_user.id)
        if not u:
            return
        lines = [
            '3️⃣ <b>CẤP DỊCH VỤ ĐẶC BIỆT</b>', '━━━━━━━━━━━━━━━━━━━━',
            '🔐 Điều kiện mở dịch vụ:',
            *_v15_special_condition_lines(),
            '', _v15_special_progress(u),
            '', '✨ Cấp dịch vụ được tính riêng, không thay thế cấp giới thiệu hoặc cấp nạp.'
        ]
    await q.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('1️⃣ Giới thiệu', callback_data='rank_type:ref'), InlineKeyboardButton('2️⃣ Nạp', callback_data='rank_type:deposit')],
        [InlineKeyboardButton('3️⃣ Đặc biệt', callback_data='rank_type:special')],
        [InlineKeyboardButton('⬅️ Quay lại', callback_data='rank_type:back')],
    ]))


async def v13_social_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return
    if not _v15_special_unlocked(u):
        await update.message.reply_text(
            '🔒 <b>DỊCH VỤ ĐẶC BIỆT</b>\n━━━━━━━━━━━━━━━━━━━━\n'
            'Bạn chưa đủ điều kiện sử dụng hệ thống dịch vụ mạng xã hội.\n\n'
            f'{_v15_special_progress(u)}\n\n'
            '📌 ' + ' và '.join(_v15_special_condition_lines()) + ' để mở.',
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📜 Lịch sử ví', callback_data='wallet_history'), InlineKeyboardButton('📊 Thống kê', callback_data='wallet_stats')]])
        )
        return
    with db() as conn:
        rows = conn.execute("SELECT * FROM social_services WHERE active=1 ORDER BY CASE code WHEN 'followers' THEN 1 WHEN 'likes' THEN 2 WHEN 'views' THEN 3 ELSE 9 END, id").fetchall()
    icon_map = {'followers':'👥', 'likes':'❤️', 'views':'👁️'}
    buttons = []
    for i in range(0, len(rows), 2):
        pair = rows[i:i+2]
        buttons.append([
            InlineKeyboardButton(
                f"{icon_map.get(r['code'],'🛒')} {str(r['name'])[:16]}\n💰 {int(r['unit_price']):,}đ/1",
                callback_data=f"svc:{r['id']}"
            ) for r in pair
        ])
    buttons.append([InlineKeyboardButton('📋 Đơn của tôi', callback_data='svc:orders'), InlineKeyboardButton('🏠 Menu', callback_data='ve_menu_chinh')])
    special = _v15_rank_state(u)[2]
    text = (
        '🛒 <b>DỊCH VỤ MẠNG XÃ HỘI TIKTOK</b>\n'
        '━━━━━━━━━━━━━━━━━━━━\n'
        f'✨ Cấp dịch vụ: <b>{h(special)}</b>\n'
        f'💳 Số dư dịch vụ: <b>{int(u.get("so_du_nap", 0) or 0):,}đ</b>\n💰 Số dư rút: <b>{int(u.get("so_du", 0) or 0):,}đ</b>\n\n'
        'Chọn dịch vụ bên dưới để xem giá, giới hạn và đặt đơn.'
    )
    if not rows:
        text += '\n\n⚠️ Hiện chưa có dịch vụ đang mở.'
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def v13_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = get_user(q.from_user.id)
    if not u:
        return
    if not _v15_special_unlocked(u):
        await q.answer('🔒 Chưa đủ điều kiện: ' + ' + '.join(_v15_special_condition_lines()) + '.', show_alert=True)
        return
    data = q.data
    if data == 'svc:orders':
        with db() as conn:
            rows = conn.execute("SELECT o.order_id,s.name,o.quantity,o.total,o.status,o.created_at,o.provider_order FROM service_orders o JOIN social_services s ON s.id=o.service_id WHERE o.user_id=? ORDER BY o.created_at DESC LIMIT 20", (q.from_user.id,)).fetchall()
        st={'pending':'⏳ Chờ xử lý','processing':'🔄 Đang xử lý','done':'✅ Hoàn tất','refunded':'↩️ Hoàn tiền','rejected':'❌ Từ chối','cancelled':'🚫 Đã hủy'}
        text='📋 <b>ĐƠN DỊCH VỤ</b>\n━━━━━━━━━━━━━━━━━━━━\n'+ ('\n\n'.join(f"<code>{r['order_id']}</code> • {h(r['name'])}\n🔢 {r['quantity']:,} • 💵 {r['total']:,}đ\n📌 {st.get(r['status'],r['status'])}" for r in rows) if rows else 'Chưa có đơn.')
        await q.message.reply_text(text, parse_mode='HTML')
        return
    try:
        sid = int(data.split(':',1)[1])
    except Exception:
        return
    with db() as conn:
        r = conn.execute('SELECT * FROM social_services WHERE id=? AND active=1', (sid,)).fetchone()
    if not r:
        await q.answer('Dịch vụ không tồn tại.', show_alert=True)
        return
    context.user_data['service_id'] = sid
    await q.message.reply_text(
        f"🛒 <b>{h(r['name'])}</b>\n\n{h(r['description'])}\n💵 Đơn giá: <b>{int(r['unit_price']):,}đ / 1</b>\n📦 Số lượng: {int(r['min_qty']):,}–{int(r['max_qty']):,}\n\nGửi: <code>link | số_lượng</code>",
        parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
    return DV_TIKTOK_INPUT


async def v13_service_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return ConversationHandler.END
    if not _v15_special_unlocked(u):
        context.user_data.pop('service_id', None)
        await update.message.reply_text('🔒 Dịch vụ đặc biệt đã khóa. ' + ' + '.join(_v15_special_condition_lines()) + '.', reply_markup=menu_chinh(u['id']))
        return ConversationHandler.END
    return await _v15_service_input_core(update, context)


async def _v15_service_input_core(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw=(update.effective_message.text or '').strip()
    if '|' not in raw:
        await update.message.reply_text('❌ Sai định dạng. Ví dụ: https://www.tiktok.com/@abc/video/123 | 1000')
        return DV_TIKTOK_INPUT
    link,qtys=[x.strip() for x in raw.split('|',1)]
    if 'tiktok.com' not in link.lower():
        await update.message.reply_text('❌ Link phải là TikTok hợp lệ.')
        return DV_TIKTOK_INPUT
    try:
        qty=int(qtys.replace(',',''))
    except Exception:
        qty=0
    u=get_user(update.effective_user.id); sid=int(context.user_data.get('service_id',0))
    with db() as conn:
        r=conn.execute('SELECT * FROM social_services WHERE id=? AND active=1',(sid,)).fetchone()
    if not r or not u:
        return ConversationHandler.END
    if qty<r['min_qty'] or qty>r['max_qty']:
        await update.message.reply_text(f"❌ Số lượng phải từ {int(r['min_qty']):,} đến {int(r['max_qty']):,}.")
        return DV_TIKTOK_INPUT
    total=int(r['unit_price'])*qty
    if total <= 0:
        await update.message.reply_text('❌ Giá trị đơn hàng không hợp lệ.')
        return DV_TIKTOK_INPUT
    now=now_vn().strftime('%d/%m/%Y %H:%M:%S'); oid=f"DV{u['id']}{int(time.time()*1000)}"
    with db() as conn:
        changed=conn.execute('UPDATE users SET so_du_nap=COALESCE(so_du_nap,0)-? WHERE id=? AND COALESCE(so_du_nap,0)>=?',(total,u['id'],total)).rowcount
        if changed!=1:
            await update.message.reply_text(f"❌ Số dư không đủ. Cần {total:,}đ, hiện có {int(u.get('so_du_nap',0) or 0):,}đ trong số dư nạp.",reply_markup=menu_chinh(u['id']))
            return ConversationHandler.END
        conn.execute("INSERT INTO service_orders(order_id,user_id,service_id,link,quantity,total,status,created_at,updated_at) VALUES (?,?,?,?,?,?, 'pending',?,?)",(oid,u['id'],sid,link,qty,total,now,now))
    kb=InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Nhận xử lý',callback_data=f'svc_admin:process:{oid}'),InlineKeyboardButton('❌ Từ chối + hoàn tiền',callback_data=f'svc_admin:reject:{oid}')]])
    await context.bot.send_message(chat_id=ADMIN_ID,text=f"🛒 <b>ĐƠN DỊCH VỤ TIKTOK</b>\n\n🆔 <code>{u['id']}</code>\n👤 {h(u['ten'])}\n📦 {h(r['name'])}\n🔗 {h(link)}\n🔢 SL: <b>{qty:,}</b>\n💵 Tổng: <b>{total:,}đ</b>\n✨ Cấp DV: <b>{h(_v15_rank_state(u)[2])}</b>\n🔔 <code>{oid}</code>",parse_mode='HTML',reply_markup=kb)
    await update.message.reply_text(f"✅ <b>Đã tạo đơn {oid}</b>\n💳 Đã giữ {total:,}đ từ số dư nạp.\n⏳ Chờ Admin xử lý.",parse_mode='HTML',reply_markup=menu_chinh(u['id']))
    context.user_data.pop('service_id',None)
    return ConversationHandler.END


def _admin_user_detail_text_v13_sync(u):
    ref, dep, special, ref_level, dep_level = _v15_rank_state(u)
    return (
        f"👤 <b>CHI TIẾT USER</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{u['id']}</code>\n👤 {h(u.get('ten',''))}\n"
        f"🔗 @{h(u.get('username') or '—')}\n"
        f"💰 Số dư kiếm được: <b>{int(u.get('so_du',0) or 0):,}đ</b>\n"
        f"💳 Số dư nạp: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>\n"
        f"📥 Tổng nạp: <b>{int(u.get('total_deposited',0) or 0):,}đ</b>\n"
        f"1️⃣ GT: <b>{h(ref)}</b> (cấp {ref_level})\n"
        f"2️⃣ Nạp: <b>{h(dep)}</b> (cấp {dep_level})\n"
        f"3️⃣ DV đặc biệt: <b>{h(special)}</b>\n"
        f"👥 Giới thiệu: <b>{int(u.get('gioi_thieu',0)):,}</b>\n"
        f"🎬 Video: <b>{int(u.get('video_da_xem',0)):,}</b>\n"
        f"🛡 Xác minh: {'✅' if u.get('xac_minh_nguoi_that',0) else '❌'}\n"
        f"🔒 {'ĐANG KHÓA' if u.get('bi_khoa',0) else 'Hoạt động'}\n"
        f"🏦 Tài khoản: <code>{h(u.get('tai_khoan') or 'Chưa liên kết')}</code>"
    )


# Giữ tương thích dữ liệu cũ: cap_bac vẫn là alias của cấp nạp, không dùng để quyết định quyền dịch vụ.

# ============================================================
# V16: QUẢN LÝ DỊCH VỤ MXH PRO - CRUD TRỰC TIẾP TỪ ADMIN
# ============================================================
ADMIN_SVC_ADD = 61
ADMIN_SVC_EDIT = 62
ADMIN_SVC_CONDITIONS = 63

async def v16_admin_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer('Không có quyền.', show_alert=True)
        return
    await q.answer()
    with db() as conn:
        services = conn.execute("SELECT id,code,name,description,unit_price,min_qty,max_qty,active,service_type FROM social_services ORDER BY id").fetchall()
        pending = conn.execute("SELECT COUNT(*) FROM service_orders WHERE status='pending'").fetchone()[0]
        processing = conn.execute("SELECT COUNT(*) FROM service_orders WHERE status='processing'").fetchone()[0]
    ref_req, dep_req, ref_name, dep_name = _v15_unlock_names()
    lines = [
        '🛒 <b>DỊCH VỤ ĐẶC BIỆT — QUẢN LÝ</b>',
        '━━━━━━━━━━━━━━━━━━━━',
        f'📦 Tổng dịch vụ: <b>{len(services)}</b>  •  ⏳ Chờ: <b>{pending}</b>  •  🔄 Xử lý: <b>{processing}</b>',
        '',
        f'🔐 Điều kiện: GT cấp <b>{ref_req}</b> ({h(ref_name)}) + Nạp cấp <b>{dep_req}</b> ({h(dep_name)})',
    ]
    buttons = []
    for s in services:
        status = '🟢 ĐANG BẬT' if int(s['active']) else '🔴 ĐANG TẮT'
        lines += [
            '',
            f'{"🟢" if int(s["active"]) else "🔴"} <b>{h(s["name"])}</b>  <code>#{s["id"]}</code>',
            f'   └ <code>{h(s["code"])}</code> • <b>{int(s["unit_price"]):,}đ/1</b> • {int(s["min_qty"]):,}-{int(s["max_qty"]):,}',
            f'   └ {status}',
        ]
        buttons.append([
            InlineKeyboardButton('✏️ Sửa', callback_data=f'admin_svc:edit:{s["id"]}'),
            InlineKeyboardButton('🟢 Tắt' if int(s['active']) else '🔴 Bật', callback_data=f'admin_svc:toggle:{s["id"]}'),
            InlineKeyboardButton('🗑 Xóa', callback_data=f'admin_svc:delete:{s["id"]}')
        ])
    if not services:
        lines.append('\n⚠️ Chưa có dịch vụ. Bấm “➕ Thêm dịch vụ” để tạo.')
    buttons += [
        [InlineKeyboardButton('➕ Thêm dịch vụ', callback_data='admin_svc:add'), InlineKeyboardButton('📋 Đơn dịch vụ', callback_data='admin_v13:services')],
        [InlineKeyboardButton('🔐 Điều kiện đặc biệt', callback_data='admin_svc:conditions'), InlineKeyboardButton('🔄 Làm mới', callback_data='admin_svc:list')],
        [InlineKeyboardButton('⬅️ Admin', callback_data='admin_home')],
    ]
    text = '\n'.join(lines)
    try:
        await q.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        await q.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def v16_admin_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ''
    if not is_admin(q.from_user.id):
        await q.answer('Không có quyền.', show_alert=True)
        return
    parts = data.split(':')
    action = parts[1] if len(parts) > 1 else ''
    if action == 'list':
        return await v16_admin_services(update, context)
    if action == 'conditions':
        await q.answer()
        ref_req, dep_req, ref_name, dep_name = _v15_unlock_names()
        await q.message.reply_text(
            '⚙️ <b>ĐIỀU KIỆN DỊCH VỤ ĐẶC BIỆT</b>\n\n'
            f'👥 Cấp giới thiệu tối thiểu: <b>{ref_req}</b> — {h(ref_name)}\n'
            f'💳 Cấp nạp tối thiểu: <b>{dep_req}</b> — {h(dep_name)}\n\n'
            'Gửi theo mẫu: <code>cấp_giới_thiệu|cấp_nạp</code>\n'
            'Ví dụ: <code>5|4</code>\n\n'
            f'📌 Giới hạn hợp lệ: GT 1–{len(MOC_CAP)}, Nạp 1–{len(CAP_NAP_AMOUNT)}',
            parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        context.user_data['admin_service_mode'] = 'conditions'
        return ADMIN_SVC_CONDITIONS
    if action == 'add':
        await q.answer()
        await q.message.reply_text(
            '➕ <b>THÊM DỊCH VỤ</b>\n\n'
            'Gửi theo mẫu:\n<code>code|tên|giá/1|tối thiểu|tối đa|mô tả</code>\n\n'
            'Ví dụ:\n<code>followers2|Tăng Follow TikTok VIP|35|100|10000|Dịch vụ follow TikTok</code>',
            parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        context.user_data['admin_service_mode'] = 'add'
        return ADMIN_SVC_ADD
    if len(parts) < 3:
        await q.answer('Dữ liệu không hợp lệ.', show_alert=True); return ConversationHandler.END
    try:
        sid = int(parts[2])
    except ValueError:
        await q.answer('ID dịch vụ không hợp lệ.', show_alert=True); return ConversationHandler.END
    if action == 'toggle':
        with db() as conn:
            row = conn.execute('SELECT active,name FROM social_services WHERE id=?', (sid,)).fetchone()
            if not row:
                await q.answer('Không tìm thấy dịch vụ.', show_alert=True); return
            new = 0 if int(row['active']) else 1
            conn.execute('UPDATE social_services SET active=? WHERE id=?', (new, sid))
        await q.answer('Đã cập nhật trạng thái.')
        return await v16_admin_services(update, context)
    if action == 'delete':
        with db() as conn:
            row = conn.execute('SELECT name FROM social_services WHERE id=?', (sid,)).fetchone()
            if not row:
                await q.answer('Không tìm thấy dịch vụ.', show_alert=True); return
            used = conn.execute('SELECT COUNT(*) FROM service_orders WHERE service_id=?', (sid,)).fetchone()[0]
            if used:
                conn.execute('UPDATE social_services SET active=0 WHERE id=?', (sid,))
                msg = 'Đã ẩn dịch vụ vì dịch vụ đã có đơn.'
            else:
                conn.execute('DELETE FROM social_services WHERE id=?', (sid,))
                msg = 'Đã xóa dịch vụ.'
        await q.answer(msg, show_alert=True)
        return await v16_admin_services(update, context)
    if action == 'edit':
        with db() as conn:
            row = conn.execute('SELECT * FROM social_services WHERE id=?', (sid,)).fetchone()
        if not row:
            await q.answer('Không tìm thấy dịch vụ.', show_alert=True); return
        await q.answer()
        context.user_data['admin_service_mode'] = 'edit'
        context.user_data['admin_service_id'] = sid
        await q.message.reply_text(
            f"✏️ <b>SỬA DỊCH VỤ</b>\n\nDịch vụ: <b>{h(row['name'])}</b>\n\n"
            'Gửi:\n<code>tên|giá/1|tối thiểu|tối đa|mô tả</code>',
            parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        return ADMIN_SVC_EDIT
    await q.answer('Không hỗ trợ.', show_alert=True)

async def v16_admin_service_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    raw = (update.effective_message.text or '').strip()
    parts = [x.strip() for x in raw.split('|', 5)]
    if len(parts) != 6:
        await update.message.reply_text('❌ Cần đúng 6 phần: code|tên|giá|min|max|mô tả'); return ADMIN_SVC_ADD
    code, name, price_s, min_s, max_s, desc = parts
    try:
        price, mn, mx = int(price_s.replace(',','')), int(min_s.replace(',','')), int(max_s.replace(',',''))
    except ValueError:
        await update.message.reply_text('❌ Giá/min/max phải là số.'); return ADMIN_SVC_ADD
    if not code or not name or price <= 0 or mn <= 0 or mx < mn or len(code) > 40:
        await update.message.reply_text('❌ Dữ liệu không hợp lệ.'); return ADMIN_SVC_ADD
    now = now_vn().strftime('%d/%m/%Y %H:%M:%S')
    try:
        with db() as conn:
            conn.execute("INSERT INTO social_services(code,name,description,unit_price,min_qty,max_qty,active,service_type,created_at) VALUES (?,?,?,?,?,?,1,'manual',?)", (code,name,desc,price,mn,mx,now))
    except Exception as exc:
        await update.message.reply_text(f'❌ Không thể thêm: {h(str(exc))}', parse_mode='HTML'); return ADMIN_SVC_ADD
    context.user_data.pop('admin_service_mode', None)
    await update.message.reply_text(f'✅ Đã thêm dịch vụ <b>{h(name)}</b>.', parse_mode='HTML')
    return ConversationHandler.END

async def v16_admin_service_conditions_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    raw = (update.effective_message.text or '').strip().replace(' ', '')
    parts = raw.split('|')
    if len(parts) != 2:
        await update.message.reply_text('❌ Nhập đúng mẫu: <code>5|4</code>', parse_mode='HTML')
        return ADMIN_SVC_CONDITIONS
    try:
        ref_req, dep_req = int(parts[0]), int(parts[1])
    except ValueError:
        await update.message.reply_text('❌ Hai giá trị phải là số nguyên.')
        return ADMIN_SVC_CONDITIONS
    if not (1 <= ref_req <= len(MOC_CAP)) or not (1 <= dep_req <= len(CAP_NAP_AMOUNT)):
        await update.message.reply_text(f'❌ Giới hạn: GT 1–{len(MOC_CAP)} và Nạp 1–{len(CAP_NAP_AMOUNT)}.')
        return ADMIN_SVC_CONDITIONS
    set_setting('special_ref_unlock_level', ref_req)
    set_setting('special_deposit_unlock_level', dep_req)
    admin_log('special_service_condition_update', detail=f'ref={ref_req},deposit={dep_req}')
    _, _, ref_name, dep_name = _v15_unlock_names()
    context.user_data.pop('admin_service_mode', None)
    await update.message.reply_text(
        f'✅ <b>Đã cập nhật điều kiện dịch vụ đặc biệt</b>\n\n👥 GT: cấp <b>{ref_req}</b> — {h(ref_name)}\n💳 Nạp: cấp <b>{dep_req}</b> — {h(dep_name)}',
        parse_mode='HTML', reply_markup=menu_chinh(update.effective_user.id))
    return ConversationHandler.END


async def v16_admin_service_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    sid = int(context.user_data.get('admin_service_id', 0))
    parts = [x.strip() for x in (update.effective_message.text or '').strip().split('|', 4)]
    if len(parts) != 5:
        await update.message.reply_text('❌ Cần đúng 5 phần: tên|giá|min|max|mô tả'); return ADMIN_SVC_EDIT
    name, price_s, min_s, max_s, desc = parts
    try:
        price, mn, mx = int(price_s.replace(',','')), int(min_s.replace(',','')), int(max_s.replace(',',''))
    except ValueError:
        await update.message.reply_text('❌ Giá/min/max phải là số.'); return ADMIN_SVC_EDIT
    if not name or price <= 0 or mn <= 0 or mx < mn:
        await update.message.reply_text('❌ Dữ liệu không hợp lệ.'); return ADMIN_SVC_EDIT
    with db() as conn:
        changed = conn.execute('UPDATE social_services SET name=?,description=?,unit_price=?,min_qty=?,max_qty=? WHERE id=?', (name,desc,price,mn,mx,sid)).rowcount
    context.user_data.pop('admin_service_id', None); context.user_data.pop('admin_service_mode', None)
    await update.message.reply_text('✅ Đã cập nhật dịch vụ.' if changed else '❌ Không tìm thấy dịch vụ.')
    return ConversationHandler.END


# ============================================================
# V17: SỔ CÁI VÍ + LỊCH SỬ GIAO DỊCH
# ============================================================
def _wallet_ledger(conn, user_id, wallet_type, delta, balance_after, kind, reference_id='', note=''):
    try:
        conn.execute(
            "INSERT INTO wallet_ledger (user_id,wallet_type,delta,balance_after,kind,reference_id,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (int(user_id), str(wallet_type), int(delta), int(balance_after), str(kind), str(reference_id or ''), str(note or ''), now_vn().strftime('%d/%m/%Y %H:%M:%S')),
        )
    except Exception:
        LOGGER.exception('wallet_ledger write failed user=%s kind=%s ref=%s', user_id, kind, reference_id)

def _wallet_ledger_label(kind):
    return {
        'video_reward':'🎬 Thưởng xem TikTok',
        'referral_commission':'👥 Hoa hồng giới thiệu',
        'deposit_approved':'💳 Nạp tiền',
        'service_order':'🛒 Thanh toán dịch vụ',
        'service_refund':'↩️ Hoàn tiền dịch vụ',
        'withdraw_approved':'💸 Rút tiền',
        'admin_adjust':'🛠 Điều chỉnh Admin',
    }.get(kind, '🧾 Giao dịch ví')

async def wallet_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    u=get_user(uid)
    if not u:
        if update.callback_query:
            await update.callback_query.answer('❌ Không tìm thấy tài khoản.', show_alert=True)
        else:
            await update.message.reply_text('Vui lòng gõ /start trước.')
        return
    with db() as conn:
        rows=conn.execute('SELECT * FROM wallet_ledger WHERE user_id=? ORDER BY id DESC LIMIT 30',(uid,)).fetchall()
    lines=['📜 <b>LỊCH SỬ VÍ</b>','━━━━━━━━━━━━━━━━━━━━',
           f"💰 Ví kiếm được: <b>{int(u.get('so_du',0) or 0):,}đ</b> <i>(được rút)</i>",
           f"💳 Ví dịch vụ: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b> <i>(chỉ dùng dịch vụ)</i>",'']
    if not rows:
        lines.append('📭 Chưa có giao dịch.')
    else:
        for r in rows:
            delta=int(r['delta'] or 0); sign='+' if delta>=0 else ''
            wallet='💰' if r['wallet_type']=='earned' else '💳'
            label=_wallet_ledger_label(r['kind'])
            ref=f" · <code>{h(r['reference_id'])}</code>" if r['reference_id'] else ''
            lines.append(f"{wallet} {label}\n└ <b>{sign}{delta:,}đ</b> · {h(r['created_at'])}{ref}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Làm mới',callback_data='wallet_history')],
                             [InlineKeyboardButton('🏠 Menu chính',callback_data='wallet_home')]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text('\n'.join(lines),parse_mode='HTML',reply_markup=kb)
    else:
        await update.message.reply_text('\n'.join(lines),parse_mode='HTML',reply_markup=kb)

async def wallet_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id
    u=get_user(uid)
    if not u:
        await q.answer('❌ Không tìm thấy tài khoản.', show_alert=True); return
    with db() as conn:
        dep=conn.execute("SELECT COUNT(*) c, COALESCE(SUM(gia),0) total FROM deposits WHERE user_id=? AND status='approved'",(uid,)).fetchone()
        wd=conn.execute("SELECT COUNT(*) c, COALESCE(SUM(so_tien),0) total FROM withdrawals WHERE user_id=? AND status='approved'",(uid,)).fetchone()
        svc=conn.execute("SELECT COUNT(*) c, COALESCE(SUM(total),0) total FROM service_orders WHERE user_id=? AND status NOT IN ('rejected','refunded')",(uid,)).fetchone()
    text=(
        '📊 <b>THỐNG KÊ TÀI KHOẢN</b>\n'
        '━━━━━━━━━━━━━━━━━━━━\n'
        f"🎬 Video đã nhận thưởng: <b>{int(u.get('video_da_xem',0) or 0):,}</b>\n"
        f"👥 Người giới thiệu: <b>{int(u.get('gioi_thieu',0) or 0):,}</b>\n"
        f"💰 Tổng kiếm được: <b>{int(u.get('total_earned',0) or 0):,}đ</b>\n"
        f"💸 Tổng đã rút: <b>{int(u.get('total_withdrawn',0) or 0):,}đ</b>\n"
        f"📥 Lần nạp thành công: <b>{int(dep['c'] or 0)}</b> · {int(dep['total'] or 0):,}đ\n"
        f"🛒 Đơn dịch vụ: <b>{int(svc['c'] or 0)}</b> · {int(svc['total'] or 0):,}đ\n\n"
        f"💰 Số dư rút: <b>{int(u.get('so_du',0) or 0):,}đ</b>\n"
        f"💳 Số dư dịch vụ: <b>{int(u.get('so_du_nap',0) or 0):,}đ</b>"
    )
    await q.edit_message_text(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('📜 Lịch sử ví',callback_data='wallet_history')],
        [InlineKeyboardButton('🏠 Menu chính',callback_data='wallet_home')]
    ]))

async def wallet_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    await q.message.reply_text('🏠 Menu chính:',reply_markup=menu_chinh(q.from_user.id))

async def wallet_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await wallet_history(update, context)

def _wallet_history_migration(conn):
    if DATABASE_URL:
        conn.execute("CREATE TABLE IF NOT EXISTS wallet_ledger (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, wallet_type TEXT NOT NULL, delta BIGINT NOT NULL, balance_after BIGINT NOT NULL, kind TEXT NOT NULL, reference_id TEXT, note TEXT, created_at TEXT NOT NULL)")
    else:
        conn.execute("CREATE TABLE IF NOT EXISTS wallet_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT NOT NULL, wallet_type TEXT NOT NULL, delta BIGINT NOT NULL, balance_after BIGINT NOT NULL, kind TEXT NOT NULL, reference_id TEXT, note TEXT, created_at TEXT NOT NULL)")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_wallet_ledger_user ON wallet_ledger(user_id,id DESC)')

_wallet_prev_init_db_v17=init_db
def init_db():
    _wallet_prev_init_db_v17()
    try:
        with db() as conn:
            _wallet_history_migration(conn)
    except Exception:
        LOGGER.exception('V17 wallet ledger migration warning')


# ============================================================
# V17.2 - PRODUCTION DATABASE SELF-HEALING
# Defined before startup so the repair is actually executed.
# ============================================================
_V172_PREVIOUS_INIT_DB = init_db

def _v172_create_critical_tables():
    serial = "BIGSERIAL" if DATABASE_URL else "INTEGER"
    with db() as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS social_services (
            id {serial} PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', unit_price BIGINT NOT NULL DEFAULT 0,
            min_qty INTEGER NOT NULL DEFAULT 1, max_qty INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1, service_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS service_orders (
            order_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, service_id INTEGER NOT NULL,
            link TEXT NOT NULL, quantity INTEGER NOT NULL, total BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', note TEXT, admin_id BIGINT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, provider_order TEXT)""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS scheduled_notifications (
            id {serial} PRIMARY KEY, send_time TEXT NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'once', target TEXT NOT NULL DEFAULT 'all',
            content TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            last_sent_date TEXT, created_at TEXT NOT NULL)""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS wallet_ledger (
            id {serial} PRIMARY KEY, user_id BIGINT NOT NULL, wallet_type TEXT NOT NULL,
            delta BIGINT NOT NULL, balance_after BIGINT NOT NULL, kind TEXT NOT NULL,
            reference_id TEXT, note TEXT, created_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_ledger_user ON wallet_ledger(user_id,id DESC)")

def _v172_add_columns():
    migrations = [
        ("users","so_du_nap","BIGINT NOT NULL DEFAULT 0"),("users","bi_khoa","INTEGER NOT NULL DEFAULT 0"),
        ("users","username","TEXT"),("users","cap_gioi_thieu","TEXT NOT NULL DEFAULT 'Thành viên'"),
        ("users","cap_nap","TEXT NOT NULL DEFAULT 'Thành viên'"),("users","cap_dac_biet","TEXT NOT NULL DEFAULT 'Chưa mở'"),
        ("users","total_deposited","BIGINT NOT NULL DEFAULT 0"),("users","total_earned","BIGINT NOT NULL DEFAULT 0"),
        ("users","total_withdrawn","BIGINT NOT NULL DEFAULT 0"),("users","last_withdraw_at","TEXT"),
        ("users","risk_score","INTEGER NOT NULL DEFAULT 0"),("users","last_active_at","TEXT"),
        ("users","new_user_bonus_claimed","INTEGER NOT NULL DEFAULT 0"),
        ("withdrawals","risk_score","INTEGER NOT NULL DEFAULT 0"),("withdrawals","account_hash","TEXT"),
        ("withdrawals","risk_flags","TEXT"),("withdrawals","reviewed_at","TEXT"),("withdrawals","reject_reason","TEXT"),
        ("withdrawals","approved_by","BIGINT"),("withdrawals","rejected_by","BIGINT"),
        ("deposits","deposit_type","TEXT NOT NULL DEFAULT 'balance'"),("deposits","approved_by","BIGINT"),
        ("deposits","approved_at","TEXT"),("deposits","photo_file_id","TEXT"),
        ("video_links","active","INTEGER NOT NULL DEFAULT 1"),("video_links","views","INTEGER NOT NULL DEFAULT 0"),
        ("video_links","claimed","INTEGER NOT NULL DEFAULT 0"),("video_links","reward_total","BIGINT NOT NULL DEFAULT 0"),
        ("video_links","category","TEXT NOT NULL DEFAULT 'default'"),("video_links","created_at","TEXT"),
        ("social_services","description","TEXT NOT NULL DEFAULT ''"),("social_services","unit_price","BIGINT NOT NULL DEFAULT 0"),
        ("social_services","min_qty","INTEGER NOT NULL DEFAULT 1"),("social_services","max_qty","INTEGER NOT NULL DEFAULT 1"),
        ("social_services","active","INTEGER NOT NULL DEFAULT 1"),("social_services","service_type","TEXT NOT NULL DEFAULT 'manual'"),
        ("social_services","created_at","TEXT"),("service_orders","note","TEXT"),("service_orders","admin_id","BIGINT"),
        ("service_orders","created_at","TEXT"),("service_orders","updated_at","TEXT"),("service_orders","provider_order","TEXT"),
        ("scheduled_notifications","send_time","TEXT"),("scheduled_notifications","frequency","TEXT NOT NULL DEFAULT 'once'"),("scheduled_notifications","target","TEXT NOT NULL DEFAULT 'all'"),("scheduled_notifications","content","TEXT NOT NULL DEFAULT ''"),("scheduled_notifications","active","INTEGER NOT NULL DEFAULT 1"),("scheduled_notifications","last_sent_date","TEXT"),("scheduled_notifications","created_at","TEXT"),
    ]
    for table,column,definition in migrations:
        try:
            with db() as conn: _safe_add_column(conn,table,column,definition)
        except Exception: LOGGER.exception("V17.2 migration failed: %s.%s",table,column)

def _v172_seed_services():
    try:
        with db() as conn:
            for code,name,desc,price,mn,mx in SOCIAL_SERVICE_DEFAULTS:
                conn.execute("""INSERT INTO social_services
                (code,name,description,unit_price,min_qty,max_qty,active,service_type,created_at)
                VALUES (?,?,?,?,?,?,1,?,?) ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,description=excluded.description,unit_price=excluded.unit_price,
                min_qty=excluded.min_qty,max_qty=excluded.max_qty,service_type=excluded.service_type""",
                (code,name,desc,price,mn,mx,"manual",now_vn().strftime("%d/%m/%Y %H:%M:%S")))
    except Exception: LOGGER.exception("V17.2 service seed warning")

def init_db():
    try: _V172_PREVIOUS_INIT_DB()
    except Exception: LOGGER.exception("Legacy init_db warning; continuing with V17.2 repair")
    try: _v172_create_critical_tables()
    except Exception: LOGGER.exception("V17.2 critical table creation failed")
    _v172_add_columns()
    _v172_seed_services()


# V17.3: ensure legacy scheduled-notification schemas have every column used
# by both the admin composer and the scheduler.
def _v173_repair_scheduled_notifications():
    for table, column, definition in [
        ("scheduled_notifications", "send_time", "TEXT"),
        ("scheduled_notifications", "frequency", "TEXT NOT NULL DEFAULT 'once'"),
        ("scheduled_notifications", "target", "TEXT NOT NULL DEFAULT 'all'"),
        ("scheduled_notifications", "content", "TEXT NOT NULL DEFAULT ''"),
        ("scheduled_notifications", "active", "INTEGER NOT NULL DEFAULT 1"),
        ("scheduled_notifications", "last_sent_date", "TEXT"),
        ("scheduled_notifications", "created_at", "TEXT"),
    ]:
        try:
            with db() as conn:
                _safe_add_column(conn, table, column, definition)
        except Exception:
            LOGGER.exception("V17.3 scheduled notification migration failed: %s.%s", table, column)

_previous_init_db_v173 = init_db
def init_db():
    _previous_init_db_v173()
    _v173_repair_scheduled_notifications()


# ============================================================
# MAIN
# ====================================
# ============================================================
# V20.8: RÀ SOÁT NÚT BẤM / CALLBACK AUDIT
# ============================================================
def _v208_callback_audit_source():
    try:
        return Path(__file__).read_text(encoding='utf-8')
    except Exception:
        with open(__file__, 'r', encoding='utf-8') as f:
            return f.read()


def _v208_collect_callback_audit():
    source = _v208_callback_audit_source()
    tree = ast.parse(source)
    patterns = []
    literals = []
    dynamic = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'CallbackQueryHandler':
            for kw in node.keywords:
                if kw.arg == 'pattern' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    patterns.append(kw.value.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'InlineKeyboardButton':
            for kw in node.keywords:
                if kw.arg == 'callback_data':
                    v = kw.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        literals.append(v.value)
                    elif isinstance(v, ast.JoinedStr):
                        dynamic += 1
    uncovered = []
    for value in sorted(set(literals)):
        try:
            if not any(re.fullmatch(p, value) for p in patterns):
                uncovered.append(value)
        except re.error:
            continue
    return len(patterns), len(set(literals)), dynamic, uncovered


async def admin_button_audit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer('Không có quyền.', show_alert=True)
        return
    await q.answer('🔎 Đang rà soát...', cache_time=0)
    try:
        handlers, literals, dynamic, uncovered = _v208_collect_callback_audit()
        if uncovered:
            detail = '\n'.join(f'• <code>{h(x)}</code>' for x in uncovered[:25])
            status = f'⚠️ <b>{len(uncovered)}</b> callback tĩnh chưa khớp handler'
        else:
            detail = '• Không phát hiện callback tĩnh bị bỏ sót.'
            status = '✅ <b>Không có callback tĩnh bị bỏ sót</b>'
        text = (
            '🧪 <b>RÀ SOÁT NÚT BẤM V20.8</b>\n'
            '━━━━━━━━━━━━━━━━━━━━\n'
            f'🧩 Handler callback: <b>{handlers}</b>\n'
            f'🔘 Callback tĩnh: <b>{literals}</b>\n'
            f'🔧 Callback động (f-string): <b>{dynamic}</b>\n\n'
            f'{status}\n{detail}\n\n'
            'ℹ️ Callback động cần kiểm tra bằng thao tác bấm thật trên Telegram.\n'
            'ℹ️ Bộ bắt lỗi V20.8 chỉ ghi lỗi khi không có handler nào thực sự nhận callback.'
        )
        await q.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🔄 Rà soát lại', callback_data='admin_button_audit')],
            [InlineKeyboardButton('⬅️ Admin', callback_data='admin_home')],
        ]))
    except Exception as exc:
        LOGGER.exception('V20.8 callback audit failed')
        await q.message.reply_text(f'❌ Rà soát lỗi: <code>{h(str(exc))}</code>', parse_mode='HTML')


async def _v208_unhandled_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    handled_id = context.user_data.get('_v208_handled_callback_id')
    if handled_id == q.id:
        return
    data = q.data or ''
    LOGGER.warning('UNHANDLED_CALLBACK data=%r user_id=%s', data, q.from_user.id)
    await q.answer('⚠️ Nút này chưa được xử lý. Đã ghi log để kiểm tra.', show_alert=True, cache_time=0)


def build_application():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # V13: nạp tiền số dư độc lập với nâng cấp bậc.
    nap_tien_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(v13_nap_tien_start, pattern=r'^nap_tien_start$'),
            MessageHandler(filters.Regex(r'^💳 Nạp Tiền$'), v13_nap_tien_message_start),
        ],
        states={
            NAP_TIEN_AMOUNT:[
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _nap_tien_interrupt_to_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, v13_nap_tien_amount),
            ],
            NAP_TIEN_RECEIPT:[
                CallbackQueryHandler(v13_da_chuyen_khoan_callback, pattern=r'^dachuyen:.+$'),
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _nap_tien_interrupt_to_menu),
                MessageHandler(filters.PHOTO | filters.Document.ALL, v13_nap_tien_receipt),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start),
            MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _nap_tien_interrupt_to_menu),
        ],
        per_user=True, per_chat=True, allow_reentry=True
    )
    service_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(v13_service_callback, pattern=r'^svc:\d+$')],
        states={DV_TIKTOK_INPUT:[MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt), MessageHandler(filters.TEXT & ~filters.COMMAND, v13_service_input)]},
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt)], per_user=True, per_chat=True, allow_reentry=True
    )
    app.add_handler(nap_tien_conv, group=0)
    app.add_handler(service_conv, group=1)
    app.add_handler(CallbackQueryHandler(v13_rank_type_callback, pattern=r'^rank_type:(ref|deposit|special|back)$'), group=0)
    app.add_handler(CallbackQueryHandler(v13_service_admin_callback, pattern=r'^svc_admin:(process|done|reject|refund):.+$'), group=0)
    app.add_handler(CallbackQueryHandler(v13_admin_router, pattern=r'^admin_v13:'), group=0)
    admin_svc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(v16_admin_service_callback, pattern=r'^admin_svc:(add|conditions)$|^admin_svc:edit:\d+$')],
        states={
            ADMIN_SVC_ADD:[MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt), MessageHandler(filters.TEXT & ~filters.COMMAND, v16_admin_service_add_input)],
            ADMIN_SVC_EDIT:[MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt), MessageHandler(filters.TEXT & ~filters.COMMAND, v16_admin_service_edit_input)],
            ADMIN_SVC_CONDITIONS:[MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt), MessageHandler(filters.TEXT & ~filters.COMMAND, v16_admin_service_conditions_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)], per_user=True, per_chat=True, allow_reentry=True
    )
    app.add_handler(admin_svc_conv, group=0)
    app.add_handler(CallbackQueryHandler(v16_admin_service_callback, pattern=r'^admin_svc:(toggle|delete):\d+$'), group=0)
    app.add_handler(CallbackQueryHandler(v16_admin_services, pattern=r'^admin_svc:list$'), group=0)
    app.add_handler(CallbackQueryHandler(admin_button_audit_callback, pattern=r'^admin_button_audit$'), group=0)
    app.add_handler(CallbackQueryHandler(v13_service_callback, pattern=r'^svc:orders$'), group=0)
    app.add_handler(MessageHandler(filters.Regex(r'^🛒 Dịch Vụ TikTok$'), v13_social_menu), group=1)
    app.add_handler(MessageHandler(filters.Regex(r'^👑 Nâng Cấp Bậc$'), nang_cap), group=1)

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
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    nhan_anh_chuyen_khoan,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start), MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt)],
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
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    nhap_thong_tin_tai_khoan,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    # Conversation: admin
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                xu_ly_admin_callback,
                pattern=r"^(admin_(cong_tien|tru_tien|cong_tat_ca|gui_tb|tim_nguoi|ds_nguoi_all|video|video_list|video_add|lich_su|log|settings|set:(min|max|daily|cooldown))|admin_history:\d+|admin_user:\d+|admin_reset_confirm:\d+|admin_edit:(cong|tru|setbal|congnap|trunap|setbalnap|cap|capgt|capnap|verify|unverify|captcha|reset|name|account|gioithieu|video|video_ngay|earned|withdrawn|resetday|lock|unlock):\d+|admin_video_del:\d+)$",
            ),
        ],
        states={
            ADMIN_CONG_SO_DU: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_TRU_SO_DU: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_CONG_TAT_CA: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_cong_tru,
                ),
            ],
            ADMIN_SUA_NGUOI: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_sua_nguoi,
                ),
            ],
            ADMIN_TIM_NGUOI: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_tim_nguoi,
                ),
            ],
            ADMIN_VIDEO_ADD: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_xu_ly_them_video,
                ),
            ],
            ADMIN_GUI_TB: [
                MessageHandler(filters.Regex(rf'^({_NAP_MENU_TEXTS})$'), _conversation_menu_interrupt),
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
        MessageHandler(filters.Regex(r"^👤 Hồ Sơ$"), ho_so), group=1
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔍 Xem TikTok$"), xem_tiktok), group=1
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👥 Cấp Giới Thiệu$"), khu_vuc_leader), group=1
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👑 Nâng Cấp Bậc$"), nang_cap), group=1
    )
    app.add_handler(MessageHandler(filters.Regex(r"^🎁 Điểm Danh$"), diem_danh), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^🏆 BXH$"), bang_xep_hang), group=1)
    app.add_handler(
        MessageHandler(filters.Regex(r"^🎧 Hỗ Trợ$"), ho_tro), group=1
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔐 Nhập CaptCha$"), captcha), group=1
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🎛 QUẢN LÝ ADMIN$"), trang_quan_ly_admin), group=1
    )

    # ========================================================
    # V3: NHIỆM VỤ / QUÀ / ADMIN PRO / CẤP BẬC
    # ========================================================
    gift_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🎁 Đổi Quà$"), gift_menu)],
        states={GIFT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_input)]},
        fallbacks=[
            CommandHandler("cancel", cancel),
            # Khi đang nhập Gift Code mà người dùng bấm menu khác,
            # kết thúc Gift Code để menu tương ứng được handler phía sau xử lý.
            MessageHandler(filters.Regex(r"^💰 Rút Tiền$"), _gift_interrupt_to_withdraw),
            MessageHandler(filters.Regex(r"^(👤 Hồ Sơ|🔍 Xem TikTok|👥 Cấp Giới Thiệu|👑 Nâng Cấp Bậc|💳 Nạp Tiền|🛒 Dịch Vụ TikTok|🎯 Nhiệm Vụ|🎁 Điểm Danh|🏆 BXH|🎡 Vòng Quay|🎉 Sự Kiện|🎧 Hỗ Trợ|🔐 Nhập CaptCha|🎛 QUẢN LÝ ADMIN)$"), _gift_interrupt_to_menu),
        ],
        per_user=True, per_chat=True, allow_reentry=True,
    )
    admin_ext_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ext_callback, pattern=r"^(admin_ext|admin_set2):.+$")],
        states={ADMIN_EXT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ext_input)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True, per_chat=True, allow_reentry=True,
    )
    app.add_handler(gift_conv, group=0)
    app.add_handler(admin_ext_conv, group=0)

    reject_withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(pro_withdraw_confirm_callback, pattern=r"^pro_wd_reject:.+$")],
        states={ADMIN_EXT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pro_withdraw_reject_input)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_user=True, per_chat=True, allow_reentry=True,
    )
    admin_pro_input_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_pro_router, pattern=r"^(pro_video_bulk|pro_broadcast:(verified|unverified|rank)|pro_settings_more)$")],
        states={ADMIN_EXT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ext_input)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_user=True, per_chat=True, allow_reentry=True,
    )
    app.add_handler(reject_withdraw_conv, group=0)
    app.add_handler(admin_pro_input_conv, group=0)
    app.add_handler(CallbackQueryHandler(admin_pro_router, pattern=r"^(pro_user_stats:\d+|pro_wd_approve_list)$"), group=0)
    app.add_handler(CallbackQueryHandler(pro_withdraw_confirm_callback, pattern=r"^pro_wd_confirm:.+$"), group=0)

    admin_v9_broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_v9_broadcast_start, pattern=r"^admin_v9:broadcast_start$")],
        states={ADMIN_V9_BROADCAST_INPUT: [
            CallbackQueryHandler(admin_v9_broadcast_target, pattern=r"^admin_v9:bcast_target:(all|verified|unverified|rank)$"),
            CallbackQueryHandler(admin_v9_broadcast_action, pattern=r"^admin_v9:bcast_(confirm|edit|cancel)$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_v9_broadcast_text),
        ]},
        fallbacks=[CommandHandler("cancel", cancel)], per_user=True, per_chat=True, allow_reentry=True,
    )
    app.add_handler(admin_v9_broadcast_conv, group=0)
    app.add_handler(CallbackQueryHandler(admin_v9_router, pattern=r"^admin_v9:"), group=0)
    app.add_handler(CallbackQueryHandler(
        extra_callback_router,
        pattern=r"^(rank_page|rank_info|rank_noop|rank_back|task_claim|tasks_refresh|wheel_spin|admin_video_toggle)(:.+)?$",
    ), group=0)
    app.add_handler(MessageHandler(filters.Regex(r"^🎯 Nhiệm Vụ$"), tasks_menu), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^🎡 Vòng Quay$"), wheel), group=1)
    app.add_handler(MessageHandler(filters.Regex(r"^🎉 Sự Kiện$"), event_menu), group=1)

    # Job queue: thông báo theo lịch mỗi phút.
    try:
        if app.job_queue:
            app.job_queue.run_repeating(job_process_scheduled_notifications, interval=60, first=5, name="scheduled_notifications_v3")
    except Exception:
        LOGGER.exception("Không khởi tạo được scheduled notification job")

    app.add_handler(CallbackQueryHandler(wallet_history, pattern=r'^wallet_history$'), group=0)
    app.add_handler(CallbackQueryHandler(wallet_home, pattern=r'^wallet_home$'), group=0)
    app.add_handler(CallbackQueryHandler(wallet_stats, pattern=r'^wallet_stats$'), group=0)
    app.add_handler(CommandHandler('lichsu', wallet_summary_command), group=0)
    app.add_handler(CommandHandler('history', wallet_summary_command), group=0)
    # V20.8: chỉ báo callback thật sự không có handler; không còn cảnh báo giả do handler kiểm tra tĩnh.
    app.add_handler(CallbackQueryHandler(_v208_unhandled_callback, pattern=r'.*'), group=99)

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
        LOGGER.info("Database schema self-heal V17.2 completed")
        backend = "Neon PostgreSQL" if DATABASE_URL else f"SQLite ({DB_FILE})"
        LOGGER.info("Database backend: %s", backend)
        run_bot()

    except KeyboardInterrupt:
        print("Bot đã dừng.")
    except Exception as exc:
        print("BOT START ERROR:", repr(exc))