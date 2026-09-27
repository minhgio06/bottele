import os
import random
from datetime import datetime
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)

# ========================================
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267
KENH_YEU_CAU = None
LINK_VIDEO = "https://t.me/cayxuonline_bot"
# ========================================

users = {}

CAP_BAC_CONFIG = {
    "Thành viên": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 5, "thuong_gioi_thieu": 100},
    "Leader Bạc": {"xu_moi_video": 3000, "gioi_han_xem_ngay": 8, "thuong_gioi_thieu": 200},
    "Leader Vàng": {"xu_moi_video": 3500, "gioi_han_xem_ngay": 12, "thuong_gioi_thieu": 300},
    "Leader Bạch Kim": {"xu_moi_video": 5000, "gioi_han_xem_ngay": 20, "thuong_gioi_thieu": 500},
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

GOI_NANG_CAP = [
    {"id": 1, "ten": "Gói Bạc", "nap": 125000, "cap": "Leader Bạc"},
    {"id": 2, "ten": "Gói Vàng", "nap": 250000, "cap": "Leader Vàng"},
    {"id": 3, "ten": "Gói Bạch Kim", "nap": 1000000, "cap": "Leader Bạch Kim"},
    {"id": 4, "ten": "Gói Kim Cương", "nap": 2000000, "cap": "Leader Kim Cương"},
]

HOA_HONG = {"f1": 0.03, "f2": 0.02, "f3": 0.01}

def cap_bac_tu_so_nguoi(so_nguoi):
    for ten, min_n, max_n in reversed(MOC_CAP):
        if so_nguoi >= min_n:
            return ten
    return "Thành viên"

def init_user(user_id, ten, ref_by=None):
    if user_id not in users:
        users[user_id] = {
            "id": user_id, "ten": ten, "cap_bac": "Thành viên", "so_du": 0,
            "video_da_xem": 0, "video_ngay": 0, "gioi_thieu": 0, "ref_by": ref_by,
            "ngay_vao": datetime.now().strftime("%d/%m/%Y"),
            "captcha_da_xac_minh": False, "ngay_reset": datetime.now().strftime("%d/%m/%Y"),
            "dang_xem": False
        }
        if ref_by and ref_by in users:
            users[ref_by]["gioi_thieu"] += 1
            # Tính thưởng giới thiệu dựa cấp bậc người mời
            cap_nguoi_moi = users[ref_by]["cap_bac"]
            thuong = CAP_BAC_CONFIG[cap_nguoi_moi]["thuong_gioi_thieu"]
            users[ref_by]["so_du"] += thuong
            # Cập nhật cấp bậc tự động theo số người giới thiệu
            users[ref_by]["cap_bac"] = cap_bac_tu_so_nguoi(users[ref_by]["gioi_thieu"])
    return users[user_id]

def menu_chinh():
    return ReplyKeyboardMarkup([
        [KeyboardButton("👤 Hồ Sơ"), KeyboardButton("🔍 Xem TikTok")],
        [KeyboardButton("👥 Khu Vực Leader"), KeyboardButton("👑 Nâng Cấp Bậc")],
        [KeyboardButton("🎧 Hỗ Trợ"), KeyboardButton("🔐 Nhập CaptCha")],
        [KeyboardButton("💰 Rút Tiền")]
    ], resize_keyboard=True, one_time_keyboard=False)

async def kt_kenh(user_id, context):
    if not KENH_YEU_CAU: return True
    try:
        m = await context.bot.get_chat_member(chat_id=KENH_YEU_CAU, user_id=user_id)
        return m.status in ["member", "administrator", "creator"]
    except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref_by = None
    if context.args:
        try: ref_by = int(context.args[0])
        except: pass
    init_user(u.id, u.full_name, ref_by)
    if not await kt_kenh(u.id, context):
        await update.message.reply_text(f"🚀 Tham gia kênh trước:\n🔗 https://t.me/{KENH_YEU_CAU.replace('@','')}\nSau đó gõ /start")
        return
    await update.message.reply_text(
        f"👋 Xin chào {u.first_name}!\n\n✨ CÀY ẢO RÚT THẬT ✨\n👇 Chọn chức năng bên dưới:",
        reply_markup=menu_chinh()
    )

