import os
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ========================================
# ĐIỀN THÔNG TIN CỦA BẠN VÀO ĐÂY
# ========================================
BOT_TOKEN = "TOKEN_CUA_BAN"  # Thay Token của bạn
ADMIN_ID = 6163458267
KENH_YEU_CAU = None  # Hoặc "@TenKenh" nếu muốn bắt tham gia kênh

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

# ========== ✅ MENU CHÍNH — ĐÃ SỬA NÚT ==========
def menu_chinh():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Hồ Sơ", callback_data="ho_so"),
            InlineKeyboardButton("🔍 Xem TikTok", callback_data="xem_tiktok")
        ],
        [
            InlineKeyboardButton("👥 Khu Vực Leader", callback_data="leader"),
            InlineKeyboardButton("👑 Nâng Cấp Bậc", callback_data="nang_cap")
        ],
        [
            InlineKeyboardButton("🎧 Hỗ Trợ", callback_data="ho_tro"),
            InlineKeyboardButton("🔐 Nhập CaptCha", callback_data="captcha")
        ],
        [InlineKeyboardButton("💰 Rút Tiền", callback_data="rut_tien")]
    ])

# ========== KIỂM TRA THAM GIA KÊNH ==========
async def kt_kenh(user_id, context):
    if not KENH_YEU_CAU:
        return True
    try:
        m = await context.bot.get_chat_member(chat_id=KENH_YEU_CAU, user_id=user_id)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

# ========== BẮT ĐẦU — NÚT TRONG TIN NHẮN ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref_by = None
    if context.args:
        try: ref_by = int(context.args[0])
        except: pass
    
    init_user(u.id, u.full_name, ref_by)
    
    if not await kt_kenh(u.id, context):
        await update.message.reply_text(
            f"🚀 Để dùng bot, vui lòng tham gia kênh trước:\n🔗 https://t.me/{KENH_YEU_CAU.replace('@','')}\n\nSau khi tham gia, gõ lại /start nhé!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Xem Kênh", url=f"https://t.me/{KENH_YEU_CAU.replace('@','')}")
            ]])
        )
        return
    
    # ✅ NÚT SẼ HIỆN NGAY BÊN DƯỚI TIN NHẮN — KHÔNG Ở Ô NHẬP
    await update.message.reply_text(
        f"👋 Xin chào, {u.first_name}!\n\n"
        "✨ TikTop View — Tăng lượt xem & tương tác TikTok ✨\n\n"
        "Chào mừng bạn đến với dịch vụ hàng đầu!\n"
        "Chúng tôi cung cấp:\n"
        "🔹 Lượt xem nhanh & ổn định\n"
        "🔹 An toàn tuyệt đối, không khóa tài khoản\n"
        "🔹 Hỗ trợ 24/7, hoàn tiền nếu lỗi\n\n"
        "👇 Chọn chức năng bên dưới để bắt đầu:",
        reply_markup=menu_chinh()  # ✅ NÚT Ở ĐÂY — GẮN VÀO TIN NHẮN
    )

# ========== HỒ SƠ ==========
async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = users[update.effective_user.id]
    await q.edit_message_text(
        f"""👤 <b>HỒ SƠ CỦA BẠN</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
🏆 Cấp bậc Leader: Thành viên

🔍 Video đã xem: {u['video_da_xem']}
📅 Tham gia: {u['ngay_vao']}""",
        parse_mode="HTML",
        reply_markup=menu_chinh()  # ✅ NÚT LUÔN Ở DƯỚI MỌI TIN NHẮN
    )

