import os
import random
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)

# ========================================
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267
KENH_YEU_CAU = None
# ========================================

users = {}
CAP_BAC_CONFIG = {
    "Thành viên": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 5},
    "Leader Bạc": {"xu_moi_video": 3000, "gioi_han_xem_ngay": 8},
    "Leader Vàng": {"xu_moi_video": 3500, "gioi_han_xem_ngay": 12},
    "Leader Bạch Kim": {"xu_moi_video": 5000, "gioi_han_xem_ngay": 20},
    "Leader Kim Cương": {"xu_moi_video": 6000, "gioi_han_xem_ngay": 30},
}
HOA_HONG = {"f1": 0.03, "f2": 0.02, "f3": 0.01}

# Link video mẫu — bạn có thể thay đổi hoặc tạo ngẫu nhiên
LINK_VIDEO_MAU = "https://www.tiktok.com/@tiktok/video/1234567890123456789"

def init_user(user_id, ten, ref_by=None):
    if user_id not in users:
        users[user_id] = {
            "id": user_id, "ten": ten, "cap_bac": "Thành viên", "so_du": 0,
            "video_da_xem": 0, "video_ngay": 0, "gioi_thieu": 0, "ref_by": ref_by,
            "ngay_vao": datetime.now().strftime("%d/%m/%Y"),
            "captcha_da_xac_minh": False, "ngay_reset": datetime.now().strftime("%d/%m/%Y"),
            "dang_xem": False  # Đang trong quá trình xem chờ nhận tiền
        }
        if ref_by and ref_by in users:
            users[ref_by]["gioi_thieu"] += 1
            users[ref_by]["so_du"] += 100
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
        f"👋 Xin chào {u.first_name}!\n\n✨ TikTop View — Tăng lượt xem TikTok ✨\n👇 Chọn chức năng bên dưới:",
        reply_markup=menu_chinh()
    )

async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    await update.message.reply_text(f"""👤 <b>HỒ SƠ</b>
🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ
🔍 Video đã xem: {u['video_da_xem']}
📅 Tham gia: {u['ngay_vao']}""", parse_mode="HTML", reply_markup=menu_chinh())

# ========== ✅ XEM TIKTOK — ĐÚNG QUY TRÌNH MỚI ==========
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
            f"⏳ Đã hết lượt xem hôm nay!\nXem tối đa: {gioi_han} video/ngày\nNâng cấp để xem nhiều hơn!",
            reply_markup=menu_chinh()
        )
        return

    # Bắt đầu quy trình xem
    u["dang_xem"] = True
    tien_duoc = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]

    # Gửi link + nút bắt đầu
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Mở Link Xem Video", url=LINK_VIDEO_MAU)],
        [InlineKeyboardButton("✅ Đã Xem Xong — Nhận Tiền", callback_data=f"nhan_tien:{u_id}")]
    ])

    await update.message.reply_text(
        f"""🎬 <b>XEM VIDEO KIẾM TIỀN</b>

📌 Bước 1: Nhấn link dưới đây mở video
📌 Bước 2: Xem đủ <b>15 giây</b>
📌 Bước 3: Nhấn nút <b>Nhận Tiền</b>

💰 Thưởng: +{tien_duoc:,}đ/video
🎯 Hạn mức hôm nay: {u['video_ngay'] + 1}/{gioi_han}""",
        parse_mode="HTML", reply_markup=keyboard
    )

# ========== ✅ NHẬN TIỀN SAU KHI XEM ==========
async def nhan_tien_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if not data.startswith("nhan_tien:"):
        return

    u_id = int(data.split(":")[1])
    user_id_hien_tai = update.effective_user.id

    # Chỉ chính chủ nhận được
    if u_id != user_id_hien_tai:
        await query.answer("❌ Đây không phải phiên của bạn!", show_alert=True)
        return

    u = users[u_id]
    if not u["dang_xem"]:
        await query.answer("❌ Phiên đã hết hạn, nhấn [Xem TikTok] lại!", show_alert=True)
        return

    # Tính tiền
    tien_duoc = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]

    u["video_da_xem"] += 1
    u["video_ngay"] += 1
    u["so_du"] += tien_duoc
    u["dang_xem"] = False  # Kết thúc phiên

    # Thưởng giới thiệu cấp 1
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

async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    link = f"https://t.me/{update.get_bot().username}?start={u_id}"
    await update.message.reply_text(f"""👥 <b>KHU VỰC LEADER</b>
🏆 Cấp hiện tại: {u['cap_bac']}
👥 Người giới thiệu: {u['gioi_thieu']}
💰 Hoa hồng: F1=3% | F2=2% | F3=1%
🔗 Link của bạn: <code>{link}</code>""", parse_mode="HTML", reply_markup=menu_chinh())

async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n1️⃣ Gói Bạc 125.000đ\n2️⃣ Gói Vàng 250.000đ\n3️⃣ Gói Bạch Kim 1.000.000đ\n4️⃣ Gói Kim Cương 2.000.000đ\nNhập số chọn gói:",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

async def ho_tro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎧 Hỗ trợ: @Admin_TikTopView\n⏰ 8h-22h hàng ngày", parse_mode="HTML", reply_markup=menu_chinh())

async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    u["captcha_da_xac_minh"] = True
    await update.message.reply_text("✅ Xác minh thành công! Bắt đầu xem video kiếm tiền nhé!", parse_mode="HTML", reply_markup=menu_chinh())

async def rut_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    if u["so_du"] >= 100000:
        await update.message.reply_text(f"💰 RÚT TIỀN\nSố dư: {u['so_du']:,}đ\nTối thiểu: 100.000đ\nNhập thông tin ngân hàng:", parse_mode="HTML", reply_markup=menu_chinh())
    else:
        await update.message.reply_text(f"💰 RÚT TIỀN\nChưa đủ điều kiện!\nHiện có: {u['so_du']:,}đ\nCần ít nhất: 100.000đ", parse_mode="HTML", reply_markup=menu_chinh())

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
    else: await update.message.reply_text("❌ Chọn nút bên dưới!", reply_markup=menu_chinh())

def main():
    print("="*50)
    print("🤖 BOT ĐANG KHỞI ĐỘNG...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(nhan_tien_callback, pattern=r"^nhan_tien:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, xu_ly_nut))
    print("✅ SẴN SÀNG! Gõ /start trên Telegram nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()