async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    await update.message.reply_text(f"""👤 <b>HỒ SƠ CỦA BẠN</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
🔍 Video đã xem: {u['video_da_xem']}
📅 Tham gia: {u['ngay_vao']}""", parse_mode="HTML", reply_markup=menu_chinh())

# ========== ✅ XEM VIDEO ==========
async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]

    if not u["captcha_da_xac_minh"]:
        await update.message.reply_text("🔐 Vui lòng nhấn [Nhập CaptCha] xác minh trước!", reply_markup=menu_chinh())
        return

    if u["dang_xem"]:
        await update.message.reply_text("⏳ Đang chờ nhận tiền, vui lòng chờ...", reply_markup=menu_chinh())
        return

    hom_nay = datetime.now().strftime("%d/%m/%Y")
    if u["ngay_reset"] != hom_nay:
        u["video_ngay"] = 0
        u["ngay_reset"] = hom_nay

    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    if u["video_ngay"] >= gioi_han:
        await update.message.reply_text(
            f"⏳ Đã hết lượt xem hôm nay!\nXem tối đa: {gioi_han} video/ngày\nNâng cấp gói để xem nhiều hơn!",
            reply_markup=menu_chinh()
        )
        return

    u["dang_xem"] = True
    tien_duoc = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Mở Link Xem Video", url=LINK_VIDEO)],
        [InlineKeyboardButton("✅ Đã Xem Xong — Nhận Tiền", callback_data=f"nhan_tien:{u_id}")]
    ])

    await update.message.reply_text(
        f"""🎬 <b>XEM VIDEO KIẾM TIỀN</b>

📌 Bước 1: Nhấn link dưới đây mở xem
📌 Bước 2: Xem đủ <b>15 giây</b>
📌 Bước 3: Nhấn nút <b>Nhận Tiền</b>

💰 Thưởng: +{tien_duoc:,}đ/video
🎯 Hạn mức hôm nay: {u['video_ngay'] + 1}/{gioi_han}""",
        parse_mode="HTML", reply_markup=keyboard
    )

async def nhan_tien_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("nhan_tien:"): return
    u_id = int(data.split(":")[1])
    user_id_hien_tai = update.effective_user.id
    if u_id != user_id_hien_tai:
        await query.answer("❌ Đây không phải phiên của bạn!", show_alert=True)
        return
    u = users[u_id]
    if not u["dang_xem"]:
        await query.answer("❌ Phiên đã hết hạn, nhấn [Xem TikTok] lại!", show_alert=True)
        return

    tien_duoc = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    u["video_da_xem"] += 1
    u["video_ngay"] += 1
    u["so_du"] += tien_duoc
    u["dang_xem"] = False

    if u["ref_by"] and u["ref_by"] in users:
        users[u["ref_by"]]["so_du"] += int(tien_duoc * HOA_HONG["f1"])

    await query.edit_message_text(
        f"""✅ <b>NHẬN TIỀN THÀNH CÔNG</b>

💰 Đã nhận: +{tien_duoc:,}đ
💵 Số dư hiện tại: {u['so_du']:,}đ
📊 Tiến độ hôm nay: {u['video_ngay']}/{gioi_han}

👉 Nhấn [🔍 Xem TikTok] để tiếp tục kiếm tiền!""",
        parse_mode="HTML"
    )

