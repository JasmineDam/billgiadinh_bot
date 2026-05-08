"""
🤖 Telegram Bot Theo Dõi Chi Tiêu - Claude AI + Google Sheets
"""

import os
import json
import logging
import httpx
import base64
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDS"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)


def get_or_create_sheet(month_label: str):
    try:
        ws = sh.worksheet(month_label)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=month_label, rows=1000, cols=5)
        ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người ghi", "Tổng cộng"])
    return ws


def get_month_label() -> str:
    return datetime.now().strftime("%m-%Y")


def add_expense(amount: int, description: str, user_name: str) -> dict:
    month_label = get_month_label()
    ws = get_or_create_sheet(month_label)
    records = ws.get_all_values()
    total = 0
    for row in records[1:]:
        if row and len(row) > 1 and row[1]:
            try:
                val = str(row[1]).replace(',', '').replace('.', '').replace('đ', '').replace('d', '').strip()
                if val.lstrip('-').isdigit():
                    total += int(val)
            except:
                pass
    total += amount
    time_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    ws.append_row([time_str, amount, description, user_name, total])
    count = len(records)  # Số giao dịch (không kể header)
    return {"total": total, "count": count}


def get_month_total(month_label: str) -> dict:
    try:
        ws = sh.worksheet(month_label)
        records = ws.get_all_values()
        total = 0
        count = 0
        for row in records[1:]:
            if row and row[1]:
                try:
                    val = str(row[1]).replace(',', '').replace('.', '').replace('đ', '').replace('d', '').strip()
                    if val.lstrip('-').isdigit():
                        total += int(val)
                        count += 1
                except:
                    pass
        return {"total": total, "count": count, "rows": records[1:]}
    except gspread.exceptions.WorksheetNotFound:
        return {"total": 0, "count": 0, "rows": []}


def extract_expense_from_image(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Đây là ảnh giao dịch hoặc đơn hàng. "
                        "Tìm TỔNG SỐ TIỀN THANH TOÁN của toàn bộ đơn hàng (không phải giá từng sản phẩm riêng lẻ). "
                        "Nếu là ảnh ngân hàng, lấy số tiền giao dịch chính. "
                        "Nếu là ảnh đơn hàng Shopee/Lazada/Tiki, lấy tổng tiền thanh toán cuối cùng của toàn đơn. "
                        "Nếu tiền là USD, quy đổi sang VND (1 USD = 26000 VND). "
                        'Trả về JSON: {"amount": <tổng tiền VND, chỉ số nguyên>, "description": "<tên shop hoặc nơi thanh toán>"}\n'
                        "Chỉ trả về JSON thuần, không markdown, không giải thích."
                    )
                }
            ],
        }]
    )
    text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Tôi là bot theo dõi chi tiêu.\n\n"
        "📸 Gửi *ảnh giao dịch ngân hàng* → tôi tự đọc và cộng vào tổng\n"
        "💬 Hoặc gõ: `84000 cafe highlands`\n\n"
        "📊 Lệnh:\n"
        "/total – Tổng chi tiêu tháng này\n"
        "/history – Lịch sử giao dịch tháng này\n"
        "/history\\_month 04 – Lịch sử tháng cụ thể\n"
        "/compare – So sánh các tháng\n"
        "/taisan – Xem/cập nhật tài sản gia đình\n"
        "/naptaisan iPower 3700000 – Cộng thêm tiền vào tài sản",
        parse_mode="Markdown",
    )


