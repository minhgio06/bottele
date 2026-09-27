from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ✅ ĐÃ CẬP NHẬT THÔNG TIN CỦA BẠN
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267

# ========== DANH SÁCH GÓI DỊCH VỤ ==========
GOI_DICH_VU = [
    {"id": 1, "ten": "Gói 100 Lượt Xem", "gia": 15000, "mo_ta": "Nhanh chóng, ổn định, không giảm"},
    {"id": 2, "ten": "Gói 500 Lượt Xem", "gia": 60000, "mo_ta": "Tăng tương tác tự nhiên"},
    {"id": 3, "ten": "Gói 1000 Lượt Xem", "gia": 100000, "mo_ta": "Phổ biến nhanh, an toàn tài khoản"},
    {"id": 4, "ten": "Gói 5000 Lượt Xem", "gia": 450000, "mo_ta": "Tiết kiệm nhất, ưu tiên hiển thị"},
]

# ========== MENU NÚT BẤM ==========
def tao_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 Xem Dịch Vụ")],
            [KeyboardButton("🛒 Đặt Hàng"), KeyboardButton("💳 Thanh Toán")],
            [KeyboardButton("📞 Hỗ Trợ")]
        ],
        resize_keyboard=True
    )

# ========== BẮT ĐẦU ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Xin chào {user.first_name}!\n\n"
        "✨ TikTop View — Tăng lượt xem & tương tác TikTok ✨\n\n"
        "Chúng tôi cung cấp dịch vụ tăng lượt xem nhanh chóng, ổn định & an toàn.\n"
        "Chọn chức năng bên dưới để bắt đầu 👇",
        reply_markup=tao_menu()
    )

# ========== XEM DỊCH VỤ ==========
async def xem_dich_vu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 === DANH SÁCH DỊCH VỤ ===\n\n"
    for g in GOI_DICH_VU:
        text += f"🔹 {g['id']}. {g['ten']}\n"
        text += f"   💰 Giá: {g['gia']:,} VNĐ\n"
        text += f"   📝 {g['mo_ta']}\n"
        text += f"   → Gõ /dat{g['id']}\n\n"
    text += "💡 Ví dụ: muốn đặt Gói 1 → gõ /dat1"
    await update.message.reply_text(text)

# ========== ĐẶT HÀNG ==========
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

# ========== XỬ LÝ TIN NHẮN ==========
async def nhan_tin_nhan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    goi = context.user_data.get("goi_dang_chon")
    
    if goi:
        link = update.message.text.strip()
        user = update.effective_user
        thong_bao = f"""
🛒 === ĐƠN HÀNG MỚI ===

👤 Khách: {user.first_name}
🆔 ID: {user.id}
📌 Tên: @{user.username or "không có"}

📦 Dịch vụ: {goi['ten']}
💰 Thành tiền: {goi['gia']:,} VNĐ
🔗 Link video: {link}
"""
        await update.message.reply_text(
            f"✅ Đơn hàng đã ghi nhận!\n{thong_bao}\n"
            "💳 Vui lòng thanh toán:\n"
            "🏦 Vietcombank - 123456789 - NGUYEN VAN A\n"
            "💵 Số tiền: " + f"{goi['gia']:,}" + " VNĐ\n"
            "📝 Nội dung: " + goi['ten'] + "\n"
            "Gửi ảnh biên lai ở đây để kích hoạt! 🚀"
        )
        # Gửi thông báo cho Admin
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=thong_bao)
        except Exception as e:
            print(f"Không gửi được thông báo cho Admin: {e}")
        context.user_data.clear()
        return

    t = update.message.text
    if t == "📋 Xem Dịch Vụ" or t == "/dichvu":
        await xem_dich_vu(update, context)
    elif t == "🛒 Đặt Hàng":
        await update.message.reply_text("👉 Xem danh sách dịch vụ trước:\n📋 Nhấn 'Xem Dịch Vụ' nhé!")
    elif t == "💳 Thanh Toán":
        await update.message.reply_text(
            "💳 === THÔNG TIN THANH TOÁN ===\n\n"
            "🏦 Vietcombank\n"
            "📌 Số tài khoản: 123456789\n"
            "👤 Tên: NGUYEN VAN A\n"
            "💵 Chờ xác nhận đơn hàng để biết số tiền chính xác\n"
            "📝 Nội dung chuyển khoản: Tên gói + Link video"
        )
    elif t == "📞 Hỗ Trợ":
        await update.message.reply_text(
            "📞 === HỖ TRỢ KHÁCH HÀNG ===\n\n"
            "💬 Liên hệ: @Admin_TikTopView\n"
            "⏰ Hoạt động: 8:00 - 22:00 hàng ngày\n"
            "📩 Phản hồi nhanh nhất trong 15 phút!"
        )
    else:
        await update.message.reply_text(
            "⚠️ Tôi không hiểu yêu cầu này.\n"
            "Chọn chức năng từ menu bên dưới nhé 👇",
            reply_markup=tao_menu()
        )

# ========== CHẠY BOT ==========
def main():
    print("🔄 Đang khởi động TikTop View...")
    print(f"✅ Token: {BOT_TOKEN[:15]}...")
    print(f"✅ Admin ID: {ADMIN_ID}")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dichvu", xem_dich_vu))
    app.add_handler(CommandHandler("dat", dat_hang))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_tin_nhan))

    print("✅ BOT ĐANG CHẠY! Mở Telegram thử /start nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()