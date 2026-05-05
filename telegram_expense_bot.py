"""
🤖 Telegram Bot Theo Dõi Chi Tiêu - Dùng Google Gemini (Miễn Phí)
"""

import os
import json
import logging
import httpx
import base64
from datetime import datetime
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)

DATA_FILE = "expenses.json"


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def add_expense(chat_id: str, amount: int, description: str) -> dict:
    data = load_data()
    month = get_month_key()
    if chat_id not in data:
        data[chat_id] = {}
    if month not in data[chat_id]:
        data[chat_id][month] = {"transactions": [], "total": 0}
    tx = {"amount": amount, "description": description, "time": datetime.now().strftime("%H:%M %d/%m/%Y")}
    data[chat_id][month]["transactions"].append(tx)
    data[chat_id][month]["total"] += amount
    save_data(data)
    return data[chat_id][month]


def extract_expense_from_image(image_bytes: bytes) -> dict:
    prompt = (
        "Đây là ảnh thông báo giao dịch ngân hàng. "
        "Trả về JSON: {\"amount\": <số tiền dương>, \"description\": \"<nơi thanh toán ngắn gọn>\"}\n"
        "Chỉ trả về JSON thuần, không markdown, không giải thích."
    )
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        ]
    )
    text = response.text.strip().replace("```json", "").replace("```", "").strip()
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
        "/reset – Xóa dữ liệu tháng này",
        parse_mode="Markdown",
    )


async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    month_data = data.get(chat_id, {}).get(get_month_key())
    if not month_data or not month_data["transactions"]:
        await update.message.reply_text("📭 Chưa có giao dịch nào tháng này.")
        return
    await update.message.reply_text(
        f"📊 *Tổng chi tiêu tháng {datetime.now().strftime('%m/%Y')}*\n"
        f"💰 `{month_data['total']:,.0f} VND`\n"
        f"🧾 {len(month_data['transactions'])} giao dịch",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    month_data = data.get(chat_id, {}).get(get_month_key())
    if not month_data or not month_data["transactions"]:
        await update.message.reply_text("📭 Chưa có giao dịch nào tháng này.")
        return
    lines = [f"🗂 *Lịch sử tháng {datetime.now().strftime('%m/%Y')}*\n"]
    for i, tx in enumerate(month_data["transactions"], 1):
        lines.append(f"{i}. `{tx['amount']:,.0f}` – {tx['description']} _{tx['time']}_")
    lines.append(f"\n💰 *Tổng: {month_data['total']:,.0f} VND*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_history_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()

    # Lấy tháng từ argument, vd: /history_month 04
    if not context.args:
        await update.message.reply_text("⚠️ Dùng: `/history_month 04` để xem tháng 4", parse_mode="Markdown")
        return

    month_input = context.args[0].zfill(2)  # "4" → "04"
    year = datetime.now().strftime("%Y")
    month_key = f"{year}-{month_input}"
    month_label = f"{month_input}/{year}"

    month_data = data.get(chat_id, {}).get(month_key)
    if not month_data or not month_data["transactions"]:
        await update.message.reply_text(f"📭 Không có dữ liệu tháng {month_label}.")
        return

    lines = [f"🗂 *Lịch sử tháng {month_label}*\n"]
    for i, tx in enumerate(month_data["transactions"], 1):
        lines.append(f"{i}. `{tx['amount']:,.0f}` – {tx['description']} _{tx['time']}_")
    lines.append(f"\n💰 *Tổng: {month_data['total']:,.0f} VND*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    user_data = data.get(chat_id, {})

    if not user_data:
        await update.message.reply_text("📭 Chưa có dữ liệu nào.")
        return

    # Sắp xếp các tháng theo thứ tự
    sorted_months = sorted(user_data.keys())
    if not sorted_months:
        await update.message.reply_text("📭 Chưa có dữ liệu nào.")
        return

    lines = ["📊 *So sánh chi tiêu các tháng*\n"]

    totals = []
    for month_key in sorted_months:
        month_data = user_data[month_key]
        total = month_data.get("total", 0)
        count = len(month_data.get("transactions", []))
        totals.append(total)
        year, month = month_key.split("-")
        lines.append(f"📅 *Tháng {month}/{year}*: `{total:,.0f} VND` ({count} giao dịch)")

    # So sánh tháng này vs tháng trước
    if len(totals) >= 2:
        diff = totals[-1] - totals[-2]
        if diff > 0:
            lines.append(f"\n📈 Tháng này tăng `{diff:,.0f} VND` so với tháng trước")
        elif diff < 0:
            lines.append(f"\n📉 Tháng này giảm `{abs(diff):,.0f} VND` so với tháng trước")
        else:
            lines.append(f"\n➡️ Tháng này bằng tháng trước")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    month = get_month_key()
    if chat_id in data and month in data[chat_id]:
        data[chat_id][month] = {"transactions": [], "total": 0}
        save_data(data)
    await update.message.reply_text("🗑 Đã xóa dữ liệu tháng này.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang đọc ảnh giao dịch...")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        async with httpx.AsyncClient() as http:
            resp = await http.get(tg_file.file_path)
            image_bytes = resp.content

        result = extract_expense_from_image(image_bytes)
        amount = int(result["amount"])
        description = result.get("description", "Không rõ")
        month_data = add_expense(str(update.effective_chat.id), amount, description)
        await msg.edit_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{month_data['total']:,.0f} VND` ({len(month_data['transactions'])} giao dịch)",
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
        month_data = add_expense(str(update.effective_chat.id), amount, description)
        await update.message.reply_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{month_data['total']:,.0f} VND` ({len(month_data['transactions'])} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text("⚠️ Không hiểu. Thử gửi ảnh hoặc gõ: `84000 cafe highlands`")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("total", cmd_total))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("history_month", cmd_history_month))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot đang chạy...")
    app.run_polling()


if __name__ == "__main__":
    main()
