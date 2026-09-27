import os
import random
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes
)

# ========================================
# ✅ THÔNG TIN ĐÃ ĐIỀN SẴN
# ========================================
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267
KENH_YEU_CAU = None  # Đặt "@TenKenh" nếu muốn bắt tham gia kênh

# ========== DỮ LIỆU HỆ THỐNG ==========
users = {}

CAP_BAC_CONFIG = {
    "Thành viên": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 5},
    "Leader Bạc": {"xu_moi_video": 3000, "gioi_han_xem_ngay": 8},
    "Leader Vàng": {"xu_moi_video": 3500, "gioi_han_xem_ngay": 12},
    "Leader Bạch Kim": {"xu_moi_video": 5000, "gioi_han_xem_ngay": 20},
    "Leader Kim Cương": {"xu_moi_video": 6000, "gioi_han_xem_ngay": 30},
}

GOI_NANG_CAP = [
    {"id": 1, "ten": "Gói Bạc", "nap": 125000, "xu_moi_video": 2500, "xem_ngay": 5},
    {"id": 2, "ten": "Gói Vàng", "nap": 250000, "xu_moi_video": 2500, "xem_ngay": 10},
    {"id": 3, "ten": "Gói Bạch Kim", "nap": 1000000, "xu_moi_video": 5000, "xem_ngay": 20},
    {"id": 4, "ten": "Gói Kim Cương", "nap": 2000000, "xu_moi_video": 6000, "xem_ngay": 30},
]

HOA_HONG = {"f1": 0.03, "f2": 0.02, "f3": 0.01}

# ========== KHỞI TẠO NGƯỜI DÙNG ==========
def init_user(user_id, ten, ref_by=None):
    if user_id not in users:
        users[user_id] = {
            "id": user_id,
            "ten": ten,
            "cap_bac": "Thành viên",
            "so_du": 0,
            "video_da_xem": 0,
            "video_ngay": 0,
            "gioi_thieu": 0,
            "ref_by": ref_by,
            "f1_thu_nhap": 0,
            "da_nap": 0,
            "ngay_vao": datetime.now().strftime("%d/%m/%Y"),
            "captcha_da_xac_minh": False,
            "ngay_reset": datetime.now().strftime("%d/%m/%Y")
        }
        if ref_by and ref_by in users:
            users[ref_by]["gioi_thieu"] += 1
            users[ref_by]["so_du"] += 100
    return users[user_id]

