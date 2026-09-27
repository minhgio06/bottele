import os
import random
from datetime import datetime
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)

# ========================================
BOT_TOKEN = "TOKEN_CUA_BAN"
ADMIN_ID = 6163458267
KENH_YEU_CAU = None
LINK_VIDEO = "https://t.me/cayxuonline_bot"
RUT_TOI_THIEU = 50000
# Trạng thái hội thoại
NHAP_TAI_KHOAN = range(1)
ADMIN_CONG_SO_DU, ADMIN_TRU_SO_DU, ADMIN_GUI_TB, ADMIN_CONG_TAT_CA = range(10, 14)
NAP_GUI_ANH = 20
# ========================================

users = {}
danh_sach_cho_duyet = {}
nap_tien_cho_duyet = {}

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
        "so_tk": "25607451", "ma_chung": "TIKTOP BAC"
    },
    "goi_vang": {
        "ten": "Gói Vàng", "gia": 250000, "cap_moi": "Leader Vàng",
        "gioi_han_xem": 10, "tien_moi_video": 3000,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP VANG"
    },
    "goi_bachkim": {
        "ten": "Gói Bạch Kim", "gia": 1000000, "cap_moi": "Leader Bạch Kim",
        "gioi_han_xem": 20, "tien_moi_video": 3500,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP BACHKIM"
    },
    "goi_kimcuong": {
        "ten": "Gói Kim Cương", "gia": 2000000, "cap_moi": "Leader Kim Cương",
        "gioi_han_xem": 30, "tien_moi_video": 6000,
        "ngan_hang": "ACB", "chu_tk": "HA QUANG MINH",
        "so_tk": "25607451", "ma_chung": "TIKTOP KIMCUONG"
    },
}

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
            "dang_xem": False,
            "tai_khoan": None  # Lưu thông tin tài khoản rút tiền
        }
        if ref_by and ref_by in users:
            users[ref_by]["gioi_thieu"] += 1
            cap_nguoi_moi = users[ref_by]["cap_bac"]
            thuong = CAP_BAC_CONFIG[cap_nguoi_moi]["thuong_gioi_thieu"]
            users[ref_by]["so_du"] += thuong
            users[ref_by]["cap_bac"] = cap_bac_tu_so_nguoi(users[ref_by]["gioi_thieu"])
    return users[user_id]

def menu_chinh(user_id=None):
    if user_id == ADMIN_ID:
        return ReplyKeyboardMarkup([
            [KeyboardButton("👤 Hồ Sơ"), KeyboardButton("🔍 Xem TikTok")],
            [KeyboardButton("👥 Khu Vực Leader"), KeyboardButton("👑 Nâng Cấp Bậc")],
            [KeyboardButton("💰 Rút Tiền"), KeyboardButton("🎛 QUẢN LÝ ADMIN")],
            [KeyboardButton("🎧 Hỗ Trợ"), KeyboardButton("🔐 Nhập CaptCha")],
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        [KeyboardButton("👤 Hồ Sơ"), KeyboardButton("🔍 Xem TikTok")],
        [KeyboardButton("👥 Khu Vực Leader"), KeyboardButton("👑 Nâng Cấp Bậc")],
        [KeyboardButton("💰 Rút Tiền"), KeyboardButton("🎧 Hỗ Trợ")],
        [KeyboardButton("🔐 Nhập CaptCha")],
    ], resize_keyboard=True)

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
        f"🎉 CHÀO MỪNG BẠN TRỞ LẠI!\n\nVui lòng chọn chức năng:",
        reply_markup=menu_chinh(u.id)
    )

async def ho_so(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    tien_moi_video = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]
    tk_info = u["tai_khoan"] or "Chưa liên kết"
    await update.message.reply_text(f"""👤 <b>HỒ SƠ CỦA BẠN</b>

🆔 ID: <code>{u['id']}</code>
👤 Tên: {u['ten']}
👑 Cấp bậc: {u['cap_bac']}
💰 Số dư: {u['so_du']:,}đ

📺 Xem hôm nay: {u['video_ngay']}/{gioi_han} video
💵 Thưởng/video: {tien_moi_video:,}đ

👥 Người giới thiệu: {u['gioi_thieu']}
📅 Tham gia: {u['ngay_vao']}

🔗 Tài khoản rút tiền: {tk_info}""", parse_mode="HTML", reply_markup=menu_chinh(update.effective_user.id))