async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_month_total(get_month_label())
    if data["count"] == 0:
        await update.message.reply_text("📭 Chưa có giao dịch nào tháng này.")
        return
    await update.message.reply_text(
        f"📊 *Tổng chi tiêu tháng {datetime.now().strftime('%m/%Y')}*\n"
        f"💰 `{data['total']:,.0f} VND`\n"
        f"🧾 {data['count']} giao dịch",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_month_total(get_month_label())
    if data["count"] == 0:
        await update.message.reply_text("📭 Chưa có giao dịch nào tháng này.")
        return
    lines = [f"🗂 *Lịch sử tháng {datetime.now().strftime('%m/%Y')}*\n"]
    for i, row in enumerate(data["rows"], 1):
        if row and len(row) >= 3:
            lines.append(f"{i}. `{int(row[1]):,.0f}` – {row[2]} _{row[0]}_")
    lines.append(f"\n💰 *Tổng: {data['total']:,.0f} VND*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_history_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Dùng: `/history_month 04`", parse_mode="Markdown")
        return
    month_input = context.args[0].zfill(2)
    year = datetime.now().strftime("%Y")
    month_label = f"{month_input}-{year}"
    data = get_month_total(month_label)
    if data["count"] == 0:
        await update.message.reply_text(f"📭 Không có dữ liệu tháng {month_input}/{year}.")
        return
    lines = [f"🗂 *Lịch sử tháng {month_input}/{year}*\n"]
    for i, row in enumerate(data["rows"], 1):
        if row and len(row) >= 3:
            lines.append(f"{i}. `{int(row[1]):,.0f}` – {row[2]} _{row[0]}_")
    lines.append(f"\n💰 *Tổng: {data['total']:,.0f} VND*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = datetime.now().strftime("%Y")
    lines = ["📊 *So sánh chi tiêu các tháng*\n"]
    totals = []
    for m in range(1, 13):
        month_label = f"{str(m).zfill(2)}-{year}"
        data = get_month_total(month_label)
        if data["count"] > 0:
            totals.append((m, data["total"], data["count"]))
            lines.append(f"📅 *Tháng {m}/{year}*: `{data['total']:,.0f} VND` ({data['count']} giao dịch)")
    if len(totals) >= 2:
        diff = totals[-1][1] - totals[-2][1]
        if diff > 0:
            lines.append(f"\n📈 Tháng này tăng `{diff:,.0f} VND` so với tháng trước")
        elif diff < 0:
            lines.append(f"\n📉 Tháng này giảm `{abs(diff):,.0f} VND` so với tháng trước")
        else:
            lines.append(f"\n➡️ Tháng này bằng tháng trước")
    if not totals:
        await update.message.reply_text("📭 Chưa có dữ liệu nào.")
        return
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang đọc ảnh giao dịch...")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        async with httpx.AsyncClient() as http:
            resp = await http.get(tg_file.file_path)
            image_bytes = resp.content

        # Đọc số tiền từ ảnh
        result = extract_expense_from_image(image_bytes)
        amount = int(result["amount"])

        # Nếu có caption thì dùng caption làm mô tả, không thì dùng AI đọc
        caption = update.message.caption
        if caption and caption.strip():
            description = caption.strip()
        else:
            description = result.get("description", "Không rõ")

        user_name = update.effective_user.first_name or "Unknown"
        data = add_expense(amount, description, user_name)
        await msg.edit_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{data['total']:,.0f} VND` ({data['count']} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Lỗi: {e}")
        await msg.edit_text("❌ Không đọc được ảnh. Thử gõ tay: `84000 cafe highlands`")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        parts = text.split(maxsplit=1)
        amount = int(parts[0].replace(",", "").replace(".", "").replace("-", ""))
        description = parts[1] if len(parts) > 1 else "Không rõ"
        user_name = update.effective_user.first_name or "Unknown"
        data = add_expense(amount, description, user_name)
        await update.message.reply_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{data['total']:,.0f} VND` ({data['count']} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text("⚠️ Không hiểu. Thử gửi ảnh hoặc gõ: `84000 cafe highlands`")





MONTHLY_BUDGET = 40_000_000  # 40 triệu VND

async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    month_label = get_month_label()
    data = get_month_total(month_label)
    spent = data["total"]
    remaining = MONTHLY_BUDGET - spent

    # Tính ngày thực tế đã chi dựa trên giao dịch đầu tiên trong sheet
    days_elapsed = now.day  # mặc định
    try:
        ws = sh.worksheet(month_label)
        records = ws.get_all_values()
        if len(records) > 1 and records[1][0]:
            # Đọc ngày giao dịch đầu tiên, format "HH:MM DD/MM/YYYY"
            first_date_str = records[1][0].split(" ")[-1]  # lấy DD/MM/YYYY
            first_day = int(first_date_str.split("/")[0])
            days_elapsed = max(now.day - first_day + 1, 1)
    except:
        pass

    import calendar
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_left = days_in_month - now.day

    # Dự báo dựa trên số ngày thực tế đã chi
    if days_elapsed > 0 and spent > 0:
        daily_avg = spent / days_elapsed
        forecast = daily_avg * days_in_month
        forecast_diff = MONTHLY_BUDGET - forecast
    else:
        daily_avg = 0
        forecast = 0
        forecast_diff = MONTHLY_BUDGET

    # Bar progress
    pct = min(spent / MONTHLY_BUDGET, 1.0)
    filled = int(pct * 10)
    bar = "🟥" * filled + "⬜" * (10 - filled)

    status = "✅ Đang ổn" if remaining >= 0 else "⚠️ Đã vượt ngân sách!"
    daily_remaining = remaining / days_left if days_left > 0 and remaining > 0 else 0

    lines = [
        f"💰 *Ngân sách tháng {now.strftime('%m/%Y')}*\n",
        f"{bar} `{pct*100:.0f}%`",
        f"",
        f"🏦 Ngân sách: `{MONTHLY_BUDGET:,.0f} VND`",
        f"💸 Đã chi: `{spent:,.0f} VND`",
        f"",
        f"{status}",
        f"{'💚 Còn lại' if remaining >= 0 else '🔴 Vượt'}: `{abs(remaining):,.0f} VND`",
        f"",
        f"📆 Còn {days_left} ngày → có thể chi `{daily_remaining:,.0f} VND/ngày`" if remaining > 0 else f"🔴 Đã vượt ngân sách `{abs(remaining):,.0f} VND`",
    ]
    await update.message.reply_text("\n".join(l for l in lines if l is not None), parse_mode="Markdown")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    month_label = get_month_label()
    try:
        ws = sh.worksheet(month_label)
        records = ws.get_all_values()[1:]  # Bỏ header
    except:
        await update.message.reply_text("📭 Chưa có dữ liệu tháng này.")
        return

    # Tính chi tiêu theo từng người
    person_totals = {}
    total = 0
    for row in records:
        if not row or len(row) < 4:
            continue
        try:
            amount = int(str(row[1]).replace(',', '').replace('.', '').replace('đ', '').strip())
            person = row[3].strip() if row[3] else "Khác"
            person_totals[person] = person_totals.get(person, 0) + amount
            total += amount
        except:
            pass

    savings = MONTHLY_BUDGET - total
    lines = [f"📊 *Tổng kết tháng {now.strftime('%m/%Y')}*\n"]

    # Chi tiêu từng người
    for person, amount in sorted(person_totals.items()):
        pct = amount / total * 100 if total > 0 else 0
        lines.append(f"👤 *{person}*: `{amount:,.0f} VND` ({pct:.0f}%)")

    lines.append("")
    lines.append(f"💸 Tổng chi: `{total:,.0f} VND`")
    lines.append(f"🏦 Ngân sách: `{MONTHLY_BUDGET:,.0f} VND`")

    if savings >= 0:
        lines.append(f"💚 Tiết kiệm: `{savings:,.0f} VND`")
    else:
        lines.append(f"🔴 Vượt chi: `{abs(savings):,.0f} VND`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Tài sản ─────────────────────────────────────────

def get_asset_sheet():
    try:
        ws = sh.worksheet("Tai San")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Tai San", rows=200, cols=5)
        ws.append_row(["Tài sản", "Số tiền", "Cập nhật lúc", "Tháng"])
    return ws

def update_asset(name: str, amount: int) -> dict:
    ws = get_asset_sheet()
    records = ws.get_all_values()
    month_label = get_month_label()
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")

    # Tìm dòng tài sản này trong tháng hiện tại
    for i, row in enumerate(records[1:], 2):
        if row and row[0].lower() == name.lower() and len(row) > 3 and row[3] == month_label:
            ws.update(f"B{i}", [[amount]])
            ws.update(f"C{i}", [[now_str]])
            break
    else:
        ws.append_row([name, amount, now_str, month_label])

    # Tính tổng tài sản tháng này
    records = ws.get_all_values()
    total = 0
    assets = {}
    for row in records[1:]:
        if row and len(row) >= 4 and row[3] == month_label:
            try:
                val = int(str(row[1]).replace(',', '').strip())
                assets[row[0]] = val
                total += val
            except:
                pass
    return {"total": total, "assets": assets}


def get_assets_by_month(month_label: str) -> dict:
    ws = get_asset_sheet()
    records = ws.get_all_values()
    total = 0
    assets = {}
    for row in records[1:]:
        if row and len(row) >= 4 and row[3] == month_label:
            try:
                val = int(str(row[1]).replace(',', '').strip())
                assets[row[0]] = val
                total += val
            except:
                pass
    return {"total": total, "assets": assets}


async def cmd_taisan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()

    # Nếu không có args → xem danh sách tài sản
    if not context.args:
        data = get_assets_by_month(get_month_label())
        if not data["assets"]:
            await update.message.reply_text(
                "📭 Chưa có tài sản nào.\n\n"
                "Dùng: `/taisan Fmarket 400000` để thêm",
                parse_mode="Markdown"
            )
            return

        # Tính tăng/giảm so với tháng trước
        prev_month = now.month - 1
        prev_year = now.year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        prev_label = f"{str(prev_month).zfill(2)}-{prev_year}"
        prev_data = get_assets_by_month(prev_label)

        diff = data["total"] - prev_data["total"]
        diff_text = ""
        if prev_data["total"] > 0:
            if diff > 0:
                diff_text = f"\n📈 Tăng `{diff:,.0f} VND` so với tháng trước"
            elif diff < 0:
                diff_text = f"\n📉 Giảm `{abs(diff):,.0f} VND` so với tháng trước"
            else:
                diff_text = f"\n➡️ Không đổi so với tháng trước"

        lines = [f"🏦 *Tài sản tháng {now.strftime('%m/%Y')}*\n"]
        for name, amount in sorted(data["assets"].items(), key=lambda x: -x[1]):
            pct = amount / data["total"] * 100 if data["total"] > 0 else 0
            lines.append(f"• {name}: `{amount:,.0f} VND` ({pct:.0f}%)")
        lines.append(f"\n💰 *Tổng: {data['total']:,.0f} VND*{diff_text}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Có args → cập nhật tài sản
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Dùng: `/taisan Fmarket 400000`",
            parse_mode="Markdown"
        )
        return

    try:
        name = context.args[0]
        amount = int(context.args[-1].replace(',', '').replace('.', ''))
        data = update_asset(name, amount)
        await update.message.reply_text(
            f"✅ *Đã cập nhật tài sản!*\n"
            f"🏦 {name}: `{amount:,.0f} VND`\n\n"
            f"💰 *Tổng tài sản tháng này:* `{data['total']:,.0f} VND`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")


async def cmd_naptaisan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Dùng: `/naptaisan iPower 3700000`",
            parse_mode="Markdown"
        )
        return
    try:
        name = context.args[0]
        amount = int(context.args[-1].replace(',', '').replace('.', ''))
        month_label = get_month_label()

        # Lấy số dư hiện tại
        ws = get_asset_sheet()
        records = ws.get_all_values()
        current = 0
        for row in records[1:]:
            if row and len(row) >= 4 and row[0].lower() == name.lower() and row[3] == month_label:
                try:
                    current = int(str(row[1]).replace(',', '').strip())
                except:
                    pass
                break

        new_amount = current + amount
        data = update_asset(name, new_amount)

        await update.message.reply_text(
            f"✅ *Đã nạp thêm vào {name}!*\n"
            f"💰 Trước: `{current:,.0f} VND`\n"
            f"➕ Nạp: `{amount:,.0f} VND`\n"
            f"💎 Sau: `{new_amount:,.0f} VND`\n\n"
            f"🏦 *Tổng tài sản:* `{data['total']:,.0f} VND`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_label = get_month_label()
    try:
        ws = sh.worksheet(month_label)
        ws.clear()
        ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người ghi", "Tổng cộng"])
        await update.message.reply_text("🗑 Đã xóa toàn bộ dữ liệu tháng này.")
    except:
        await update.message.reply_text("📭 Không có dữ liệu tháng này để xóa.")


# ── Tài sản ─────────────────────────────────────────

def get_asset_sheet():
    try:
        ws = sh.worksheet("Tai San")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Tai San", rows=200, cols=5)
        ws.append_row(["Tài sản", "Số tiền", "Cập nhật lúc", "Tháng"])
    return ws

def update_asset(name: str, amount: int) -> dict:
    ws = get_asset_sheet()
    records = ws.get_all_values()
    month_label = get_month_label()
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")

    # Tìm dòng tài sản này trong tháng hiện tại
    for i, row in enumerate(records[1:], 2):
        if row and row[0].lower() == name.lower() and len(row) > 3 and row[3] == month_label:
            ws.update(f"B{i}", [[amount]])
            ws.update(f"C{i}", [[now_str]])
            break
    else:
        ws.append_row([name, amount, now_str, month_label])

    # Tính tổng tài sản tháng này
    records = ws.get_all_values()
    total = 0
    assets = {}
    for row in records[1:]:
        if row and len(row) >= 4 and row[3] == month_label:
            try:
                val = int(str(row[1]).replace(',', '').strip())
                assets[row[0]] = val
                total += val
            except:
                pass
    return {"total": total, "assets": assets}


def get_assets_by_month(month_label: str) -> dict:
    ws = get_asset_sheet()
    records = ws.get_all_values()
    total = 0
    assets = {}
    for row in records[1:]:
        if row and len(row) >= 4 and row[3] == month_label:
            try:
                val = int(str(row[1]).replace(',', '').strip())
                assets[row[0]] = val
                total += val
            except:
                pass
    return {"total": total, "assets": assets}


async def cmd_taisan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()

    # Nếu không có args → xem danh sách tài sản
    if not context.args:
        data = get_assets_by_month(get_month_label())
        if not data["assets"]:
            await update.message.reply_text(
                "📭 Chưa có tài sản nào.\n\n"
                "Dùng: `/taisan Fmarket 400000` để thêm",
                parse_mode="Markdown"
            )
            return

        # Tính tăng/giảm so với tháng trước
        prev_month = now.month - 1
        prev_year = now.year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        prev_label = f"{str(prev_month).zfill(2)}-{prev_year}"
        prev_data = get_assets_by_month(prev_label)

        diff = data["total"] - prev_data["total"]
        diff_text = ""
        if prev_data["total"] > 0:
            if diff > 0:
                diff_text = f"\n📈 Tăng `{diff:,.0f} VND` so với tháng trước"
            elif diff < 0:
                diff_text = f"\n📉 Giảm `{abs(diff):,.0f} VND` so với tháng trước"
            else:
                diff_text = f"\n➡️ Không đổi so với tháng trước"

        lines = [f"🏦 *Tài sản tháng {now.strftime('%m/%Y')}*\n"]
        for name, amount in sorted(data["assets"].items(), key=lambda x: -x[1]):
            pct = amount / data["total"] * 100 if data["total"] > 0 else 0
            lines.append(f"• {name}: `{amount:,.0f} VND` ({pct:.0f}%)")
        lines.append(f"\n💰 *Tổng: {data['total']:,.0f} VND*{diff_text}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Có args → cập nhật tài sản
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Dùng: `/taisan Fmarket 400000`",
            parse_mode="Markdown"
        )
        return

    try:
        name = context.args[0]
        amount = int(context.args[-1].replace(',', '').replace('.', ''))
        data = update_asset(name, amount)
        await update.message.reply_text(
            f"✅ *Đã cập nhật tài sản!*\n"
            f"🏦 {name}: `{amount:,.0f} VND`\n\n"
            f"💰 *Tổng tài sản tháng này:* `{data['total']:,.0f} VND`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")


async def cmd_naptaisan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Dùng: `/naptaisan iPower 3700000`",
            parse_mode="Markdown"
        )
        return
    try:
        name = context.args[0]
        amount = int(context.args[-1].replace(',', '').replace('.', ''))
        month_label = get_month_label()

        # Lấy số dư hiện tại
        ws = get_asset_sheet()
        records = ws.get_all_values()
        current = 0
        for row in records[1:]:
            if row and len(row) >= 4 and row[0].lower() == name.lower() and row[3] == month_label:
                try:
                    current = int(str(row[1]).replace(',', '').strip())
                except:
                    pass
                break

        new_amount = current + amount
        data = update_asset(name, new_amount)

        await update.message.reply_text(
            f"✅ *Đã nạp thêm vào {name}!*\n"
            f"💰 Trước: `{current:,.0f} VND`\n"
            f"➕ Nạp: `{amount:,.0f} VND`\n"
            f"💎 Sau: `{new_amount:,.0f} VND`\n\n"
            f"🏦 *Tổng tài sản:* `{data['total']:,.0f} VND`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_label = get_month_label()
    try:
        ws = sh.worksheet(month_label)
        ws.clear()
        ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người ghi", "Tổng cộng"])
        await update.message.reply_text("🗑 Đã xóa toàn bộ dữ liệu tháng này.")
    except:
        await update.message.reply_text("📭 Không có dữ liệu tháng này để xóa.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("total", cmd_total))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("history_month", cmd_history_month))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("taisan", cmd_taisan))
    app.add_handler(CommandHandler("naptaisan", cmd_naptaisan))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot đang chạy với Claude AI + Google Sheets!")
    app.run_polling()


if __name__ == "__main__":
    main()