# ========== MENU NÚT Ở DƯỚI MÀN HÌNH ==========
def menu_chinh():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("👤 Hồ Sơ"), KeyboardButton("🔍 Xem TikTok")],
            [KeyboardButton("👥 Khu Vực Leader"), KeyboardButton("👑 Nâng Cấp Bậc")],
            [KeyboardButton("🎧 Hỗ Trợ"), KeyboardButton("🔐 Nhập CaptCha")],
            [KeyboardButton("💰 Rút Tiền")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# ========== KIỂM TRA KÊNH ==========
async def kt_kenh(user_id, context):
    if not KENH_YEU_CAU:
        return True
    try:
        m = await context.bot.get_chat_member(chat_id=KENH_YEU_CAU, user_id=user_id)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

# ========== BẮT ĐẦU ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref_by = None
    if context.args:
        try: ref_by = int(context.args[0])
        except: pass

    init_user(u.id, u.full_name, ref_by)

    if not await kt_kenh(u.id, context):
        await update.message.reply_text(
            f"🚀 Để dùng bot, vui lòng tham gia kênh trước:\n🔗 https://t.me/{KENH_YEU_CAU.replace('@','')}\n\nSau khi tham gia, gõ lại /start nhé!"
        )
        return

    await update.message.reply_text(
        f"👋 Xin chào, {u.first_name}!\n\n"
        "✨ TikTop View — Tăng lượt xem & tương tác TikTok ✨\n\n"
        "Chào mừng bạn đến với dịch vụ hàng đầu!\n"
        "Chúng tôi cung cấp:\n"
        "🔹 Lượt xem nhanh & ổn định\n"
        "🔹 An toàn tuyệt đối, không khóa tài khoản\n"
        "🔹 Hỗ trợ 24/7, hoàn tiền nếu lỗi\n\n"
        "👇 Chọn chức năng bên dưới để bắt đầu:",
        reply_markup=menu_chinh()
    )

# ========== HỒ SƠ ==========
async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    await update.message.reply_text(
        f"""👤 <b>HỒ SƠ CỦA BẠN</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
🏆 Cấp bậc Leader: Thành viên

🔍 Video đã xem: {u['video_da_xem']}
📅 Tham gia: {u['ngay_vao']}""",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== XEM TIKTOK ==========
async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]

    if not u["captcha_da_xac_minh"]:
        await update.message.reply_text("🔐 Vui lòng nhấn [Nhập CaptCha] xác minh trước!", reply_markup=menu_chinh())
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

    tien_duoc = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]
    u["video_da_xem"] += 1
    u["video_ngay"] += 1
    u["so_du"] += tien_duoc

    if u["ref_by"] and u["ref_by"] in users:
        users[u["ref_by"]]["so_du"] += int(tien_duoc * HOA_HONG["f1"])

    await update.message.reply_text(
        f"""🔍 <b>XEM TIKTOK</b>

🎬 Video hôm nay: {u['video_ngay']}/{gioi_han}
💰 Thưởng: +{tien_duoc:,}đ/video
⏱ Thời gian xem: 15 giây

✅ Đã xem xong! Tích lũy: {u['so_du']:,}đ""",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== KHU VỰC LEADER ==========
async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    link = f"https://t.me/{update.get_bot().username}?start={u_id}"

    await update.message.reply_text(
        f"""👥 <b>KHU VỰC LEADER</b>

🏆 Cấp hiện tại: {u['cap_bac']}
👥 Người giới thiệu: {u['gioi_thieu']}

💰 HOA HỒNG XEM VIDEO CẤP DƯỚI
F1: 3% | F2: 2% | F3: 1%

📈 MỐC CẤP BẬC
0-29 người → Thành viên
30-99 người → Leader Bạc
100-299 người → Leader Vàng
300+ người → Leader Bạch Kim

🔗 LINK GIỚI THIỆU CỦA BẠN:
<code>{link}</code>""",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== NÂNG CẤP BẬC ==========
async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n\nChọn gói bạn muốn nâng cấp:\n\n"
        "1️⃣ Gói Bạc — 125.000đ\n"
        "2️⃣ Gói Vàng — 250.000đ\n"
        "3️⃣ Gói Bạch Kim — 1.000.000đ\n"
        "4️⃣ Gói Kim Cương — 2.000.000đ\n\n"
        "Nhập số 1, 2, 3 hoặc 4 để chọn gói.",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== HỖ TRỢ ==========
async def ho_tro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\nLiên hệ: @Admin_TikTopView\n⏰ 8:00 - 22:00 hàng ngày",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== CAPTCHA ==========
async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    u["captcha_da_xac_minh"] = True
    await update.message.reply_text(
        "🔐 <b>CAPTCHA</b>\n\n✅ Đã xác minh thành công! Bây giờ có thể xem video kiếm tiền.",
        parse_mode="HTML", reply_markup=menu_chinh()
    )

# ========== RÚT TIỀN ==========
async def rut_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    if u["so_du"] >= 100000:
        await update.message.reply_text(
            f"💰 <b>RÚT TIỀN</b>\n\nSố dư: {u['so_du']:,}đ\nTối thiểu rút: 100.000đ\n\nNhập số tiền & thông tin ngân hàng:",
            parse_mode="HTML", reply_markup=menu_chinh()
        )
    else:
        await update.message.reply_text(
            f"💰 <b>RÚT TIỀN</b>\n\nSố dư không đủ!\nHiện có: {u['so_du']:,}đ\nCần ít nhất: 100.000đ",
            parse_mode="HTML", reply_markup=menu_chinh()
        )

# ========== XỬ LÝ NÚT BẤM ==========
async def xu_ly_nut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id not in users:
        init_user(u_id, update.effective_user.full_name)

    text = update.effective_message.text

    if text == "👤 Hồ Sơ":
        await ho_so(update, context)
    elif text == "🔍 Xem TikTok":
        await xem_tiktok(update, context)
    elif text == "👥 Khu Vực Leader":
        await khu_vuc_leader(update, context)
    elif text == "👑 Nâng Cấp Bậc":
        await nang_cap(update, context)
    elif text == "🎧 Hỗ Trợ":
        await ho_tro(update, context)
    elif text == "🔐 Nhập CaptCha":
        await captcha(update, context)
    elif text == "💰 Rút Tiền":
        await rut_tien(update, context)
    else:
        await update.message.reply_text(
            "❌ Lệnh không hợp lệ, vui lòng chọn nút bên dưới.",
            reply_markup=menu_chinh()
        )

# ========== CHẠY BOT ==========
def main():
    print("="*50)
    print("🤖 TIKTOP VIEW BOT — ĐANG KHỞI ĐỘNG...")
    print(f"✅ Admin ID: {ADMIN_ID}")
    print(f"✅ Token: {BOT_TOKEN[:20]}...")
    print("="*50)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, xu_ly_nut))

    print("✅ BOT ĐANG CHẠY! Mở Telegram gõ /start nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()