async def xem_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    if not u["captcha_da_xac_minh"]:
        await update.message.reply_text("🔐 Vui lòng nhấn [Nhập CaptCha] xác minh trước!", reply_markup=menu_chinh(u_id))
        return
    if u["dang_xem"]:
        await update.message.reply_text("⏳ Đang xử lý, vui lòng chờ...", reply_markup=menu_chinh(u_id))
        return
    hom_nay = datetime.now().strftime("%d/%m/%Y")
    if u["ngay_reset"] != hom_nay:
        u["video_ngay"] = 0
        u["ngay_reset"] = hom_nay
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    tien_moi_video = CAP_BAC_CONFIG[u["cap_bac"]]["xu_moi_video"]
    if u["video_ngay"] >= gioi_han:
        await update.message.reply_text(
            f"⏳ Đã hết lượt xem hôm nay!\n\n📺 Giới hạn {u['cap_bac']}: {gioi_han} video/ngày\n💵 Thưởng/video: {tien_moi_video:,}đ\n\n👉 Nâng cấp gói để xem nhiều hơn & nhận thưởng cao hơn!",
            reply_markup=menu_chinh(u_id)
        )
        return
    u["dang_xem"] = True
    hien_tai = u["video_ngay"]
    keyboard_mo = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 MỞ VIDEO TIKTOK", url=LINK_VIDEO)]])
    msg = await update.message.reply_text(
        f"""🔍 <b>XEM TIKTOK — {u['cap_bac']}</b>

📺 Video hôm nay: {hien_tai}/{gioi_han}
💰 Thưởng: {tien_moi_video:,}đ/video
⏱ Thời gian xem: 15 giây

👉 Bấm mở video và xem đủ 15 giây.
⌛ Sau 15 giây nút nhận thưởng sẽ xuất hiện.""",
        parse_mode="HTML", reply_markup=keyboard_mo
    )
    await asyncio.sleep(15)
    if not u["dang_xem"]: return
    keyboard_nhan = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ NHẬN {tien_moi_video:,}đ", callback_data=f"nhan_thuong:{u_id}:{tien_moi_video}")]])
    await msg.edit_reply_markup(reply_markup=keyboard_nhan)

async def nhan_thuong_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("nhan_thuong:"): return
    _, u_id, tien_nhan = data.split(":")
    u_id = int(u_id)
    tien_nhan = int(tien_nhan)
    if u_id != update.effective_user.id:
        await query.answer("❌ Không phải phiên của bạn!", show_alert=True)
        return
    u = users[u_id]
    if not u["dang_xem"]:
        await query.answer("❌ Đã hết hạn, nhấn [Xem TikTok] lại!", show_alert=True)
        return
    gioi_han = CAP_BAC_CONFIG[u["cap_bac"]]["gioi_han_xem_ngay"]
    u["video_da_xem"] += 1
    u["video_ngay"] += 1
    u["so_du"] += tien_nhan
    u["dang_xem"] = False
    if u["ref_by"] and u["ref_by"] in users:
        users[u["ref_by"]]["so_du"] += int(tien_nhan * HOA_HONG["f1"])
    await query.edit_message_text(
        f"""✅ <b>NHẬN THƯỞNG THÀNH CÔNG</b>

🎬 Video hôm nay: {u['video_ngay']}/{gioi_han}
⏱ Đã xem đủ: 15 giây
💰 Thưởng: +{tien_nhan:,}đ
💵 Số dư: {u['so_du']:,}đ""",
        parse_mode="HTML"
    )

