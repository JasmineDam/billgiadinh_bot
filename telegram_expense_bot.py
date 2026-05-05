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
        "/delete 4 – Xóa giao dịch thứ 4",
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




async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_label = get_month_label()
    try:
        ws = sh.worksheet(month_label)
        ws.clear()
        ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người ghi", "Tổng cộng"])
        await update.message.reply_text("🗑 Đã xóa toàn bộ dữ liệu tháng này.")
    except:
        await update.message.reply_text("📭 Không có dữ liệu tháng này để xóa.")

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Dùng: `/delete 4` để xóa giao dịch thứ 4", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0])
        month_label = get_month_label()
        ws = get_or_create_sheet(month_label)
        records = ws.get_all_values()
        data_rows = records[1:]  # Bỏ header

        if idx < 1 or idx > len(data_rows):
            await update.message.reply_text(f"⚠️ Không có giao dịch thứ {idx}. Hiện có {len(data_rows)} giao dịch.")
            return

        row = data_rows[idx - 1]
        amount = int(row[1]) if row[1] else 0
        description = row[2] if len(row) > 2 else "?"

        # Xóa dòng (row index trong sheet = idx + 1 vì có header)
        ws.delete_rows(idx + 1)

        # Tính lại tổng sau khi xóa
        remaining = ws.get_all_values()[1:]
        total = sum(int(r[1]) for r in remaining if r and r[1] and r[1].isdigit())

        await update.message.reply_text(
            f"🗑 *Đã xóa giao dịch {idx}*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng còn lại:* `{total:,.0f} VND` ({len(remaining)} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("total", cmd_total))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("history_month", cmd_history_month))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot đang chạy với Claude AI + Google Sheets!")
    app.run_polling()


if __name__ == "__main__":
    main()
