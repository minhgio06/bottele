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
BOT_TOKEN = "8605823154:AAFOTHtkZKE01PcaDmYDbafexIwN5sj2oLA"
ADMIN_ID = 6163458267
KENH_YEU_CAU = None
LINK_VIDEO = "https://t.me/cayxuonline_bot"
RUT_TOI_THIEU = 50000  # === ĐỔI: Tối thiểu 50.000đ ===
# Trạng thái hội thoại rút tiền
NH_TEN_NGANHANG, NH_SO_TAIKHOAN, NH_TEN_CHUTAIKHOAN, NH_SO_TIEN = range(4)
# Trạng thái duyệt rút tiền
DUYET_RUT = 10
# ========================================

users = {}
rut_tien_temp = {}
danh_sach_cho_duyet = {}  # Lưu yêu cầu chờ duyệt

CAP_BAC_CONFIG = {
    "Thành viên": {"xu_moi_video": 2500, "gioi_han_xem_ngay": 2, "thuong_gioi_thieu": 100},
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
        f"👋 Xin chào {u.first_name}!\n\n✨ CÀY ẢO RÚT THẬT ✨\n👇 Chọn chức năng bên dưới:",
        reply_markup=menu_chinh(u.id)
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
📅 Tham gia: {u['ngay_vao']}""", parse_mode="HTML", reply_markup=menu_chinh(update.effective_user.id))

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
            f"⏳ Đã hết lượt xem hôm nay!\nXem tối đa: {gioi_han} video/ngày",
            reply_markup=menu_chinh(u_id)
        )
        return

    u["dang_xem"] = True
    hien_tai = u["video_ngay"]

    keyboard_mo = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MỞ VIDEO TIKTOK", url=LINK_VIDEO)]
    ])

    msg = await update.message.reply_text(
        f"""🔍 <b>XEM TIKTOK</b>

🎬 Video hôm nay: {hien_tai}/{gioi_han}
💰 Thưởng: {tien_moi_video:,}đ/video
⏱ Thời gian xem: 15 giây

👉 Bấm mở video và xem đủ 15 giây.
⌛ Sau 15 giây nút nhận thưởng sẽ tự xuất hiện.""",
        parse_mode="HTML", reply_markup=keyboard_mo
    )

    await asyncio.sleep(15)

    if not u["dang_xem"]:
        return

    keyboard_nhan = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ NHẬN {tien_moi_video:,}đ", callback_data=f"nhan_thuong:{u_id}:{tien_moi_video}")]
    ])

    await msg.edit_reply_markup(reply_markup=keyboard_nhan)

async def nhan_thuong_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if not data.startswith("nhan_thuong:"):
        return

    _, u_id, tien_nhan = data.split(":")
    u_id = int(u_id)
    tien_nhan = int(tien_nhan)
    user_hien_tai = update.effective_user.id

    if u_id != user_hien_tai:
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
        parse_mode="HTML", reply_markup=menu_chinh(u_id)
    )

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

async def xu_ly_goi_nang_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    u_id = update.effective_user.id

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
🏦 Ngân hàng: <b>ACB</b>
🔢 Số tài khoản: <b>25607451</b>
🔔 Nội dung chuyển khoản: <code>NAP {u_id}</code>

✅ Sau khi chuyển khoản, vui lòng chờ admin duyệt!""",
        parse_mode="HTML"
    )

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

# ========== ✅ RÚT TIỀN — TỐI THIỂU 50.000đ ==========
async def rut_tien_bat_dau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]

    if u["so_du"] < RUT_TOI_THIEU:
        await update.message.reply_text(
            f"💰 <b>RÚT TIỀN</b>\n\n❌ Số dư không đủ!\nHiện có: {u['so_du']:,}đ\nYêu cầu tối thiểu: {RUT_TOI_THIEU:,}đ",
            parse_mode="HTML", reply_markup=menu_chinh(u_id)
        )
        return ConversationHandler.END

    rut_tien_temp[u_id] = {}

    await update.message.reply_text(
        f"""💰 <b>RÚT TIỀN</b>

💵 Số dư: {u['so_du']:,}đ
✅ Đủ điều kiện rút tiền! Tối thiểu {RUT_TOI_THIEU:,}đ

Vui lòng nhập thông tin tài khoản nhận tiền:

🏦 Bước 1/4 — Nhập tên ngân hàng (VD: ACB, Vietcombank...)""",
        parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
    )
    return NH_TEN_NGANHANG

async def rut_tien_ten_nganhang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    ten_nganhang = update.effective_message.text
    rut_tien_temp[u_id]["ten_nganhang"] = ten_nganhang
    await update.message.reply_text(f"✅ Ngân hàng: {ten_nganhang}\n\n🔢 Bước 2/4 — Nhập số tài khoản nhận tiền:")
    return NH_SO_TAIKHOAN

async def rut_tien_so_taikhoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    so_tai_khoan = update.effective_message.text
    rut_tien_temp[u_id]["so_tai_khoan"] = so_tai_khoan
    await update.message.reply_text(f"✅ Số tài khoản: {so_tai_khoan}\n\n👤 Bước 3/4 — Nhập tên chủ tài khoản (viết hoa có dấu):")
    return NH_TEN_CHUTAIKHOAN