async def khu_vuc_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    bot_username = await context.bot.get_me()
    link = f"https://t.me/{bot_username.username}?start={u_id}"
    
    thong_tin_cap = ""
    for cap in CAP_BAC_CONFIG:
        cfg = CAP_BAC_CONFIG[cap]
        thong_tin_cap += f"👑 {cap}: {cfg['gioi_han_xem_ngay']} video/ngày — {cfg['xu_moi_video']:,}đ/video\n"
    
    await update.message.reply_text(
        f"""👥 <b>KHU VỰC LEADER</b>

👑 Cấp hiện tại: {u['cap_bac']}
📺 Giới hạn xem: {CAP_BAC_CONFIG[u['cap_bac']]['gioi_han_xem_ngay']} video/ngày
💵 Thưởng/video: {CAP_BAC_CONFIG[u['cap_bac']]['xu_moi_video']:,}đ
👥 Người giới thiệu: {u['gioi_thieu']}

💰 HOA HỒNG XEM TIKTOK CẤP DƯỚI
F1: 3% | F2: 2% | F3: 1%

📊 <b>GIỚI HẠN XEM THEO CẤP BẬC</b>
{thong_tin_cap}
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
        parse_mode="HTML", reply_markup=menu_chinh(u_id)
    )

async def nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥈 Gói Bạc", callback_data="goi_bac")],
        [InlineKeyboardButton("🥇 Gói Vàng", callback_data="goi_vang")],
        [InlineKeyboardButton("💎 Gói Bạch Kim", callback_data="goi_bachkim")],
        [InlineKeyboardButton("💠 Gói Kim Cương", callback_data="goi_kimcuong")],
    ])
    await update.message.reply_text("""👑 <b>NÂNG CẤP BẬC</b>

👇 Chọn gói bạn muốn xem:""", parse_mode="HTML", reply_markup=keyboard)

async def xu_ly_goi_nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    u_id = update.effective_user.id
    u = users[u_id]
    
    if data not in GOI_NANG_CAP: return
    g = GOI_NANG_CAP[data]
    
    ma_nap = f"{g['ma_chung']} {u_id}"
    nap_tien_cho_duyet[ma_nap] = {
        "goi_key": data, "user_id": u_id, "ten": u["ten"],
        "cap_moi": g["cap_moi"], "gia": g["gia"],
        "thoi_gian": datetime.now().strftime("%d/%m/%Y %H:%M"), "da_gui_anh": False
    }
    
    await query.edit_message_text(
        f"""🏅 <b>{g['ten']}</b>

💰 Nạp: {g['gia']:,}đ
📺 Xem: {g['gioi_han_xem']} video TikTok/ngày
💵 {g['tien_moi_video']:,}đ / 1 video

🏦 <b>THÔNG TIN CHUYỂN KHOẢN</b>
Ngân hàng: {g['ngan_hang']}
Chủ TK: {g['chu_tk']}
Số TK: {g['so_tk']}

💵 Số tiền: {g['gia']:,}đ
📝 Nội dung CK: {ma_nap}

⚠️ Vui lòng chuyển đúng số tiền và đúng nội dung!""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Tôi đã chuyển khoản", callback_data=f"dachuyen:{ma_nap}")]
        ])
    )

async def da_chuyen_khoan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("dachuyen:"): return
    _, ma_nap = data.split(":", 1)
    
    if ma_nap not in nap_tien_cho_duyet:
        await query.answer("❌ Yêu cầu không tồn tại!", show_alert=True)
        return
    
    context.user_data["ma_nap_dang_xu_ly"] = ma_nap
    
    await query.edit_message_text(
        f"""📩 <b>XÁC NHẬN CHUYỂN KHOẢN</b>

Vui lòng gửi ảnh màn hình chuyển khoản thành công hoặc biên lai vào đây để admin kiểm tra.

📦 Gói: {nap_tien_cho_duyet[ma_nap]['goi_key'].replace('goi_','').upper()} - {nap_tien_cho_duyet[ma_nap]['gia']:,}đ""",
        parse_mode="HTML"
    )
    return NAP_GUI_ANH

async def nhan_anh_chuyen_khoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    ma_nap = context.user_data.get("ma_nap_dang_xu_ly")
    
    if not ma_nap or ma_nap not in nap_tien_cho_duyet:
        await update.message.reply_text("❌ Yêu cầu không tồn tại hoặc đã hết hạn!", reply_markup=menu_chinh(u_id))
        return ConversationHandler.END
    
    yc = nap_tien_cho_duyet[ma_nap]
    
    photo = update.effective_message.photo[-1] if update.effective_message.photo else None
    caption = f"""📢 <b>YÊU CẦU NẠP TIỀN — CHỜ DUYỆT</b>

🆔 ID: <code>{yc['user_id']}</code>
👤 Tên: {yc['ten']}
📦 Gói: {yc['goi_key'].replace('goi_','').upper()}
💵 Số tiền: {yc['gia']:,}đ
🏆 Nâng cấp lên: {yc['cap_moi']}
📅 Thời gian: {yc['thoi_gian']}
🔔 Mã: <code>{ma_nap}</code>"""
    
    nut_duyet = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ DUYỆT", callback_data=f"duyet_nap_ok:{ma_nap}"),
            InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"duyet_nap_no:{ma_nap}")
        ]
    ])
    
    if photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo.file_id,
            caption=caption, parse_mode="HTML", reply_markup=nut_duyet
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=caption,
            parse_mode="HTML", reply_markup=nut_duyet
        )
    
    yc["da_gui_anh"] = True
    
    await update.message.reply_text(
        f"""✅ <b>ĐÃ GỬI XÁC NHẬN THÀNH CÔNG!</b>

📦 Gói: {yc['goi_key'].replace('goi_','').upper()} - {yc['gia']:,}đ
⏳ Đang chờ admin duyệt...
Thời gian xử lý: trong vòng 24h""",
        parse_mode="HTML", reply_markup=menu_chinh(u_id)
    )
    
    context.user_data.pop("ma_nap_dang_xu_ly", None)
    return ConversationHandler.END