# ========== XEM TIKTOK KIẾM TIỀN ==========
async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u_id = update.effective_user.id
    u = users[u_id]
    
    if not u["captcha_da_xac_minh"]:
        await q.edit_message_text(
            "🔐 Vui lòng nhấn [Nhập CaptCha] xác minh trước!",
            reply_markup=menu_chinh()
        )
        return
    
    hom_nay = datetime.now().strftime("%d/%m/%Y")
    if u["ngay_reset"] != hom_nay:
        u["video_ngay"] = 0
        u["ngay_reset"] = hom_nay
    
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    if u["video_ngay"] >= gioi_han:
        await q.edit_message_text(
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
    
    await q.edit_message_text(
        f"""🔍 <b>XEM TIKTOK</b>

🎬 Video hôm nay: {u['video_ngay']}/{gioi_han}
💰 Thưởng: +{tien_duoc:,}đ/video
⏱ Thời gian xem: 15 giây

✅ Đã xem xong! Tích lũy: {u['so_du']:,}đ""",
        parse_mode="HTML",
        reply_markup=menu_chinh()
    )

# ========== KHU VỰC LEADER ==========
async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u_id = update.effective_user.id
    u = users[u_id]
    link = f"https://t.me/{update.get_bot().username}?start={u_id}"
    
    await q.edit_message_text(
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
        parse_mode="HTML",
        reply_markup=menu_chinh()
    )

# ========== NÂNG CẤP BẬC ==========
async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = []
    for g in GOI_NANG_CAP:
        kb.append([InlineKeyboardButton(
            f"{'🥈'if g['id']==1 else '🥇'if g['id']==2 else '💎'if g['id']==3 else '💠'} {g['ten']} — {g['nap']:,}đ",
            callback_data=f"mua_{g['id']}"
        )])
    kb.append([InlineKeyboardButton("🔙 Quay Lại", callback_data="ho_so")])
    
    await q.edit_message_text(
        "👑 <b>NÂNG CẤP BẬC</b>\n\nChọn gói bạn muốn nâng cấp 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ========== CHI TIẾT GÓI ==========
async def chi_tiet_goi(update: Update, context: ContextTypes.DEFAULT_TYPE, goi_id):
    q = update.callback_query; await q.answer()
    goi = next((g for g in GOI_NANG_CAP if g["id"]==goi_id), None)
    if not goi: return
    
    await q.edit_message_text(
        f"""{'🥈'if goi_id==1 else '🥇'if goi_id==2 else '💎'if goi_id==3 else '💠'} <b>{goi['ten'].upper()}</b>

💰 Nạp: {goi['nap']:,}đ
🔍 Xem tối đa: {goi['xem_ngay']} video/ngày
💵 Thưởng: {goi['xu_moi_video']:,}đ/video

🏦 THÔNG TIN THANH TOÁN
Ngân hàng: Vikki Digital Bank
Chủ TK: Hoang Diep Phi
Số TK: 663452138
Số tiền: {goi['nap']:,}đ
Nội dung CK: TIKTOP_{goi['ten'].replace(' ','_').upper()} {update.effective_user.id}

⚠️ Vui lòng chuyển đúng số tiền & nội dung!""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tôi đã chuyển khoản", callback_data=f"da_nap_{goi_id}")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="nang_cap")]
        ])
    )

# ========== XỬ LÝ NÚT BẤM ==========
async def xu_ly_nut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u_id = update.effective_user.id
    if u_id not in users:
        init_user(u_id, update.effective_user.full_name)
    u = users[u_id]
    data = q.data
    
    if data == "ho_so": await ho_so(update, context)
    elif data == "xem_tiktok": await xem_tiktok(update, context)
    elif data == "leader": await khu_vuc_leader(update, context)
    elif data == "nang_cap": await nang_cap(update, context)
    elif data.startswith("mua_"): await chi_tiet_goi(update, context, int(data.split("_")[-1]))
    elif data.startswith("da_nap_"):
        goi_id = int(data.split("_")[-1])
        goi = next((g for g in GOI_NANG_CAP if g["id"]==goi_id), None)
        u["da_nap"] += goi["nap"]
        u["cap_bac"] = "Leader Bạc" if goi_id==1 else "Leader Vàng" if goi_id==2 else "Leader Bạch Kim" if goi_id==3 else "Leader Kim Cương"
        await q.edit_message_text(
            f"✅ <b>Đã ghi nhận nạp {goi['nap']:,}đ!</b>\n👑 Nâng cấp {goi['ten']} thành công!",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    elif data == "ho_tro":
        await q.edit_message_text(
            "🎧 <b>HỖ TRỢ</b>\n\nLiên hệ: @Admin_TikTopView\n⏰ 8:00 - 22:00 hàng ngày",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    elif data == "captcha":
        u["captcha_da_xac_minh"] = True
        await q.edit_message_text(
            "🔐 <b>CAPTCHA</b>\n\n✅ Đã xác minh thành công! Bây giờ có thể xem video kiếm tiền.",
            parse_mode="HTML",
            reply_markup=menu_chinh()
        )
    elif data == "rut_tien":
        if u["so_du"] >= 100000:
            await q.edit_message_text(
                f"💰 <b>RÚT TIỀN</b>\n\nSố dư: {u['so_du']:,}đ\nTối thiểu rút: 100.000đ\n\nNhập số tiền & thông tin ngân hàng:",
                parse_mode="HTML",
                reply_markup=menu_chinh()
            )
        else:
            await q.edit_message_text(
                f"💰 <b>RÚT TIỀN</b>\n\nSố dư không đủ!\nHiện có: {u['so_du']:,}đ\nCần ít nhất: 100.000đ",
                parse_mode="HTML",
                reply_markup=menu_chinh()
            )

# ========== CHẠY BOT ==========
def main():
    print("="*50)
    print("🤖 TIKTOP VIEW BOT — ĐANG KHỞI ĐỘNG...")
    print(f"✅ Token: {BOT_TOKEN[:20]}...")
    print("="*50)
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(xu_ly_nut))
    
    print("✅ BOT ĐANG CHẠY! Mở Telegram gõ /start nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()