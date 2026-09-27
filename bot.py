import asyncio
import html
import os
import time
import sqlite3
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
    ContextTypes,
    filters,
)

# ============================================================
# CẤU HÌNH
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8633360420:AAFL8ab-zheRorpwEf7Ol1cki_9RVjsfB6I") 
ADMIN_ID = int(os.getenv("ADMIN_ID", "8207544772")) 
KENH_YEU_CAU = os.getenv("KENH_YEU_CAU", "@thongbaoxutiktok")
LINK_VIDEO = os.getenv("LINK_VIDEO", "https://vt.tiktok.com/ZSb6JTwaf/")
RUT_TOI_THIEU = 50_000
PHI_XAC_MINH = 30_000
XAC_MINH_NGAN_HANG = os.getenv("XAC_MINH_NGAN_HANG", "ACB")
XAC_MINH_CHU_TK = os.getenv("XAC_MINH_CHU_TK", "HA QUANG MINH")
XAC_MINH_SO_TK = os.getenv("XAC_MINH_SO_TK", "25607451")
DB_FILE = os.getenv("DB_FILE", "bot_data.db")
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

if not BOT_TOKEN:
    raise RuntimeError("Thiếu biến môi trường BOT_TOKEN.")
if not ADMIN_ID:
    raise RuntimeError("Thiếu biến môi trường ADMIN_ID.")

# Conversation states
NHAP_TAI_KHOAN = 1
ADMIN_CONG_SO_DU = 10
ADMIN_TRU_SO_DU = 11
ADMIN_GUI_TB = 12
ADMIN_CONG_TAT_CA = 13
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
def db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def now_vn():
    return datetime.now(VN_TZ)


def today_vn():
    return now_vn().strftime("%d/%m/%Y")