async def ho_tro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 <b>HỖ TRỢ</b>\n\nLiên hệ: @Admin\n⏰ 8:00 - 22:00 hàng ngày",
        parse_mode="HTML", reply_markup=menu_chinh(update.effective_user.id)
    )

async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users[update.effective_user.id]
    u["captcha_da_xac_minh"] = True
    await update.message.reply_text(
        "✅ <b>Đã xác minh thành công!</b>\nBây giờ có thể xem video kiếm tiền rồi nhé!",
        parse_mode="HTML", reply_markup=menu_chinh(update.effective_user.id)
    )

# === PHẦN RÚT TIỀN — THEO GIAO DIỆN ẢNH ===
async def rut_tien_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]
    
    if not u["tai_khoan"]:
        await update.message.reply_text(
            """💰 RÚT TIỀN

Bạn chưa liên kết tài khoản nhận tiền.
Vui lòng liên kết tài khoản trước khi rút tiền.""",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Liên kết tài khoản", callback_data="lien_ket_tai_khoan")
            ]])
        )
        return
    
    if u["so_du"] < RUT_TOI_THIEU:
        await update.message.reply_text(
            f"""💰 RÚT TIỀN

❌ Số dư không đủ!
Hiện có: {u['so_du']:,}đ
Yêu cầu tối thiểu: {RUT_TOI_THIEU:,}đ""",
            reply_markup=menu_chinh(u_id)
        )
        return
    
    # Đã có tài khoản & đủ tiền → tiếp tục nhập số tiền
    context.user_data["dang_rut_tien"] = True
    await update.message.reply_text(
        f"""💰 RÚT TIỀN

🔗 Tài khoản: {u['tai_khoan']}
💵 Số dư: {u['so_du']:,}đ
✅ Đủ điều kiện!

Vui lòng nhập số tiền muốn rút (tối thiểu {RUT_TOI_THIEU:,}đ):""",
        reply_markup=ReplyKeyboardRemove()
    )
    return NHAP_TAI_KHOAN

async def lien_ket_tai_khoan_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        """🔗 LIÊN KẾT TÀI KHOẢN

Vui lòng gửi thông tin tài khoản nhận tiền.

✅ Định dạng đúng:
MOMO 082682967 NGUYEN VAN A
BIDV 123456789 NGUYEN VAN A
VIETCOMBANK 987654321 NGUYEN VAN B

⚠️ Lưu ý:
• Không dùng dấu +, -, hoặc ký tự đặc biệt
• Viết hoa toàn bộ tên
• Ngăn cách bằng dấu cách""",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["dang_lien_ket"] = True
    return NHAP_TAI_KHOAN

