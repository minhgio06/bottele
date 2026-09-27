from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267

# ========== DANH SÁCH GÓI DỊCH VỤ — GIỐNG BOT MẪU ==========
GOI_DICH_VU = [
    {"id": 1, "ten": "Gói 100 Lượt Xem", "gia": 15000, "mo_ta": "✅ Nhanh chóng | Ổn định | Không giảm"},
    {"id": 2, "ten": "Gói 500 Lượt Xem", "gia": 60000, "mo_ta": "✅ Tăng tương tác tự nhiên | An toàn"},
    {"id": 3, "ten": "Gói 1000 Lượt Xem", "gia": 100000, "mo_ta": "✅ Phổ biến nhanh | Ưu tiên đề xuất"},
    {"id": 4, "ten": "Gói 5000 Lượt Xem", "gia": 450000, "mo_ta": "✅ Tiết kiệm nhất | Bền dài lâu"},
]

# ========== MENU CHÍNH — GIỐNG BOT MẪU ==========
def menu_chinh():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 Xem Dịch Vụ")],
            [KeyboardButton("💳 Nạp Tiền"), KeyboardButton("🛒 Đơn Hàng")],
            [KeyboardButton("👤 Tài Khoản"), KeyboardButton("📞 Hỗ Trợ")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Chọn chức năng bên dưới..."
    )

# ========== MENU QUAY LẠI ==========
def menu_quay_lai():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 Trở Về Trang Chủ")]],
        resize_keyboard=True
    )

# ========== TRANG CHỦ — GIỐNG BOT MẪU ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Xin chào, {user.first_name}!\n\n"
        "✨ **TikTop View** — Tăng lượt xem & tương tác TikTok ✨\n\n"
        "Chào mừng bạn đến với dịch vụ hàng đầu!\n"
        "Chúng tôi cung cấp:\n"
        "🔹 Lượt xem nhanh & ổn định\n"
        "🔹 An toàn tuyệt đối, không khóa tài khoản\n"
        "🔹 Hỗ trợ 24/7, hoàn tiền nếu lỗi\n\n"
        "👇 Chọn chức năng bên dưới để bắt đầu:",
        reply_markup=menu_chinh(),
        parse_mode="Markdown"
    )

# ========== XEM DỊCH VỤ ==========
async def xem_dich_vu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 === DANH SÁCH DỊCH VỤ ===\n\n"
    text += "Chọn gói bạn muốn mua:\n\n"
    for g in GOI_DICH_VU:
        text += f"🔸 **{g['id']}. {g['ten']}**\n"
        text += f"   💰 Giá: `{g['gia']:,}` VNĐ\n"
        text += f"   📝 {g['mo_ta']}\n"
        text += f"   ➡️ Gõ: `/mua{g['id']}`\n\n"
    text += "💡 Ví dụ: mua Gói 1 → gõ `/mua1`"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=menu_quay_lai())

# ========== BẮT ĐẦU ĐẶT HÀNG ==========
async def mua_goi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ma = int(update.message.text.replace("/mua", ""))
        goi = next((g for g in GOI_DICH_VU if g["id"] == ma), None)
    except:
        await update.message.reply_text("❌ Lệnh không hợp lệ!\nVí dụ: `/mua1`", parse_mode="Markdown")
        return
    
    if not goi:
        await update.message.reply_text("❌ Gói dịch vụ không tồn tại!")
        return

    context.user_data["goi_dang_chon"] = goi
    await update.message.reply_text(
        f"✅ **Đã chọn: {goi['ten']}**\n"
        f"💰 Thành tiền: `{goi['gia']:,}` VNĐ\n\n"
        "🔗 Vui lòng gửi **LINK VIDEO TikTok** của bạn:",
        parse_mode="Markdown",
        reply_markup=menu_quay_lai()
    )