async def rut_tien_ten_chu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    ten_chu_tai_khoan = update.effective_message.text
    rut_tien_temp[u_id]["ten_chu_tai_khoan"] = ten_chu_tai_khoan
    await update.message.reply_text(f"✅ Tên chủ TK: {ten_chu_tai_khoan}\n\n💵 Bước 4/4 — Nhập số tiền muốn rút (tối thiểu {RUT_TOI_THIEU:,}đ):")
    return NH_SO_TIEN

async def rut_tien_so_tien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    u = users[u_id]

    try:
        so_tien = int(update.effective_message.text.replace(".", "").replace("đ", "").strip())
    except:
        await update.message.reply_text("❌ Vui lòng nhập số tiền hợp lệ!")
        return NH_SO_TIEN

    if so_tien < RUT_TOI_THIEU:
        await update.message.reply_text(f"❌ Số tiền tối thiểu là {RUT_TOI_THIEU:,}đ!")
        return NH_SO_TIEN

    if so_tien > u["so_du"]:
        await update.message.reply_text("❌ Số tiền rút lớn hơn số dư!")
        return NH_SO_TIEN

    tt = rut_tien_temp[u_id]
    yeu_cau_id = f"RUT{u_id}{int(datetime.now().timestamp())}"
    danh_sach_cho_duyet[yeu_cau_id] = {
        "user_id": u_id,
        "ten": u["ten"],
        "so_tien": so_tien,
        **tt,
        "thoi_gian": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    # === Gửi thông báo cho ADMIN có nút Duyệt/Từ chối ===
    thong_bao_admin = f"""📢 <b>YÊU CẦU RÚT TIỀN MỚI — {yeu_cau_id}</b>

🆔 ID: <code>{u_id}</code>
👤 Tên: {u['ten']}
💵 Số tiền: <b>{so_tien:,}đ</b>
🏦 Ngân hàng: {tt['ten_nganhang']}
🔢 Số TK: {tt['so_tai_khoan']}
👤 Tên chủ TK: {tt['ten_chu_tai_khoan']}
📅 Thời gian: {danh_sach_cho_duyet[yeu_cau_id]['thoi_gian']}
"""
    nut_duyet = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ DUYỆT", callback_data=f"duyet_ok:{yeu_cau_id}:{so_tien}"),
            InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"duyet_no:{yeu_cau_id}")
        ]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=thong_bao_admin, parse_mode="HTML", reply_markup=nut_duyet)

    # === Thông báo cho người dùng ===
    await update.message.reply_text(
        f"""✅ <b>ĐÃ GỬI YÊU CẦU RÚT TIỀN THÀNH CÔNG!</b>

📋 Mã yêu cầu: <code>{yeu_cau_id}</code>
💵 Số tiền: <b>{so_tien:,}đ</b>
🏦 Ngân hàng: {tt['ten_nganhang']}
🔢 Số TK: {tt['so_tai_khoan']}
👤 Tên chủ TK: {tt['ten_chu_tai_khoan']}

⏳ Đang chờ admin duyệt...
Thời gian xử lý: trong vòng 24h""",
        parse_mode="HTML", reply_markup=menu_chinh(u_id)
    )

    del rut_tien_temp[u_id]
    return ConversationHandler.END

async def rut_tien_huy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id in rut_tien_temp:
        del rut_tien_temp[u_id]
    await update.message.reply_text("❌ Đã hủy yêu cầu rút tiền.", reply_markup=menu_chinh(u_id))
    return ConversationHandler.END

# ========== ✅ QUẢN LÝ ADMIN ==========
async def trang_quan_ly_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id
    if u_id != ADMIN_ID:
        await update.message.reply_text("❌ Bạn không có quyền truy cập!")
        return

    tong_nguoi = len(users)
    tong_cho_duyet = len(danh_sach_cho_duyet)
    tong_so_du = sum(u["so_du"] for u in users.values())

    await update.message.reply_text(
        f"""🎛 <b>TRANG QUẢN LÝ ADMIN</b>

📊 Thống kê:
👥 Tổng người dùng: <b>{tong_nguoi}</b>
⏳ Yêu cầu chờ duyệt: <b>{tong_cho_duyet}</b>
💰 Tổng số dư hệ thống: <b>{tong_so_du:,}đ</b>

📋 Chọn chức năng bên dưới:""",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📋 Danh sách chờ duyệt ({tong_cho_duyet})", callback_data="admin_danh_sach")],
            [InlineKeyboardButton("📊 Xem tất cả người dùng", callback_data="admin_ds_nguoi")],
            [InlineKeyboardButton("💰 Thay đổi số dư", callback_data="admin_sua_du")],
        ])
    )

