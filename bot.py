import os
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ========== CẤU HÌNH ==========
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267

# Lưu dữ liệu người dùng
users = {}

# Cấu hình cấp bậc & gói
CAP_BAC = {
    "Thành viên": {"min_ref": 0, "min_deposit": 0, "xu_moi_video": 2500},
    "Leader Bạc": {"min_ref": 30, "min_deposit": 125000, "xu_moi_video": 3000},
    "Leader Vàng": {"min_ref": 100, "min_deposit": 250000, "xu_moi_video": 3500},
    "Leader Bạch Kim": {"min_ref": 300, "min_deposit": 1000000, "xu_moi_video": 5000},
}

GOI_NANG_CAP = [
    {"id": 1, "ten": "Gói Bạc", "nap": 125000, "xem_duoc": 5, "xu_moi_video": 2500},
    {"id": 2, "ten": "Gói Vàng", "nap": 250000, "xem_duoc": 10, "xu_moi_video": 2500},
    {"id": 3, "ten": "Gói Bạch Kim", "nap": 1000000, "xem_duoc": 20, "xu_moi_video": 5000},
    {"id": 4, "ten": "Gói Kim Cương", "nap": 2000000, "xem_duoc": 30, "xu_moi_video": 6000},
]

# ========== KHỞI TẠO NGƯỜI DÙNG ==========
def init_user(user_id, ten, ref_by=None):
    if user_id not in users:
        users[user_id] = {
            "id": user_id,
            "ten": ten,
            "cap_bac": "Thành viên",
            "so_du": 0,
            "xu": 0,
            "video_da_xem": 0,
            "gioi_thieu": 0,
            "ref_by": ref_by,
            "gioi_thieu_f1": 0,
            "gioi_thieu_f2": 0,
            "gioi_thieu_f3": 0,
            "da_nap": 0,
            "ngay_vao": datetime.now().strftime("%d/%m/%Y"),
            "dang_xem": False,
            "captcha_dung": False
        }
        # Cộng hoa hồng cho người giới thiệu
        if ref_by and ref_by in users:
            users[ref_by]["gioi_thieu"] += 1
            users[ref_by]["gioi_thieu_f1"] += 1
            users[ref_by]["so_du"] += 100
    return users[user_id]

# ========== MENU CHÍNH ==========
def menu_chinh():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Hồ Sơ", callback_data="ho_so"),
         InlineKeyboardButton("🔍 Xem TikTok", callback_data="xem_tiktok")],
        [InlineKeyboardButton("👥 Khu Vực Leader", callback_data="leader"),
         InlineKeyboardButton("👑 Nâng Cấp Bậc", callback_data="nang_cap")],
        [InlineKeyboardButton("🎧 Hỗ Trợ", callback_data="ho_tro"),
         InlineKeyboardButton("🔐 Nhập CaptCha", callback_data="captcha")],
        [InlineKeyboardButton("💰 Rút Tiền", callback_data="rut_tien")]
    ])

# ========== HỒ SƠ ==========
def text_ho_so(u):
    return f"""👤 <b>HỒ SƠ CỦA BẠN</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ
💵 Xu: {u['xu']:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
🏆 Cấp bậc Leader: {u['cap_bac']}

🔍 Video đã xem: {u['video_da_xem']}
📅 Tham gia: {u['ngay_vao']}
"""

# ========== BẮT ĐẦU ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref_by = None
    # Xử lý link giới thiệu: /start=123456
    if context.args:
        try:
            ref_by = int(context.args[0])
        except:
            pass
    init_user(u.id, u.full_name, ref_by)
    
    await update.message.reply_text(
        f"🎉 <b>CHÀO MỪNG BẠN TRỞ LẠI, {u.first_name}!</b>\n\n"
        "Vui lòng chọn chức năng bên dưới 👇",
        parse_mode="HTML",
        reply_markup=menu_chinh()
    )

# ========== XEM VIDEO TIKTOK ==========
async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = users[update.effective_user.id]
    
    if not u["captcha_dung"]:
        await query.edit_message_text(
            "🔐 Vui lòng nhập CaptCha trước khi xem video!",
            reply_markup=menu_chinh()
        )
        return
    
    if u["dang_xem"]:
        await query.edit_message_text(
            "⏳ Đang xem video... Vui lòng chờ hoàn tất!",
            reply_markup=menu_chinh()
        )
        return
    
    xu_kiem_duoc = CAP_BAC[u["cap_bac"]]["xu_moi_video"]
    u["dang_xem"] = True
    u["video_da_xem"] += 1
    u["xu"] += xu_kiem_duoc
    u["so_du"] += xu_kiem_duoc
    
    await query.edit_message_text(
        f"🔍 <b>XEM TIKTOK</b>\n\n"
        f"🎬 Video hôm nay: {u['video_da_xem']}/5\n"
        f"💰 Thưởng: +{xu_kiem_duoc:,}đ/video\n"
        f"⏱ Thời gian xem: 15 giây\n\n"
        f"✅ Đã xem xong! Tích lũy: {u['xu']:,}đ",
        parse_mode="HTML",
        reply_markup=menu_chinh()
    )
    u["dang_xem"] = False

# ========== KHU VỰC LEADER ==========
async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = users[update.effective_user.id]
    link_gioi_thieu = f"https://t.me/TikTopView_bot?start={update.effective_user.id}"
    
    text = f"""👥 <b>KHU VỰC LEADER</b>

🏆 Cấp hiện tại: {u['cap_bac']}
👥 Người giới thiệu: {u['gioi_thieu']}

💰 HOA HỒNG XEM VIDEO CẤP DƯỚI
F1: 3% | F2: 2% | F3: 1%

📈 MỐC CẤP BẬC
0-29 người → Thành viên
30-99 người → Leader Bạc
100-299 người → Leader Vàng
300+ người → Leader Bạch Kim

🎁 THƯỞNG GIỚI THIỆU
Thành viên: +100đ/người
Leader Bạc: +200đ/người
Leader Vàng: +300đ/người

🔗 LINK GIỚI THIỆU CỦA BẠN:
<code>{link_gioi_thieu}</code>
"""
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=menu_chinh())

