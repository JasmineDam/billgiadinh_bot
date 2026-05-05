"""
🤖 Telegram Bot Theo Dõi Chi Tiêu - Đọc Ảnh Ngân Hàng Tự Động
Yêu cầu: pip install python-telegram-bot anthropic

Chạy: python telegram_expense_bot.py
"""

import os
import json
import base64
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic
import httpx

# ===================== CẤU HÌNH =====================
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]   # Thay bằng token từ BotFather
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]  # Thay bằng API key của bạn

# File lưu dữ liệu chi tiêu
DATA_FILE = "expenses.json"
# ====================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Đọc / Ghi dữ liệu ──────────────────────────────

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

    tx = {
        "amount": amount,
        "description": description,
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
    }
    data[chat_id][month]["transactions"].append(tx)
    data[chat_id][month]["total"] += amount
    save_data(data)
    return data[chat_id][month]


# ── Đọc ảnh bằng Claude AI ─────────────────────────

def extract_expense_from_image(image_bytes: bytes) -> dict | None:
    """Gửi ảnh lên Claude để đọc số tiền và mô tả giao dịch."""
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        messages=[
            {
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
                            "Đây là ảnh thông báo giao dịch ngân hàng. "
                            "Hãy trích xuất thông tin và trả về JSON với format:\n"
                            '{"amount": <số tiền dương, không dấu âm>, "description": "<nơi thanh toán hoặc mô tả ngắn>"}\n'
                            "Chỉ trả về JSON, không giải thích thêm."
                        ),
                    },
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    # Xóa markdown code block nếu có
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


# ── Handlers ────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Tôi là bot theo dõi chi tiêu.\n\n"
        "📸 Gửi *ảnh giao dịch ngân hàng* → tôi sẽ tự đọc và cộng vào tổng\n"
        "💬 Hoặc gõ: `-84000 cafe highlands`\n\n"
        "📊 Lệnh:\n"
        "/total – Xem tổng chi tiêu tháng này\n"
        "/history – Xem lịch sử giao dịch\n"
        "/reset – Xóa dữ liệu tháng này",
        parse_mode="Markdown",
    )


async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    month = get_month_key()

    month_data = data.get(chat_id, {}).get(month)
    if not month_data or not month_data["transactions"]:
        await update.message.reply_text("📭 Chưa có giao dịch nào tháng này.")
        return

    total = month_data["total"]
    count = len(month_data["transactions"])
    month_label = datetime.now().strftime("%m/%Y")

    await update.message.reply_text(
        f"📊 *Tổng chi tiêu tháng {month_label}*\n"
        f"💰 `{total:,.0f} VND`\n"
        f"🧾 {count} giao dịch",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    month = get_month_key()

    month_data = data.get(chat_id, {}).get(month)
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
    """Nhận ảnh, gửi lên Claude để đọc số tiền."""
    msg = await update.message.reply_text("⏳ Đang đọc ảnh giao dịch...")

    try:
        photo = update.message.photo[-1]  # Lấy ảnh chất lượng cao nhất
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        result = extract_expense_from_image(bytes(image_bytes))
        amount = int(result["amount"])
        description = result.get("description", "Không rõ")

        month_data = add_expense(str(update.effective_chat.id), amount, description)
        total = month_data["total"]
        count = len(month_data["transactions"])

        await msg.edit_text(
            f"✅ *Đã ghi nhận giao dịch!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{total:,.0f} VND` ({count} giao dịch)",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Lỗi đọc ảnh: {e}")
        await msg.edit_text(
            "❌ Không đọc được ảnh. Thử gõ tay: `-84000 cafe highlands`"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận text dạng: -84000 cafe highlands"""
    text = update.message.text.strip()

    try:
        parts = text.split(maxsplit=1)
        amount_str = parts[0].replace(",", "").replace(".", "").replace("-", "")
        amount = int(amount_str)
        description = parts[1] if len(parts) > 1 else "Không rõ"

        month_data = add_expense(str(update.effective_chat.id), amount, description)
        total = month_data["total"]
        count = len(month_data["transactions"])

        await update.message.reply_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"📊 *Tổng tháng này:* `{total:,.0f} VND` ({count} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Không hiểu. Thử:\n"
            "• Gửi ảnh giao dịch ngân hàng\n"
            "• Hoặc gõ: `-84000 cafe highlands`"
        )


# ── Main ─────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("total", cmd_total))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Bot đang chạy... Nhấn Ctrl+C để dừng.")
    app.run_polling()


if __name__ == "__main__":
    main()