async def nhap_thong_tin_tai_khoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    text = update.effective_message.text.strip()
    
    # Kiểm tra định dạng: ít nhất 3 phần
    parts = text.split()
    if len(parts) < 3:
        await update.message.reply_text(
            """❌ ĐỊNH DẠNG TÀI KHOẢN KHÔNG ĐÚNG

Chỉ chấp nhận định dạng:
MOMO 082682967 NGUYEN VAN A

Ví dụ trên là hợp lệ.
Không nhập dấu + hoặc ký tự đặc biệt.""",
            reply_markup=ReplyKeyboardRemove()
        )
        return NHAP_TAI_KHOAN
    
    # Kiểm tra phần số tài khoản có phải là số không
    loai_tk = parts[0].upper()
    so_tk = parts[1]
    ten_chu = " ".join(parts[2:]).upper()
    
    if not so_tk.isdigit():
        await update.message.reply_text(
            """❌ ĐỊNH DẠNG TÀI KHOẢN KHÔNG ĐÚNG

Chỉ chấp nhận định dạng:
MOMO 082682967 NGUYEN VAN A

Số tài khoản chỉ gồm chữ số, không dấu + hay chữ cái.""",
            reply_markup=ReplyKeyboardRemove()
        )
        return NHAP_TAI_KHOAN
    
    # Lưu thông tin tài khoản
    tk_hoan_hao = f"{loai_tk} {so_tk} {ten_chu}"
    users[u_id]["tai_khoan"] = tk_hoan_hao
    
    if context.user_data.get("dang_lien_ket"):
        context.user_data.pop("dang_lien_ket", None)
        await update.message.reply_text(
            f"""✅ LIÊN KẾT TÀI KHOẢN THÀNH CÔNG!

🔗 Tài khoản: {tk_hoan_hao}

Bây giờ bạn có thể rút tiền nhé!""",
            reply_markup=menu_chinh(u_id)
        )
        return ConversationHandler.END
    
    # Nếu đang trong quá trình rút tiền
    try:
        so_tien = int(text.replace(".", "").replace("đ", "").strip())
    except:
        await update.message.reply_text(
            "Vui lòng nhập số tiền rút:", reply_markup=ReplyKeyboardRemove()
        )
        return NHAP_TAI_KHOAN
    
    return await xu_ly_so_tien_rut(update, context, so_tien)

async def xu_ly_so_tien_rut(update: Update, context: ContextTypes.DEFAULT_TYPE, so_tien):
    u_id = update.effective_user.id
    u = users[u_id]
    
    if so_tien < RUT_TOI_THIEU:
        await update.message.reply_text(
            f"❌ Tối thiểu rút {RUT_TOI_THIEU:,}đ!", reply_markup=ReplyKeyboardRemove()
        )
        return NHAP_TAI_KHOAN
    if so_tien > u["so_du"]:
        await update.message.reply_text(
            "❌ Số tiền vượt quá số dư!", reply_markup=ReplyKeyboardRemove()
        )
        return NHAP_TAI_KHOAN
    
    yeu_cau_id = f"RUT{u_id}{int(datetime.now().timestamp())}"
    danh_sach_cho_duyet[yeu_cau_id] = {
        "user_id": u_id, "ten": u["ten"], "so_tien": so_tien,
        "tai_khoan": u["tai_khoan"],
        "thoi_gian": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    thong_bao_admin = f"""📢 <b>YÊU CẦU RÚT TIỀN MỚI — {yeu_cau_id}</b>

🆔 ID: <code>{u_id}</code>
👤 Tên: {u['ten']}
💵 Số tiền: {so_tien:,}đ
🔗 Tài khoản: {u['tai_khoan']}
📅 Thời gian: {danh_sach_cho_duyet[yeu_cau_id]['thoi_gian']}"""
    
    nut = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ DUYỆT", callback_data=f"duyet_ok:{yeu_cau_id}:{so_tien}"),
         InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"duyet_no:{yeu_cau_id}")]
    ])
    
    await context.bot.send_message(chat_id=ADMIN_ID, text=thong_bao_admin, parse_mode="HTML", reply_markup=nut)
    
    await update.message.reply_text(
        f"""✅ ĐÃ GỬI YÊU CẦU RÚT TIỀN!

📋 Mã: <code>{yeu_cau_id}</code>
💵 Số tiền: {so_tien:,}đ
🔗 Tài khoản: {u['tai_khoan']}
⏳ Đang chờ duyệt...""",
        parse_mode="HTML", reply_markup=menu_chinh(u_id)
    )
    
    context.user_data.pop("dang_rut_tien", None)
    return ConversationHandler.END

async def rut_tien_huy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Đã hủy.", reply_markup=menu_chinh(update.effective_user.id))
    return ConversationHandler.END

