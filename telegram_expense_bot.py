"""
🤖 Telegram Bot Theo Dõi Chi Tiêu - Dùng Google Gemini (Miễn Phí)
"""

import os
import json
import logging
from datetime import datetime
import google.generativeai as genai
import PIL.Image
import io
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

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
    image = PIL.Image.open(io.BytesIO(image_bytes))
    prompt = (
        "Đây là ảnh thông báo giao dịch ngân hàng. "
        "Trả về JSON: {\"amount\": <số tiền dương>, \"description\": \"<nơi thanh toán ngắn gọn>\"}\n"
        "Chỉ trả về JSON thuần, không markdown, không giải thích."
    )
    response = model.generate_content([prompt, image])
    text = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Tôi là bot theo dõi chi tiêu.\n\n"
        "📸 Gửi *ảnh giao dịch ngân hàng* → tôi tự đọc và cộng vào tổng\n"
        "💬 Hoặc gõ: `84000 cafe highlands`\n\n"
        "📊 Lệnh:\n"
        "/total – Tổng chi tiêu tháng này\n"
        "/history – Lịch sử giao dịch\n"
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
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        result = extract_expense_from_image(bytes(image_bytes))
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
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot đang chạy...")
    app.run_polling()


if __name__ == "__main__":
    main()
