# --------------------------
# BOT BÁN HÀNG TELEGRAM
# Hoàn toàn tương thích Python 3.8+
# --------------------------

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# ============= THAY THÔNG TIN CỦA BẠN Ở ĐÂY =============
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"       # Thay bằng Token từ @BotFather
ADMIN_ID = 6163458267              # Thay bằng số ID từ @getmyid_bot
# ==========================================================

# DANH SÁCH SẢN PHẨM
SAN_PHAM = [
    {"id": 1, "ten": "Áo thun nam", "gia": 99000, "mo_ta": "Chất cotton mát mẻ"},
    {"id": 2, "ten": "Quần jean nữ", "gia": 199000, "mo_ta": "Kiểu dáng hiện đại"},
    {"id": 3, "ten": "Giày thể thao", "gia": 350000, "mo_ta": "Đế bền, đi nhẹ"},
]

# Các trạng thái
NHAP_SO_LUONG, NHAP_THONG_TIN = range(2)

# === Bắt đầu ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Xin chào {name}!\n"
        "🛒 CỬA HÀNG CỦA TÔI\n\n"
        "📌 Lệnh có sẵn:\n"
        "/danhsach → Xem sản phẩm\n"
        "/huongdan → Hướng dẫn mua hàng"
    )

# === Danh sách sản phẩm ===
async def danh_sach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 DANH SÁCH SẢN PHẨM:\n\n"
    for sp in SAN_PHAM:
        text += f"🔹 {sp['id']}. {sp['ten']}\n"
        text += f"   💰 Giá: {sp['gia']:,} VNĐ\n"
        text += f"   → Gõ: /mua{sp['id']}\n\n"
    text += "💡 Ví dụ: muốn mua sản phẩm số 1 → gõ /mua1"
    await update.message.reply_text(text)

# === Bắt đầu đặt hàng ===
async def mua_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ma_sp = int(update.message.text.strip().replace("/mua", ""))
        sp = next((s for s in SAN_PHAM if s["id"] == ma_sp), None)
    except Exception as e:
        await update.message.reply_text("❌ Lỗi! Gõ ví dụ: /mua1")
        return ConversationHandler.END

    if not sp:
        await update.message.reply_text("❌ Sản phẩm không tồn tại!")
        return ConversationHandler.END

    context.user_data["san_pham"] = sp
    await update.message.reply_text(
        f"✅ Bạn chọn: {sp['ten']}\n"
        f"💰 Đơn giá: {sp['gia']:,} VNĐ\n\n"
        "👉 Nhập số lượng muốn mua:"
    )
    return NHAP_SO_LUONG

# === Nhập số lượng ===
async def nhap_so_luong(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        so_luong = int(update.message.text.strip())
        if so_luong <= 0:
            raise ValueError("Số lượng âm")
    except:
        await update.message.reply_text("⚠️ Vui lòng nhập số lớn hơn 0:")
        return NHAP_SO_LUONG

    context.user_data["so_luong"] = so_luong
    sp = context.user_data["san_pham"]
    await update.message.reply_text(
        f"✅ Số lượng: {so_luong}\n"
        f"💵 Tạm tính: {sp['gia'] * so_luong:,} VNĐ\n\n"
        "👉 Nhập thông tin giao hàng:\n"
        "Họ tên + Số điện thoại + Địa chỉ"
    )
    return NHAP_THONG_TIN

# === Nhập thông tin & Xác nhận ===
async def nhap_thong_tin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thong_tin = update.message.text.strip()
    sp = context.user_data["san_pham"]
    sl = context.user_data["so_luong"]
    tong_tien = sp["gia"] * sl
    user = update.effective_user

    don_hang = f"""
🛒 === ĐƠN HÀNG MỚI ===

👤 Khách hàng: {user.first_name}
🆔 ID Telegram: {user.id}

📦 Sản phẩm: {sp['ten']}
🔢 Số lượng: {sl}
💰 Đơn giá: {sp['gia']:,} VNĐ
💵 TỔNG TIỀN: {tong_tien:,} VNĐ

📍 Thông tin giao hàng:
{thong_tin}
"""

    # Gửi cho khách
    await update.message.reply_text(
        f"✅ Đặt hàng thành công!\n{don_hang}\n"
        "Chúng tôi sẽ liên hệ xác nhận sớm nhất. Cảm ơn bạn! ❤️"
    )

    # Gửi cho chủ cửa hàng
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=don_hang)
    except Exception as e:
        print(f"Không gửi được thông báo cho quản trị: {e}")

    # Xóa dữ liệu
    context.user_data.clear()
    return ConversationHandler.END

# === Hủy đặt hàng ===
async def huy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Đã hủy đặt hàng!")
    return ConversationHandler.END

# === Hướng dẫn ===
async def huong_dan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Hướng dẫn mua hàng:\n\n"
        "1️⃣ Gõ /danhsach xem sản phẩm\n"
        "2️⃣ Gõ /mua + mã (VD: /mua1)\n"
        "3️⃣ Nhập số lượng\n"
        "4️⃣ Nhập thông tin giao hàng\n"
        "5️⃣ Hoàn thành! ✅\n\n"
        "Bạn sẽ nhận được thông báo, đồng thời tôi cũng nhận được đơn hàng."
    )

# === Chạy chương trình ===
def main():
    print("🔄 Đang khởi tạo bot...")
    
    # Kiểm tra cấu hình
    if BOT_TOKEN == "TOKEN_CUA_BAN":
        print("❌ LỖI: Bạn chưa nhập BOT_TOKEN!")
        print("   Mở file, thay TOKEN_CUA_BAN bằng Token thật từ @BotFather")
        return
    if ADMIN_ID == 123456789:
        print("⚠️ LƯU Ý: Bạn chưa đổi ADMIN_ID, thông báo đơn hàng sẽ không gửi được!")
        print("   Nhắn @getmyid_bot để lấy ID thật của bạn")

    # Tạo ứng dụng
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Xử lý đặt hàng
    dat_hang_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^/mua\d+$'), mua_bat_dau)],
        states={
            NHAP_SO_LUONG: [MessageHandler(filters.TEXT & ~filters.COMMAND, nhap_so_luong)],
            NHAP_THONG_TIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, nhap_thong_tin)],
        },
        fallbacks=[CommandHandler("huy", huy)]
    )

    # Đăng ký lệnh
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("danhsach", danh_sach))
    app.add_handler(CommandHandler("huongdan", huong_dan))
    app.add_handler(dat_hang_handler)

    print("✅ BOT ĐANG CHẠY! Nhấn Ctrl+C để dừng")
    app.run_polling()

if __name__ == "__main__":
    main()