def h(value):
    return html.escape(str(value), quote=False)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                ten TEXT NOT NULL,
                cap_bac TEXT NOT NULL DEFAULT 'Thành viên',
                so_du INTEGER NOT NULL DEFAULT 0,
                video_da_xem INTEGER NOT NULL DEFAULT 0,
                video_ngay INTEGER NOT NULL DEFAULT 0,
                gioi_thieu INTEGER NOT NULL DEFAULT 0,
                ref_by INTEGER,
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
                user_id INTEGER NOT NULL,
                ten TEXT NOT NULL,
                so_tien INTEGER NOT NULL,
                tai_khoan TEXT NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                request_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                ten TEXT NOT NULL,
                goi_key TEXT NOT NULL,
                cap_moi TEXT NOT NULL,
                gia INTEGER NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                photo_file_id TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_requests (
                request_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                ten TEXT NOT NULL,
                phi INTEGER NOT NULL,
                thoi_gian TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                photo_file_id TEXT
            )
        """)

        # Migration cho database cũ.
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
        [KeyboardButton("👥 Khu Vực Leader"), KeyboardButton("👑 Nâng Cấp Bậc")],
        [KeyboardButton("💰 Rút Tiền"), KeyboardButton("🎧 Hỗ Trợ")],
        [KeyboardButton("🔐 Nhập CaptCha")],
    ]
    if user_id == ADMIN_ID:
        rows.insert(2, [KeyboardButton("🎛 QUẢN LÝ ADMIN")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def kt_kenh(user_id, context):
    """Kiểm tra người dùng đã tham gia kênh bắt buộc hay chưa."""
    if not KENH_YEU_CAU:
        return True
    try:
        m = await context.bot.get_chat_member(
            chat_id=KENH_YEU_CAU, user_id=user_id
        )
        return m.status in {"member", "administrator", "creator"}
    except Exception as exc:
        # Nếu bot không có quyền kiểm tra thành viên kênh, coi như chưa xác minh
        # để không cho người dùng bỏ qua bước tham gia.
        print("CHECK CHANNEL ERROR:", repr(exc))
        return False


def nut_kiem_tra_kenh():
    """Nút mở kênh + nút kiểm tra lại sau khi người dùng đã tham gia."""
    link = KENH_YEU_CAU
    if link.startswith("@"):  # Telegram URL từ username kênh
        link = "https://t.me/" + link[1:]
    elif not link.startswith("http://") and not link.startswith("https://"):
        link = "https://t.me/" + link.lstrip("/")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 THAM GIA KÊNH", url=link)],
        [InlineKeyboardButton("🔎 KIỂM TRA ĐÃ THAM GIA CHƯA", callback_data="kiem_tra_kenh")],
    ])


async def yeu_cau_tham_gia_kenh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiện yêu cầu tham gia kênh và cho phép người dùng bấm kiểm tra lại."""
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
        "2️⃣ Tham gia kênh\n"
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
        "❌ Chưa phát hiện bạn tham gia kênh. Hãy tham gia rồi bấm kiểm tra lại.",
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
    cfg = CAP_BAC_CONFIG[u["cap_bac"]]
    tk_info = u["tai_khoan"] or "Chưa liên kết"
    xac_minh = "✅ Đã xác minh" if u.get("xac_minh_nguoi_that", 0) else "🔒 Chưa xác minh"

    await update.message.reply_text(
        f"""👤 HỒ SƠ CỦA BẠN

🆔 ID: <code>{u['id']}</code>
👤 Tên: {h(u['ten'])}
👑 Cấp bậc: {h(u['cap_bac'])}
💰 Số dư: {u['so_du']:,}đ

📺 Xem hôm nay: {u['video_ngay']}/{cfg['gioi_han_xem_ngay']} video
💵 Thưởng/video: {cfg['xu_moi_video']:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
📅 Tham gia: {u['ngay_vao']}

🔗 Tài khoản rút tiền: {h(tk_info)}
🛡 Xác minh người thật: {xac_minh}""",
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
            [[InlineKeyboardButton("🎬 MỞ VIDEO TIKTOK", url=LINK_VIDEO)]]
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

    u = get_user(uid)
    if not u or not u["dang_xem"]:
        await query.answer("❌ Phiên đã hết hạn.", show_alert=True)
        return

    if context.user_data.get("watch_message_id") != message_id:
        await query.answer("❌ Phiên không hợp lệ.", show_alert=True)
        return

    await query.answer()

    reset_daily_if_needed(u)
    cfg = CAP_BAC_CONFIG[u["cap_bac"]]

    if u["video_ngay"] >= cfg["gioi_han_xem_ngay"]:
        u["dang_xem"] = False
        save_user(u)
        await query.answer("❌ Đã hết lượt hôm nay.", show_alert=True)
        return

    tien = cfg["xu_moi_video"]
    u["video_da_xem"] += 1
    u["video_ngay"] += 1
    u["so_du"] += tien
    u["dang_xem"] = False
    save_user(u)

    ancestor_id = u["ref_by"]
    for rate in (HOA_HONG["f1"], HOA_HONG["f2"], HOA_HONG["f3"]):
        if not ancestor_id:
            break
        parent = get_user(ancestor_id)
        if not parent:
            break
        hoa_hong = int(tien * rate)
        if hoa_hong > 0:
            parent["so_du"] += hoa_hong
            save_user(parent)
        ancestor_id = parent["ref_by"]

    context.user_data.pop("watch_message_id", None)
    await query.edit_message_text(
        f"""✅ <b>NHẬN THƯỞNG THÀNH CÔNG</b>

🎬 Video hôm nay: {u['video_ngay']}/{cfg['gioi_han_xem_ngay']}
⏱ Đã xem đủ: 15 giây
💰 Thưởng: +{tien:,}đ
💵 Số dư: {u['so_du']:,}đ""",
        parse_mode="HTML",
    )


async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={u['id']}"

    thong_tin_cap = ""
    for cap, cfg in CAP_BAC_CONFIG.items():
        thong_tin_cap += (
            f"👑 {cap}: {cfg['gioi_han_xem_ngay']} video/ngày — "
            f"{cfg['xu_moi_video']:,}đ/video\n"
        )

    await update.message.reply_text(
        f"""👥 <b>KHU VỰC LEADER</b>

👑 Cấp hiện tại: {h(u['cap_bac'])}
📺 Giới hạn xem: {CAP_BAC_CONFIG[u['cap_bac']]['gioi_han_xem_ngay']} video/ngày
💵 Thưởng/video: {CAP_BAC_CONFIG[u['cap_bac']]['xu_moi_video']:,}đ
👥 Người giới thiệu: {u['gioi_thieu']}

💰 HOA HỒNG CẤP DƯỚI
F1: 3% | F2: 2% | F3: 1%

📊 <b>GIỚI HẠN XEM</b>
{thong_tin_cap}
📈 <b>MỐC CẤP BẬC</b>
👤 0-29 → Thành viên
🥈 30-99 → Leader Bạc
🥇 100-299 → Leader Vàng
💎 300-499 → Leader Bạch Kim
💠 500-999 → Leader Kim Cương
👑 1.000+ → Leader Cao Thủ

🔗 <b>LINK GIỚI THIỆU:</b>
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
    ma_nap = f"{g['ma_chung']} {u['id']}"

    with db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO deposits
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
    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\nLiên hệ: @hotroxutiktok\n⏰ 8:00 - 22:00 hàng ngày",
        parse_mode="HTML",
        reply_markup=menu_chinh(update.effective_user.id),
    )


async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        return
    u["captcha_da_xac_minh"] = True
    save_user(u)
    await update.message.reply_text(
        "✅ <b>Đã xác minh thành công!</b>\n"
        "Bây giờ có thể sử dụng chức năng xem video.",
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


async def xac_minh_nguoi_that_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    u = get_user(update.effective_user.id)
    if not u:
        return

    if u.get("xac_minh_nguoi_that", 0):
        await query.answer("✅ Bạn đã được xác minh.", show_alert=True)
        return

    with db() as conn:
        old = conn.execute(
            """
            SELECT * FROM verification_requests
            WHERE user_id=? AND status='pending'
            ORDER BY thoi_gian DESC
            LIMIT 1
            """,
            (u["id"],),
        ).fetchone()

        if old:
            request_id = old["request_id"]
        else:
            request_id = f"XM{u['id']}{int(time.time() * 1000)}"
            conn.execute(
                """
                INSERT INTO verification_requests
                (request_id, user_id, ten, phi, thoi_gian, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    request_id, u["id"], u["ten"], PHI_XAC_MINH,
                    now_vn().strftime("%d/%m/%Y %H:%M"),
                ),
            )

    context.user_data["dang_xac_minh"] = request_id

    await query.edit_message_text(
        f"""🛡 <b>XÁC MINH NGƯỜI THẬT</b>

💰 <b>Phí xác minh: {PHI_XAC_MINH:,}đ</b>

🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>
Ngân hàng: <b>{h(XAC_MINH_NGAN_HANG)}</b>
Chủ TK: <b>{h(XAC_MINH_CHU_TK)}</b>
Số TK: <code>{h(XAC_MINH_SO_TK)}</code>

💵 Số tiền: <b>{PHI_XAC_MINH:,}đ</b>
📝 Nội dung CK: <code>XACMINH {u['id']}</code>

📸 Sau khi chuyển khoản, hãy <b>gửi ảnh biên lai</b> tại đây.
⏳ Admin sẽ kiểm tra giao dịch và duyệt thủ công.

⚠️ Khoản phí phải được thanh toán đúng số tiền và đúng thông tin trên. Chức năng rút chỉ được mở sau khi Admin xác nhận.""",
        parse_mode="HTML",
        reply_markup=menu_chinh(u["id"]),
    )

    # Thông báo cho admin rằng có yêu cầu xác minh mới.
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"""🛡 <b>YÊU CẦU XÁC MINH NGƯỜI THẬT</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {h(u['ten'])}
💰 Phí: {PHI_XAC_MINH:,}đ
📝 Nội dung CK: <code>XACMINH {u['id']}</code>
📋 Mã: <code>{h(request_id)}</code>

⏳ Đang chờ người dùng gửi biên lai.""",
        parse_mode="HTML",
    )

    return XAC_MINH_GUI_ANH


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
MOMO 0396037105 NGUYEN VAN A
ACB 25607451 NGUYEN VAN A

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
# ADMIN
# ============================================================
async def trang_quan_ly_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Không có quyền.")
        return

    with db() as conn:
        tong_nguoi = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        tong_cho_rut = conn.execute(
            "SELECT COUNT(*) FROM withdrawals WHERE status='pending'"
        ).fetchone()[0]
        tong_cho_nap = conn.execute(
            "SELECT COUNT(*) FROM deposits WHERE status='pending'"
        ).fetchone()[0]
        tong_cho_xac_minh = conn.execute(
            "SELECT COUNT(*) FROM verification_requests WHERE status='pending'"
        ).fetchone()[0]
        tong_so_du = conn.execute(
            "SELECT COALESCE(SUM(so_du),0) FROM users"
        ).fetchone()[0]

    await update.message.reply_text(
        f"""🎛 <b>TRANG QUẢN LÝ ADMIN</b>

👥 Tổng người dùng: <b>{tong_nguoi}</b>
⏳ Chờ rút tiền: <b>{tong_cho_rut}</b>
⏳ Chờ nạp/nâng cấp: <b>{tong_cho_nap}</b>
🛡 Chờ xác minh: <b>{tong_cho_xac_minh}</b>
💰 Tổng số dư hệ thống: <b>{tong_so_du:,}đ</b>

👇 Chọn chức năng:""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Cộng tiền 1 người", callback_data="admin_cong_tien")],
            [InlineKeyboardButton("💰 Cộng tiền TẤT CẢ", callback_data="admin_cong_tat_ca")],
            [InlineKeyboardButton("💸 Trừ tiền người dùng", callback_data="admin_tru_tien")],
            [InlineKeyboardButton("📢 Gửi thông báo", callback_data="admin_gui_tb")],
            [InlineKeyboardButton("📋 Danh sách chờ rút", callback_data="admin_ds_rut")],
            [InlineKeyboardButton("📋 Danh sách chờ nạp", callback_data="admin_ds_nap")],
            [InlineKeyboardButton("🛡 Danh sách xác minh", callback_data="admin_ds_xacminh")],
            [InlineKeyboardButton("✅ DUYỆT TẤT CẢ ĐƠN", callback_data="admin_duyet_tat_ca")],
            [InlineKeyboardButton("👥 Xem người dùng", callback_data="admin_ds_nguoi")],
        ]),
    )


async def xu_ly_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Không có quyền.", show_alert=True)
        return

    data = query.data

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
            conn.execute("BEGIN IMMEDIATE")
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
            conn.execute("BEGIN IMMEDIATE")

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

                if not user:
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

                if not user:
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

        msg = (
            "✅ <b>ĐÃ DUYỆT TẤT CẢ ĐƠN CÓ THỂ XỬ LÝ</b>\n\n"
            f"🛡 Xác minh: <b>{len(approved_verifications)}</b> đơn\n"
            f"📥 Nạp/nâng cấp: <b>{len(approved_deposits)}</b> đơn\n"
            f"💸 Rút tiền: <b>{len(approved_withdrawals)}</b> đơn\n"
            f"⚠️ Rút bỏ qua do số dư không đủ: <b>{len(skipped_withdrawals)}</b> đơn\n"
            f"⚠️ Nạp bỏ qua do người dùng không tồn tại: <b>{len(skipped_deposits)}</b> đơn"
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
                """
                SELECT * FROM withdrawals
                WHERE status='pending'
                ORDER BY thoi_gian DESC
                """
            ).fetchall()

        if not rows:
            await query.message.reply_text("✅ Không có yêu cầu chờ rút.")
            return

        text = "📋 <b>DANH SÁCH CHỜ RÚT</b>\n\n"
        for yc in rows:
            text += (
                f"<code>{h(yc['request_id'])}</code>\n"
                f"👤 {h(yc['ten'])} | 💵 {yc['so_tien']:,}đ\n"
                f"🔗 {h(yc['tai_khoan'])}\n\n"
            )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "admin_ds_nap":
        with db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM deposits
                WHERE status='pending'
                ORDER BY thoi_gian DESC
                """
            ).fetchall()

        if not rows:
            await query.message.reply_text("✅ Không có yêu cầu chờ nạp.")
            return

        text = "📋 <b>DANH SÁCH CHỜ NẠP/NÂNG CẤP</b>\n\n"
        for yc in rows:
            text += (
                f"<code>{h(yc['request_id'])}</code>\n"
                f"👤 {h(yc['ten'])} | {yc['gia']:,}đ → {h(yc['cap_moi'])}\n\n"
            )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "admin_ds_xacminh":
        with db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM verification_requests
                WHERE status='pending'
                ORDER BY thoi_gian DESC
                """
            ).fetchall()

        if not rows:
            await query.message.reply_text(
                "✅ Không có yêu cầu xác minh đang chờ."
            )
            return

        text = "🛡 <b>DANH SÁCH CHỜ XÁC MINH</b>\n\n"
        for yc in rows:
            text += (
                f"📋 <code>{h(yc['request_id'])}</code>\n"
                f"🆔 ID: <code>{yc['user_id']}</code>\n"
                f"👤 {h(yc['ten'])}\n"
                f"💰 Phí: {yc['phi']:,}đ\n"
                f"📅 {h(yc['thoi_gian'])}\n\n"
            )

        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "admin_ds_nguoi":
        rows = all_users()
        if not rows:
            await query.message.reply_text("Chưa có người dùng.")
            return

        text = "👥 <b>DANH SÁCH NGƯỜI DÙNG</b>\n\n"
        for u in rows[:100]:
            xac = "✅" if u.get("xac_minh_nguoi_that", 0) else "🔒"
            text += (
                f"🆔 {u['id']} | {h(u['ten'])}\n"
                f"💰 {u['so_du']:,}đ | {h(u['cap_bac'])} | {xac}\n\n"
            )
        await query.message.reply_text(text, parse_mode="HTML")


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
    print("BOT ERROR:", repr(context.error))


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
                pattern=r"^admin_(cong_tien|tru_tien|cong_tat_ca|gui_tb)$",
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

    # Callback Admin: duyệt đơn, xác minh, danh sách, duyệt tất cả.
    app.add_handler(
        CallbackQueryHandler(
            xu_ly_admin_callback,
            pattern=(
                r"^(duyet_nap_ok|duyet_nap_no|duyet_ok|duyet_no|"
                r"xacminh_ok|xacminh_no):.+$|"
                r"^(admin_ds_(rut|nap|xacminh|nguoi)|admin_duyet_tat_ca)$"
            ),
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

    app.add_handler(
        CallbackQueryHandler(
            nhan_thuong_callback,
            pattern=r"^nhan_thuong:.+$",
        ),
        group=0,
    )

    app.add_handler(
        CallbackQueryHandler(
            xac_minh_nguoi_that_callback,
            pattern=r"^xac_minh_nguoi_that$",
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
    app.add_handler(admin_conv, group=1)

    # Ảnh biên lai xác minh 30.000đ. Handler kiểm tra cờ trong user_data.
    app.add_handler(
        MessageHandler(filters.PHOTO, nhan_anh_xac_minh),
        group=1,
    )

    app.add_handler(
        MessageHandler(filters.Regex(r"^👤 Hồ Sơ$"), ho_so)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔍 Xem TikTok$"), xem_tiktok)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👥 Khu Vực Leader$"), khu_vuc_leader)
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


async def run_bot():
    application = build_application()

    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()

    try:
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        print("Bot đang chạy...")
        await asyncio.Event().wait()
    finally:
        if application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("Bot đã dừng.")
    except Exception as exc:
        print("BOT START ERROR:", repr(exc))
        raise