# ========== ✅ KHU VỰC LEADER — GIỐNG ẢNH ==========
async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    bot_username = await context.bot.get_me()
    link = f"https://t.me/{bot_username.username}?start={u_id}"

    await update.message.reply_text(
        f"""👥 <b>KHU VỰC LEADER</b>

👑 Cấp hiện tại: {u['cap_bac']}
👥 Người giới thiệu: {u['gioi_thieu']}

💰 HOA HỒNG XEM TIKTOK CẤP DƯỚI
F1: 3% | F2: 2% | F3: 1%

📈 <b>MỐC CẤP BẬC</b>
👤 0-29 người → Thành viên
🥈 30-99 người → Leader Bạc
🥇 100-299 người → Leader Vàng
💎 300-499 người → Leader Bạch Kim
💠 500-999 người → Leader Kim Cương
👑 1.000+ người → Leader Cao Thủ

🎁 <b>THƯỞNG GIỚI THIỆU</b>
👤 Thành viên: +100đ/người
🥈 Leader Bạc: +200đ/người
🥇 Leader Vàng: +300đ/người
💎 Leader Bạch Kim: +500đ/người
💠 Leader Kim Cương: +1.000đ/người
👑 Leader Cao Thủ: +3.000đ/người

🔗 <b>LINK GIỚI THIỆU CỦA BẠN:</b>
<code>{link}</code>""",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== ✅ NÂNG CẤP BẬC — GIỐNG ẢNH ==========
async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥈 Gói Bạc", callback_data="goi_bac")],
        [InlineKeyboardButton("🥇 Gói Vàng", callback_data="goi_vang")],
        [InlineKeyboardButton("💎 Gói Bạch Kim", callback_data="goi_bachkim")],
        [InlineKeyboardButton("💠 Gói Kim Cương", callback_data="goi_kimcuong")],
    ])

    await update.message.reply_text(
        """👑 <b>NÂNG CẤP BẬC</b>

👇 Chọn gói bạn muốn xem:""",
        parse_mode="HTML", reply_markup=keyboard
    )

# Xử lý chọn gói nâng cấp
async def xu_ly_goi_nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    u_id = update.effective_user.id
    u = users[u_id]

    thong_tin = {
        "goi_bac": ("Gói Bạc", "125.000đ", "Leader Bạc"),
        "goi_vang": ("Gói Vàng", "250.000đ", "Leader Vàng"),
        "goi_bachkim": ("Gói Bạch Kim", "1.000.000đ", "Leader Bạch Kim"),
        "goi_kimcuong": ("Gói Kim Cương", "2.000.000đ", "Leader Kim Cương"),
    }

    ten_goi, gia, cap_moi = thong_tin[data]

    await query.edit_message_text(
        f"""👑 <b>{ten_goi}</b>

💵 Giá: {gia}
🏆 Nâng cấp lên: {cap_moi}

📌 Vui lòng chuyển khoản đến tài khoản:
🔔 Nội dung: NAP {u_id}

Sau khi chuyển, chờ admin duyệt!""",
        parse_mode="HTML"
    )

async def ho_tro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\nLiên hệ: @minhpro19\n⏰ 8:00 - 22:00 hàng ngày",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    u["captcha_da_xac_minh"] = True
    await update.message.reply_text(
        "✅ <b>Đã xác minh thành công!</b>\nBây giờ có thể xem video kiếm tiền rồi nhé!",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

async def rut_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    if u["so_du"] >= 100000:
        await update.message.reply_text(
            f"💰 <b>RÚT TIỀN</b>\n\nSố dư: {u['so_du']:,}đ\nTối thiểu rút: 100.000đ\n\nNhập thông tin ngân hàng:",
            parse_mode="HTML", reply_markup=menu_chinh()
        )
    else:
        await update.message.reply_text(
            f"💰 <b>RÚT TIỀN</b>\n\nSố dư không đủ!\nHiện có: {u['so_du']:,}đ\nCần ít nhất: 100.000đ",
            parse_mode="HTML", reply_markup=menu_chinh()
        )

async def xu_ly_nut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id not in users:
        init_user(u_id, update.effective_user.full_name)
    text = update.effective_message.text
    if text == "👤 Hồ Sơ": await ho_so(update, context)
    elif text == "🔍 Xem TikTok": await xem_tiktok(update, context)
    elif text == "👥 Khu Vực Leader": await khu_vuc_leader(update, context)
    elif text == "👑 Nâng Cấp Bậc": await nang_cap(update, context)
    elif text == "🎧 Hỗ Trợ": await ho_tro(update, context)
    elif text == "🔐 Nhập CaptCha": await captcha(update, context)
    elif text == "💰 Rút Tiền": await rut_tien(update, context)
    else: await update.message.reply_text("❌ Vui lòng chọn nút bên dưới!", reply_markup=menu_chinh())

def main():
    print("="*50)
    print("🤖 CÀY ẢO RÚT THẬT — ĐANG KHỞI ĐỘNG...")
    print("="*50)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(nhan_tien_callback, pattern=r"^nhan_tien:"))
    app.add_handler(CallbackQueryHandler(xu_ly_goi_nang_cap, pattern=r"^goi_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, xu_ly_nut))
    print("✅ SẴN SÀNG! Gõ /start trên Telegram nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()