# === PHẦN ADMIN ===
async def trang_quan_ly_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id != ADMIN_ID:
        await update.message.reply_text("❌ Không có quyền!")
        return
    tong_nguoi = len(users)
    tong_cho_rut = len(danh_sach_cho_duyet)
    tong_cho_nap = len(nap_tien_cho_duyet)
    tong_so_du = sum(u["so_du"] for u in users.values())
    await update.message.reply_text(
        f"""🎛 <b>TRANG QUẢN LÝ ADMIN</b>

📊 Thống kê:
👥 Tổng người dùng: <b>{tong_nguoi}</b>
⏳ Chờ rút tiền: <b>{tong_cho_rut}</b>
⏳ Chờ nạp/nâng cấp: <b>{tong_cho_nap}</b>
💰 Tổng số dư hệ thống: <b>{tong_so_du:,}đ</b>

👇 Chọn chức năng:""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Cộng tiền cho 1 người", callback_data="admin_cong_tien")],
            [InlineKeyboardButton("💰 Cộng tiền TẤT CẢ người dùng", callback_data="admin_cong_tat_ca")],
            [InlineKeyboardButton("💸 Trừ tiền người dùng", callback_data="admin_tru_tien")],
            [InlineKeyboardButton("📢 Gửi thông báo toàn hệ thống", callback_data="admin_gui_tb")],
            [InlineKeyboardButton(f"📋 Danh sách chờ rút ({tong_cho_rut})", callback_data="admin_ds_rut")],
            [InlineKeyboardButton(f"📋 Danh sách chờ nạp ({tong_cho_nap})", callback_data="admin_ds_nap")],
            [InlineKeyboardButton("👥 Xem tất cả người dùng", callback_data="admin_ds_nguoi")],
        ])
    )

async def xu_ly_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    u_id = update.effective_user.id
    if u_id != ADMIN_ID: return

    if data.startswith("duyet_nap_ok:"):
        _, ma_nap = data.split(":")
        if ma_nap not in nap_tien_cho_duyet:
            await query.edit_message_text("❌ Không tồn tại!")
            return
        yc = nap_tien_cho_duyet[ma_nap]
        nguoi_dung_id = yc["user_id"]
        cap_moi = yc["cap_moi"]
        if nguoi_dung_id in users:
            users[nguoi_dung_id]["cap_bac"] = cap_moi
            thong_bao = f"""✅ <b>NÂNG CẤP THÀNH CÔNG!</b>

🔔 Mã: {ma_nap}
🏆 Cấp hiện tại: {cap_moi}
📺 Giới hạn xem: {CAP_BAC_CONFIG[cap_moi]['gioi_han_xem_ngay']} video/ngày
💵 Thưởng/video: {CAP_BAC_CONFIG[cap_moi]['xu_moi_video']:,}đ
✅ Đã kích hoạt thành công!"""
            await context.bot.send_message(chat_id=nguoi_dung_id, text=thong_bao, parse_mode="HTML")
            await query.edit_message_text(f"✅ Đã duyệt {ma_nap} → {yc['ten']} lên {cap_moi}!")
            del nap_tien_cho_duyet[ma_nap]

    elif data.startswith("duyet_nap_no:"):
        _, ma_nap = data.split(":")
        if ma_nap not in nap_tien_cho_duyet:
            await query.edit_message_text("❌ Không tồn tại!")
            return
        yc = nap_tien_cho_duyet[ma_nap]
        await context.bot.send_message(
            chat_id=yc["user_id"],
            text=f"""❌ <b>YÊU CẦU NÂNG CẤP BỊ TỪ CHỐI</b>

🔔 Mã: {ma_nap}
Vui lòng kiểm tra lại thông tin chuyển khoản hoặc liên hệ hỗ trợ!""",
            parse_mode="HTML"
        )
        await query.edit_message_text(f"❌ Đã từ chối {ma_nap}!")
        del nap_tien_cho_duyet[ma_nap]

    elif data.startswith("duyet_ok:"):
        _, yeu_cau_id, so_tien = data.split(":")
        so_tien = int(so_tien)
        if yeu_cau_id not in danh_sach_cho_duyet:
            await query.edit_message_text("❌ Không tồn tại!")
            return
        yc = danh_sach_cho_duyet[yeu_cau_id]
        nguoi_dung_id = yc["user_id"]
        if users[nguoi_dung_id]["so_du"] >= so_tien:
            users[nguoi_dung_id]["so_du"] -= so_tien
            await context.bot.send_message(
                chat_id=nguoi_dung_id,
                text=f"""✅ <b>RÚT TIỀN ĐƯỢC DUYỆT!</b>

📋 Mã: {yeu_cau_id}
💵 Số tiền: {so_tien:,}đ
🔗 Tài khoản: {yc['tai_khoan']}
✅ Đã chuyển! Cảm ơn bạn!""",
                parse_mode="HTML"
            )
            await query.edit_message_text(f"✅ Đã duyệt {yeu_cau_id} — Trừ {so_tien:,}đ!")
            del danh_sach_cho_duyet[yeu_cau_id]
        else:
            await query.edit_message_text("❌ Số dư không đủ!")

    elif data.startswith("duyet_no:"):
        _, yeu_cau_id = data.split(":")
        if yeu_cau_id not in danh_sach_cho_duyet:
            await query.edit_message_text("❌ Không tồn tại!")
            return
        yc = danh_sach_cho_duyet[yeu_cau_id]
        await context.bot.send_message(
            chat_id=yc["user_id"],
            text=f"""❌ <b>RÚT TIỀN BỊ TỪ CHỐI</b>

📋 Mã: {yeu_cau_id}
💵 Số tiền: {yc['so_tien']:,}đ
Vui lòng liên hệ hỗ trợ!""",
            parse_mode="HTML"
        )
        await query.edit_message_text(f"❌ Đã từ chối {yeu_cau_id}!")
        del danh_sach_cho_duyet[yeu_cau_id]

    elif data == "lien_ket_tai_khoan":
        return await lien_ket_tai_khoan_bat_dau(update, context)

    elif data == "admin_cong_tien":
        await query.message.reply_text("""💰 <b>CỘNG TIỀN CHO 1 NGƯỜI DÙNG</b>

Nhập ID người dùng + số tiền (VD: 123456789 500000)""", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        context.user_data["admin_hanh_dong"] = "cong"
        return ADMIN_CONG_SO_DU

    elif data == "admin_cong_tat_ca":
        await query.message.reply_text("""💰 <b>CỘNG TIỀN CHO TẤT CẢ NGƯỜI DÙNG</b>

Nhập số tiền muốn cộng cho mọi người (VD: 100000)""", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        context.user_data["admin_hanh_dong"] = "cong_tat_ca"
        return ADMIN_CONG_TAT_CA

    elif data == "admin_tru_tien":
        await query.message.reply_text("""💸 <b>TRỪ TIỀN NGƯỜI DÙNG</b>

Nhập ID + số tiền (VD: 123456789 100000)""", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        context.user_data["admin_hanh_dong"] = "tru"
        return ADMIN_TRU_SO_DU

    elif data == "admin_gui_tb":
        await query.message.reply_text("""📢 <b>GỬI THÔNG BÁO TOÀN HỆ THỐNG</b>

Nhập nội dung thông báo:""", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return ADMIN_GUI_TB

    elif data == "admin_ds_rut":
        if not danh_sach_cho_duyet:
            await query.message.reply_text("✅ Không có yêu cầu chờ rút!")
            return
        nd = "📋 <b>DANH SÁCH CHỜ RÚT</b>\n\n"
        for ma, yc in danh_sach_cho_duyet.items():
            nd += f"<code>{ma}</code>\n👤 {yc['ten']} | 💵 {yc['so_tien']:,}đ\n🔗 {yc['tai_khoan']}\n\n"
        await query.message.reply_text(nd, parse_mode="HTML")
    elif data == "admin_ds_nap":
        if not nap_tien_cho_duyet:
            await query.message.reply_text("✅ Không có yêu cầu chờ nạp!")
            return
        nd = "📋 <b>DANH SÁCH CHỜ NẠP/NÂNG CẤP</b>\n\n"
        for ma, yc in nap_tien_cho_duyet.items():
            nd += f"<code>{ma}</code>\n👤 {yc['ten']} | {yc['gia']:,}đ → {yc['cap_moi']}\n"
        await query.message.reply_text(nd, parse_mode="HTML")
    elif data == "admin_ds_nguoi":
        if not users:
            await query.message.reply_text("Chưa có ai!")
            return
        nd = "👥 <b>DANH SÁCH NGƯỜI DÙNG</b>\n\n"
        for uid, u in list(users.items())[:50]:
            nd += f"🆔 {uid} | {u['ten']} | 💰 {u['so_du']:,}đ | {u['cap_bac']}\n"
        await query.message.reply_text(nd, parse_mode="HTML")

async def admin_xu_ly_cong_tru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id != ADMIN_ID: return
    hanh_dong = context.user_data.get("admin_hanh_dong")
    text = update.effective_message.text.strip()
    
    if hanh_dong == "cong_tat_ca":
        try: so_tien = int(text.replace(".", "").replace("đ", "").strip())
        except:
            await update.message.reply_text("❌ Nhập số tiền hợp lệ!", reply_markup=menu_chinh(u_id))
            return ConversationHandler.END
        if so_tien <= 0:
            await update.message.reply_text("❌ Số tiền phải lớn hơn 0!", reply_markup=menu_chinh(u_id))
            return ConversationHandler.END
        
        dem = 0
        for uid in users:
            users[uid]["so_du"] += so_tien
            dem += 1
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"""💰 <b>ĐƯỢC CỘNG TIỀN TỪ HỆ THỐNG!</b>

+{so_tien:,}đ vào số dư của bạn!
💵 Số dư mới: {users[uid]['so_du']:,}đ""",
                    parse_mode="HTML"
                )
            except: pass
        
        await update.message.reply_text(
            f"""✅ <b>ĐÃ CỘNG TIỀN CHO TẤT CẢ THÀNH CÔNG!</b>

👥 Số người: {dem}
💰 Mỗi người: +{so_tien:,}đ""",
            parse_mode="HTML", reply_markup=menu_chinh(u_id)
        )
        context.user_data.pop("admin_hanh_dong", None)
        return ConversationHandler.END
    
    try:
        id_nguoi_dung, so_tien = text.split()
        id_nguoi_dung = int(id_nguoi_dung)
        so_tien = int(so_tien)
    except:
        await update.message.reply_text("❌ Định dạng sai! VD: 123456789 500000", reply_markup=menu_chinh(u_id))
        return ConversationHandler.END
    if id_nguoi_dung not in users:
        await update.message.reply_text("❌ Người dùng không tồn tại!", reply_markup=menu_chinh(u_id))
        return ConversationHandler.END
    
    if hanh_dong == "cong":
        users[id_nguoi_dung]["so_du"] += so_tien
        await update.message.reply_text(
            f"""✅ <b>ĐÃ CỘNG TIỀN THÀNH CÔNG!</b>

🆔 ID: {id_nguoi_dung}
💰 Cộng: +{so_tien:,}đ
💵 Số dư mới: {users[id_nguoi_dung]['so_du']:,}đ""",
            parse_mode="HTML", reply_markup=menu_chinh(u_id)
        )
        await context.bot.send_message(
            chat_id=id_nguoi_dung,
            text=f"""💰 <b>ĐƯỢC CỘNG TIỀN!</b>

+{so_tien:,}đ vào số dư của bạn!
💵 Số dư mới: {users[id_nguoi_dung]['so_du']:,}đ""",
            parse_mode="HTML"
        )
    elif hanh_dong == "tru":
        if users[id_nguoi_dung]["so_du"] < so_tien:
            await update.message.reply_text("❌ Số dư không đủ!", reply_markup=menu_chinh(u_id))
            return ConversationHandler.END
        users[id_nguoi_dung]["so_du"] -= so_tien
        await update.message.reply_text(
            f"""✅ <b>ĐÃ TRỪ TIỀN THÀNH CÔNG!</b>

🆔 ID: {id_nguoi_dung}
💸 Trừ: -{so_tien:,}đ
💵 Số dư mới: {users[id_nguoi_dung]['so_du']:,}đ""",
            parse_mode="HTML", reply_markup=menu_chinh(u_id)
        )
        await context.bot.send_message(
            chat_id=id_nguoi_dung,
            text=f"""💸 <b>BỊ TRỪ TIỀN</b>

-{so_tien:,}đ khỏi số dư!
💵 Số dư mới: {users[id_nguoi_dung]['so_du']:,}đ""",
            parse_mode="HTML"
        )
    context.user_data.pop("admin_hanh_dong", None)
    return ConversationHandler.END

async def admin_xu_ly_gui_tb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id != ADMIN_ID: return
    noi_dung = update.effective_message.text
    thanh_cong = 0
    for uid in list(users.keys()):
        try:
            await context.bot.send_message(chat_id=uid, text=f"""📢 <b>THÔNG BÁO HỆ THỐNG</b>

{noi