# ========== NÂNG CẤP BẬC ==========
async def nang_cap_bac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    for g in GOI_NANG_CAP:
        keyboard.append([InlineKeyboardButton(
            f"{'🥈' if g['id']==1 else '🥇' if g['id']==2 else '💎' if g['id']==3 else '💠'} {g['ten']} — {g['nap']:,}đ",
            callback_data=f"mua_goi_{g['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Quay Lại", callback_data="ho_so")])
    
    await query.edit_message_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n\nChọn gói bạn muốn nâng cấp 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========== CHI TIẾT GÓI NÂNG CẤP ==========
async def chi_tiet_goi(update: Update, context: ContextTypes.DEFAULT_TYPE, goi_id):
    query = update.callback_query
    await query.answer()
    goi = next((g for g in GOI_NANG_CAP if g["id"] == goi_id), None)
    if not goi: return
    
    text = f"""{'🥈' if goi_id==1 else '🥇' if goi_id==2 else '💎' if goi_id==3 else '💠'} <b>{goi['ten'].upper()}</b>

💰 Nạp: {goi['nap']:,}đ
🔍 Xem tối đa: {goi['xem_duoc']} video/ngày
💵 Thưởng: {goi['xu_moi_video']:,}đ/video

🏦 THÔNG TIN THANH TOÁN
Ngân hàng: Vikki Digital Bank
Chủ TK: Hoang Diep Phi
Số TK: 663452138
Số tiền: {goi['nap']:,}đ
Nội dung CK: TIKTOP_{goi['ten'].replace(' ','_').upper()} {update.effective_user.id}

⚠️ Vui lòng chuyển đúng số tiền & nội dung!
"""
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tôi đã chuyển khoản", callback_data=f"da_chuyen_{goi_id}")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="nang_cap")]
        ])
    )

# ========== XỬ LÝ NÚT BẤM ==========
async def xu_ly_nut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    u = users.get(user_id)
    if not u:
        init_user(user_id, update.effective_user.full_name)
        u = users[user_id]
    
    data = query.data
    
    if data == "ho_so":
        await query.edit_message_text(text_ho_so(u), parse_mode="HTML", reply_markup=menu_chinh())
    
    elif data == "xem_tiktok":
        await xem_tiktok(update, context)
    
    elif data == "leader":
        await khu_vuc_leader(update, context)
    
    elif data == "nang_cap":
        await nang_cap_bac(update, context)
    
    elif data.startswith("mua_goi_"):
        goi_id = int(data.split("_")[-1])
        await chi_tiet_goi(update, context, goi_id)
    
    elif data.startswith("da_chuyen_"):
        goi_id = int(data.split("_")[-1])
        goi = next((g for g in GOI_NANG_CAP if g["id"] == goi_id), None)
        u["da_nap"] += goi["nap"]
        u["cap_bac"] = "Leader Bạc" if goi_id==1 else "Leader Vàng" if goi_id==2 else "Leader Bạch Kim" if goi_id==3 else "Leader Kim Cương"
        await query.edit_message_text(
            f"✅ <b>Đã ghi nhận nạp {goi['nap']:,}đ!</b>\n"
            f"👑 Nâng cấp lên {goi['ten']} thành công!\n"
            f"💰 Xem {goi['xem_duoc']} video/ngày, +{goi['xu_moi_video']:,}đ/video",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    
    elif data == "ho_tro":
        await query.edit_message_text(
            "🎧 <b>HỖ TRỢ KHÁCH HÀNG</b>\n\n"
            "💬 Liên hệ: @Admin_TikTopView\n"
            "⏰ 8:00 - 22:00 hàng ngày\n"
            "⚡ Phản hồi trong 5-15 phút",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    
    elif data == "captcha":
        ma = random.randint(100000, 999999)
        context.user_data["captcha_dung"] = str(ma)
        u["captcha_dung"] = True
        await query.edit_message_text(
            f"🔐 <b>NHẬP CAPTCHA</b>\n\n"
            f"Mã xác thực: <code>{ma}</code>\n"
            f"✅ Đã xác minh! Bây giờ có thể xem video kiếm tiền.",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    
    elif data == "rut_tien":
        if u["so_du"] >= 100000:
            await query.edit_message_text(
                f"💰 <b>RÚT TIỀN</b>\n\n"
                f"Số dư: {u['so_du']:,}đ\n"
                f"Tối thiểu rút: 100.000đ\n\n"
                f"Nhập số tiền & thông tin ngân hàng:",
                parse_mode="HTML",
                reply_markup=menu_chinh()
            )
        else:
            await query.edit_message_text(
                f"💰 <b>RÚT TIỀN</b>\n\n"
                f"Số dư không đủ!\n"
                f"Hiện có: {u['so_du']:,}đ\n"
                f"Cần ít nhất: 100.000đ",
                parse_mode="HTML",
                reply_markup=menu_chinh()
            )

# ========== CHẠY BOT ==========
def main():
    print("="*50)
    print("🤖 TIKTOP VIEW BOT — ĐANG KHỞI ĐỘNG...")
    print(f"✅ Token: {BOT_TOKEN[:20]}...")
    print(f"✅ Admin: {ADMIN_ID}")
    print("="*50)
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(xu_ly_nut))
    
    print("✅ BOT ĐANG CHẠY! Mở Telegram gõ /start nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()