async def xu_ly_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    u_id = update.effective_user.id
    if u_id != ADMIN_ID:
        return

    # === Duyệt / Từ chối yêu cầu rút ===
    if data.startswith("duyet_ok:"):
        _, yeu_cau_id, so_tien = data.split(":")
        so_tien = int(so_tien)
        if yeu_cau_id not in danh_sach_cho_duyet:
            await query.edit_message_text("❌ Yêu cầu không tồn tại hoặc đã xử lý!")
            return
        yc = danh_sach_cho_duyet[yeu_cau_id]
        nguoi_dung_id = yc["user_id"]
        if users[nguoi_dung_id]["so_du"] >= so_tien:
            users[nguoi_dung_id]["so_du"] -= so_tien
            thong_bao = f"""✅ <b>YÊU CẦU RÚT TIỀN ĐƯỢC DUYỆT!</b>

📋 Mã: {yeu_cau_id}
💵 Số tiền: {so_tien:,}đ
✅ Đã chuyển tiền cho bạn!
Cảm ơn bạn!"""
            await context.bot.send_message(chat_id=nguoi_dung_id, text=thong_bao, parse_mode="HTML")
            await query.edit_message_text(f"✅ Đã duyệt yêu cầu {yeu_cau_id} — Trừ {so_tien:,}đ khỏi số dư người dùng!")
            del danh_sach_cho_duyet[yeu_cau_id]
        else:
            await query.edit_message_text(f"❌ Số dư người dùng không đủ!")

    elif data.startswith("duyet_no:"):
        _, yeu_cau_id = data.split(":")
        if yeu_cau_id not in danh_sach_cho_duyet:
            await query.edit_message_text("❌ Yêu cầu không tồn tại hoặc đã xử lý!")
            return
        yc = danh_sach_cho_duyet[yeu_cau_id]
        nguoi_dung_id = yc["user_id"]
        thong_bao = f"""❌ <b>YÊU CẦU RÚT TIỀN BỊ TỪ CHỐI</b>

📋 Mã: {yeu_cau_id}
💵 Số tiền: {yc['so_tien']:,}đ
Vui lòng kiểm tra lại thông tin hoặc liên hệ hỗ trợ!"""
        await context.bot.send_message(chat_id=nguoi_dung_id, text=thong_bao, parse_mode="HTML")
        await query.edit_message_text(f"❌ Đã từ chối yêu cầu {yeu_cau_id}!")
        del danh_sach_cho_duyet[yeu_cau_id]

    elif data == "admin_danh_sach":
        if not danh_sach_cho_duyet:
            await update.callback_query.message.reply_text("✅ Không có yêu cầu nào chờ duyệt!")
            return
        noi_dung = "📋 <b>DANH SÁCH CHỜ DUYỆT</b>\n\n"
        for idx, (ma, yc) in enumerate(danh_sach_cho_duyet.items(), 1):
            noi_dung += f"{idx}. <code>{ma}</code>\n👤 {yc['ten']} | 💵 {yc['so_tien']:,}đ\n"
        await update.callback_query.message.reply_text(noi_dung, parse_mode="HTML")

    elif data == "admin_ds_nguoi":
        if not users:
            await update.callback_query.message.reply_text("Chưa có người dùng nào!")
            return
        noi_dung = "👥 <b>DANH SÁCH NGƯỜI DÙNG</b>\n\n"
        for uid, u in list(users.items())[:30]:
            noi_dung += f"🆔 {uid} | {u['ten']} | 💰 {u['so_du']:,}đ | 👥 {u['gioi_thieu']}\n"
        await update.callback_query.message.reply_text(noi_dung, parse_mode="HTML")

# Xử lý nút chính
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
    elif text == "💰 Rút Tiền": return await rut_tien_bat_dau(update, context)
    elif text == "🎛 QUẢN LÝ ADMIN" and u_id == ADMIN_ID:
        await trang_quan_ly_admin(update, context)
    else:
        await update.message.reply_text("❌ Vui lòng chọn nút bên dưới!", reply_markup=menu_chinh(u_id))

def main():
    print("="*50)
    print("🤖 CÀY ẢO RÚT THẬT — ĐANG KHỞI ĐỘNG...")
    print("="*50)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    rut_tien_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💰 Rút Tiền$"), rut_tien_bat_dau)],
        states={
            NH_TEN_NGANHANG: [MessageHandler(filters.TEXT & ~filters.COMMAND, rut_tien_ten_nganhang)],
            NH_SO_TAIKHOAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, rut_tien_so_taikhoan)],
            NH_TEN_CHUTAIKHOAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, rut_tien_ten_chu)],
            NH_SO_TIEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, rut_tien_so_tien)],
        },
        fallbacks=[MessageHandler(filters.Regex("^Hủy$|^/cancel$"), rut_tien_huy)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(nhan_thuong_callback, pattern=r"^nhan_thuong:"))
    app.add_handler(CallbackQueryHandler(xu_ly_goi_nang_cap, pattern=r"^goi_"))
    app.add_handler(CallbackQueryHandler(xu_ly_admin_callback, pattern=r"^(duyet_ok:|duyet_no:|admin_)"))
    app.add_handler(rut_tien_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, xu_ly_nut))

    print("✅ SẴN SÀNG! Gõ /start trên Telegram nhé!")
    app.run_polling()

if __name__ == "__main__":
    main()