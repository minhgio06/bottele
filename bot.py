import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ===== CẤU HÌNH =====
BOT_TOKEN = os.getenv("8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA")
ADMIN_ID = int(os.getenv("6163458267", "0"))

# ===== DANH SÁCH GÓI DỊCH VỤ =====
GOI_DICH_VU = [
    {"id": 1, "ten": "Gói 100 Lượt Xem", "gia": 15000, "mo_ta": "Nhanh chóng, ổn định, không giảm"},
    {"id": 2, "ten": "Gói 500 Lượt Xem", "gia": 60000, "mo_ta": "Tăng tương tác tự nhiên"},
    {"id": 3, "ten": "Gói 1000 Lượt Xem", "gia": 100000, "mo_ta": "Phổ biến nhanh, an toàn tài khoản"},
    {"id": 4, "ten": "Gói 5000 Lượt Xem", "gia": 450000, "mo_ta": "Tiết kiệm nhất, ưu tiên hiển thị"},
]

# ===== MENU NÚT BẤM =====
def tao_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 Xem Dịch Vụ")],
            [KeyboardButton("🛒 Đặt Hàng"), KeyboardButton("💳 Thanh Toán")],
            [KeyboardButton("📞 Hỗ Trợ")]
        ],
        resize_keyboard=True
    )

# ===== BẮT ĐẦU =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Xin chào {user.first_name}!\n\n"
        "✨ TikTop View — Tăng lượt xem & tương tác TikTok ✨\n\n"
        "Chúng tôi cung cấp dịch vụ tăng lượt xem nhanh chóng, ổn định & an toàn.\n"
        "Chọn chức năng bên dưới để bắt đầu 👇",
        reply_markup=tao_menu()
    )

# ===== XEM DỊCH VỤ =====
async def xem_dich_vu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 === DANH SÁCH DỊCH VỤ ===\n\n"
    for g in GOI_DICH_VU:
        text += f"🔹 {g['id']}. {g['ten']}\n"
        text += f"   💰 Giá: {g['gia']:,} VNĐ\n"
        text += f"   📝 {g['mo_ta']}\n"
        text += f"   → Gõ /dat{g['id']} để đặt\n\n"
    text += "💡 Ví dụ: muốn đặt Gói 1 → gõ /dat1"
    await update.message.reply_text(text)

# ===== ĐẶT HÀNG =====
async def dat_hang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ma = int(update.message.text.replace("/dat", ""))
        goi = next((g for g in GOI_DICH_VU if g["id"] == ma), None)
    except:
        await update.message.reply_text("❌ Lệnh không hợp lệ! Gõ ví dụ: /dat1")
        return
    
    if not goi:
        await update.message.reply_text("❌ Gói dịch vụ không tồn tại!")
        return

    context.user_data["goi_dang_chon"] = goi
    await update.message.reply_text(
        f"✅ Bạn chọn: {goi['ten']}\n"
        f"💰 Thành tiền: {goi['gia']:,} VNĐ\n\n"
        "👉 Vui lòng gửi LINK VIDEO TikTok của bạn:"
    )

# ===== NHẬN LINK & XÁC NHẬN =====
async def nhan_tin_nhan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    goi = context.user_data.get("goi_dang_chon")
    if not goi:
        text = update.message.text
        if text == "📋 Xem Dịch Vụ":
            await xem_dich_vu(update, context)
        elif text == "🛒 Đặt Hàng":
            await update.message.reply_text("👉 Xem danh sách dịch vụ trước:\n📋 Nhấn nút trên hoặc gõ /dichvu")
        elif text == "💳 Thanh Toán":
            await update.message.reply_text(
                "💳 === THÔNG TIN THANH TOÁN ===\n\n"
                "🏦 Ngân hàng: Vietcombank\n"
                "📌 Số tài khoản: 1234567890\n"
                "👤 Tên: NGUYEN VAN A\n"
                "💵 Số tiền: Chờ xác nhận đơn hàng\n\n"
                "Nội dung chuyển khoản: [Tên gói] + [Link video]\n"
                "Gửi ảnh biên lai cho chúng tôi để kích hoạt! ✅"
            )
        elif text == "📞 Hỗ Trợ":
            await update.message.reply_text(
                "📞 === HỖ TRỢ KHÁCH HÀNG ===\n\n"
                "💬 Liên hệ: @minhpro19\n"
                "⏰ Hoạt động: 8:00 - 22:00 hàng ngày\n"
                "📩 Phản hồi nhanh nhất trong 15 phút!"
            )
        elif text == "/dichvu":
            await xem_dich_vu(update, context)
        else:
            await update.message.reply_text(
                "⚠️ Tôi không hiểu yêu cầu này.\n"
                "Chọn chức năng từ menu bên dưới nhé 👇",
                reply_markup=tao_menu()
            )
        return

    # Nếu đang chọn gói → nhận link
    link = update.message.text.strip()
    user = update.effective_user
    thong_bao = f"""
🛒 === ĐƠN HÀNG MỚI ===

👤 Khách: {user.first_name}
🆔 ID: {user.id}
📌 Tên người dùng: @{user.username or "không có"}

📦 Dịch vụ: {goi['ten']}
💰 Thành tiền: {goi['gia']:,} VNĐ
🔗 Link video: {link}

⏳ Trạng thái: Chờ xác nhận thanh toán
"""

    # Gửi cho khách
    await update.message.reply_text(
        f"✅ Đơn hàng đã ghi nhận!\n{thong_bao}\n"
        "💳 Vui lòng thanh toán theo thông tin:\n"
        "🏦 Vietcombank - 1234567890 - NGUYEN VAN A\n"
        "💵 Số tiền: " + str(f"{goi['gia']:,}") + " VNĐ\n"
        "📝 Nội dung: " + goi['ten'] + " + Link video\n"
        "Gửi ảnh biên lại ở đây để kích hoạt ngay! 🚀"
    )

    # Gửi cho quản trị
    if ADMIN_ID:
        await context.bot.send_message(chat_id=ADMIN_ID, text=thong_bao)

    context.user_data.clear()

# ===== CHẠY BOT =====
def main():
    print("🔄 Đang khởi động TikTop View...")
    if not BOT_TOKEN:
        print("❌ Chưa đặt BOT_TOKEN!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dichvu", xem_dich_vu))
    app.add_handler(CommandHandler("dat", dat_hang))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_tin_nhan))

    print("✅ TikTop View BOT ĐANG CHẠY!")
    app.run_polling()

if __name__ == "__main__":
    main()