# ========== XỬ LÝ TẤT CẢ TIN NHẮN ==========
async def xu_ly_tin_nhan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    goi_dang_chon = context.user_data.get("goi_dang_chon")
    
    # Nếu đang chọn gói → nhận link
    if goi_dang_chon:
        link = update.message.text.strip()
        user = update.effective_user
        goi = goi_dang_chon
        
        don_hang = f"""
🛒 === ĐƠN HÀNG MỚI ===

👤 Khách hàng: {user.first_name}
🆔 ID: `{user.id}`
📌 Tên tài khoản: @{user.username or "Không có"}

📦 Dịch vụ: **{goi['ten']}**
💰 Số tiền: `{goi['gia']:,}` VNĐ
🔗 Link video: {link}

⏳ Trạng thái: **Chờ xác nhận thanh toán**
"""
        # Thông báo cho khách
        await update.message.reply_text(
            f"✅ **Đơn hàng đã được tạo thành công!**\n\n{don_hang}\n"
            "💳 Vui lòng thanh toán theo thông tin sau:\n\n"
            "🏦 **Ngân hàng**: Vietcombank\n"
            "📌 **Số tài khoản**: 123456789\n"
            "👤 **Chủ tài khoản**: NGUYEN VAN A\n"
            f"💵 **Số tiền**: `{goi['gia']:,}` VNĐ\n"
            "📝 **Nội dung**: Tên gói + Link video\n\n"
            "📩 Gửi ảnh biên lai chuyển khoản vào đây để chúng tôi kích hoạt dịch vụ ngay! 🚀",
            parse_mode="Markdown",
            reply_markup=menu_chinh()
        )
        
        # Thông báo cho Admin
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🔔 === CÓ ĐƠN HÀNG MỚI ===\n{don_hang}\n📩 Kiểm tra & kích hoạt nhé!",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Không gửi được thông báo Admin: {e}")
        
        context.user_data.clear()
        return

    # Xử lý các nút bấm
    tin_nhan = update.message.text
    
    if tin_nhan == "🏠 Trở Về Trang Chủ" or tin_nhan == "/start":
        await start(update, context)
    
    elif tin_nhan == "📋 Xem Dịch Vụ":
        await xem_dich_vu(update, context)
    
    elif tin_nhan == "💳 Nạp Tiền":
        await update.message.reply_text(
            "💳 === NẠP TIỀN VÀO TÀI KHOẢN ===\n\n"
            "🏦 **Ngân hàng**: Vietcombank\n"
            "📌 **STK**: 123456789\n"
            "👤 **Tên**: NGUYEN VAN A\n\n"
            "📝 **Nội dung**: Nạp tiền + ID Telegram\n"
            f"🆔 ID của bạn: `{update.effective_user.id}`\n\n"
            "Gửi ảnh biên lai để được cộng tiền tự động!",
            parse_mode="Markdown",
            reply_markup=menu_quay_lai()
        )
    
    elif tin_nhan == "🛒 Đơn Hàng":
        await update.message.reply_text(
            "🛒 === LỊCH SỬ ĐƠN HÀNG ===\n\n"
            "Chưa có đơn hàng nào.\n"
            "Gõ `/danhsach` để xem dịch vụ và đặt hàng nhé!",
            parse_mode="Markdown",
            reply_markup=menu_quay_lai()
        )
    
    elif tin_nhan == "👤 Tài Khoản":
        user = update.effective_user
        await update.message.reply_text(
            "👤 === THÔNG TIN TÀI KHOẢN ===\n\n"
            f"📌 Tên: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"🔗 Tên người dùng: @{user.username or 'Chưa đặt'}\n\n"
            "💰 Số dư: `0` VNĐ\n"
            "💡 Nạp tiền để đặt hàng nhanh hơn!",
            parse_mode="Markdown",
            reply_markup=menu_quay_lai()
        )
    
    elif tin_nhan == "📞 Hỗ Trợ":
        await update.message.reply_text(
            "📞 === HỖ TRỢ KHÁCH HÀNG ===\n\n"
            "💬 **Admin**: @Admin_TikTopView\n"
            "⏰ **Thời gian**: 8:00 - 22:00 hàng ngày\n"
            "⚡ **Phản hồi**: Trong vòng 5-15 phút\n\n"
            "📌 Lưu ý: Không chia sẻ Token/Mật khẩu cho ai!",
            parse_mode="Markdown",
            reply_markup=menu_quay_lai()
        )
    
    elif tin_nhan == "/danhsach":
        await xem_dich_vu(update, context)
    
    else:
        await update.message.reply_text(
            "⚠️ Tôi không hiểu yêu cầu này.\n"
            "👇 Vui lòng chọn chức năng từ menu bên dưới:",
            reply_markup=menu_chinh()
        )

# ========== CHẠY BOT ==========
def main():
    print("🔄 Đang khởi động TikTop View...")
    print(f"✅ Token: {BOT_TOKEN[:20]}...")
    print(f"✅ Admin: {ADMIN_ID}")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Đăng ký lệnh
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("danhsach", xem_dich_vu))
    app.add_handler(CommandHandler("mua", mua_goi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, xu_ly_tin_nhan))
    
    print("=" * 40)
    print("✅ ✅ BOT ĐANG CHẠY HOÀN TOÀN! ✅ ✅")
    print("👉 Mở Telegram tìm bot của bạn → gõ /start")
    print("=" * 40)
    
    app.run_polling()

if __name__ == "__main__":
    main()