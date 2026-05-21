import logging
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from data_fetcher import get_historical_data, get_market_overview, get_top_movers
from technical_analysis import analyze_stock
from ai_analyzer import analyze_with_ai
from market_scanner import get_market_scan_results
from watchlist_manager import WatchlistManager

logger = logging.getLogger(__name__)
wm = WatchlistManager()
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def format_price(p: float) -> str:
    return f"{p:,.0f}"


def signal_badge(rec: str) -> str:
    return {"BUY": "🟢 NÊN MUA", "SELL": "🔴 KHÔNG NÊN MUA", "HOLD": "🟡 CÂN NHẮC"}.get(rec, "⚪ N/A")


def normalize_symbol(symbol: str) -> str | None:
    value = symbol.strip().upper()
    return value if SYMBOL_RE.fullmatch(value) else None


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "📈 *Stock Analysis Bot – Thị trường VN*\n\n"
        "Chào mừng! Bot phân tích cổ phiếu Việt Nam tích hợp AI.\n\n"
        "📋 *Các lệnh:*\n"
        "`/analyze VNM` – Phân tích chi tiết + AI\n"
        "`/quick VNM` – Tín hiệu nhanh\n"
        "`/watch VNM` – Thêm vào danh mục\n"
        "`/unwatch VNM` – Xóa khỏi danh mục\n"
        "`/watchlist` – Xem danh mục của bạn\n"
        "`/market` – Tổng quan thị trường\n"
        "`/scan` – Tổng quan dòng tiền toàn thị trường\n"
        "`/signals` – Tín hiệu Tích lũy/Đột biến\n"
        "`/entry VNM` – Tính Điểm vào/Cắt lỗ\n"
        "`/top` – Top tăng/giảm mạnh\n\n"
        f"📌 Chat ID của bạn: `{chat_id}`",
        parse_mode="Markdown",
    )


async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang lấy dữ liệu thị trường...")
    try:
        overview = await get_market_overview()
        lines = ["📊 *Tổng quan thị trường VN*\n"]
        for idx, d in overview.items():
            arrow = "📈" if d.get("change_pct", 0) >= 0 else "📉"
            lines.append(
                f"{arrow} *{idx}*: {d.get('value', 0):,.2f} "
                f"({d.get('change_pct', 0):+.2f}%)"
            )
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {e}")


async def cmd_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Cú pháp: `/quick VNM`", parse_mode="Markdown")
        return
    symbol = normalize_symbol(context.args[0])
    if not symbol:
        await update.message.reply_text("❌ Mã cổ phiếu không hợp lệ.", parse_mode="Markdown")
        return
    msg = await update.message.reply_text(f"⏳ Đang phân tích {symbol}...")
    try:
        data = await get_historical_data(symbol, 200)
        if len(data) < 30:
            await msg.edit_text(f"❌ Không tìm thấy dữ liệu cho {symbol}")
            return
        analysis = analyze_stock(data)
        ind = analysis["indicators"]
        price = analysis["price_info"]
        last = data[-1]
        text = (
            f"⚡ *{symbol}* – Phân tích nhanh\n\n"
            f"💰 Giá: {format_price(last['close'])} VNĐ ({price['change_pct']:+.2f}%)\n"
            f"📊 Khối lượng: {last['volume']:,}\n\n"
            f"📈 RSI(14): `{ind['rsi']}`\n"
            f"📉 MACD: `{ind['macd']['macd']:.2f}` | Cross: `{ind['macd']['cross']}`\n"
            f"📏 MA20: `{format_price(ind['ma20'] or 0)}`\n\n"
            f"🏆 *Tín hiệu: {signal_badge(analysis['recommendation'])}*\n"
            f"📊 Điểm: `{analysis['score']}/8`"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Thêm watchlist", callback_data=f"watch_{symbol}")]
        ])
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi khi phân tích {symbol}: {e}")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Cú pháp: `/analyze VNM`", parse_mode="Markdown")
        return
    symbol = normalize_symbol(context.args[0])
    if not symbol:
        await update.message.reply_text("❌ Mã cổ phiếu không hợp lệ.", parse_mode="Markdown")
        return
    msg = await update.message.reply_text(f"⏳ Đang phân tích chi tiết {symbol} + AI…")
    try:
        data = await get_historical_data(symbol, 300)
        if len(data) < 30:
            await msg.edit_text(f"❌ Không tìm thấy dữ liệu cho mã {symbol}")
            return
        analysis = analyze_stock(data)
        ai_text = await analyze_with_ai(symbol, analysis, raw_data=data)
        ind = analysis["indicators"]
        price = analysis["price_info"]
        last = data[-1]
        prev = data[-2] if len(data) >= 2 else last

        # Tính thêm thông số chuyên sâu
        chg_5d = (last["close"] - data[-6]["close"]) / data[-6]["close"] * 100 if len(data) >= 6 and data[-6]["close"] else 0
        chg_60d = (last["close"] - data[-61]["close"]) / data[-61]["close"] * 100 if len(data) >= 61 and data[-61]["close"] else 0
        recent20 = data[-20:]
        high_20 = max(b["high"] for b in recent20)
        low_20 = min(b["low"] for b in recent20)
        avg_vol_20 = sum(b["volume"] for b in recent20) / len(recent20)
        vol_ratio = last["volume"] / avg_vol_20 if avg_vol_20 else 0

        rsi = ind["rsi"]
        rsi_tag = "🔴 Quá mua" if rsi > 70 else "🟢 Quá bán" if rsi < 30 else "⚪ Trung tính"
        macd_cross = ind["macd"]["cross"]
        macd_tag = "🟢 Golden Cross" if macd_cross == "bullish" else "🔴 Death Cross" if macd_cross == "bearish" else "⚪ No cross"
        bb_pos = ind["bollinger"]["position"]
        bb_tag = {"above_upper": "🔴 Trên BB", "below_lower": "🟢 Dưới BB", "upper_half": "Nửa trên BB", "lower_half": "Nửa dưới BB"}.get(bb_pos, bb_pos)

        header = (
            f"🔍 *Phân tích chi tiết: {symbol}*  `{last['date']}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Giá: {format_price(last['close'])} VNĐ* ({price['change_pct']:+.2f}%)\n"
            f"📅 Tham chiếu: `{format_price(prev['close'])}`  •  Mở: `{format_price(last['open'])}`\n"
            f"📈 Cao: `{format_price(last['high'])}`  •  Thấp: `{format_price(last['low'])}`\n"
            f"📊 KL: `{last['volume']:,}` ({vol_ratio:.2f}x TB20)\n\n"
            f"⏱ *Biến động:*\n"
            f"  • 5 phiên: `{chg_5d:+.2f}%`  •  60 phiên: `{chg_60d:+.2f}%`\n"
            f"  • Đỉnh 20 phiên: `{format_price(high_20)}`\n"
            f"  • Đáy 20 phiên: `{format_price(low_20)}`\n\n"
            f"📐 *Chỉ báo kỹ thuật:*\n"
            f"  • RSI(14): `{rsi}` {rsi_tag}\n"
            f"  • MACD hist: `{ind['macd']['histogram']:+.2f}` {macd_tag}\n"
            f"  • Bollinger: `{bb_pos}` {bb_tag}\n"
            f"  • MA20: `{format_price(ind['ma20'] or 0)}`\n"
            f"  • MA50: `{format_price(ind['ma50'] or 0)}`\n"
            f"  • MA200: `{format_price(ind['ma200'] or 0)}`\n\n"
            f"🎯 *Tín hiệu hệ thống: {signal_badge(analysis['recommendation'])}*\n"
            f"📊 Điểm tổng hợp: `{analysis['score']}/8`\n"
        )

        # Telegram giới hạn 4096 ký tự / tin. Gửi header trước, AI commentary trong tin riêng nếu dài.
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Thêm watchlist", callback_data=f"watch_{symbol}")]
        ])
        await msg.edit_text(header, parse_mode="Markdown")
        # AI gửi tin riêng – không bị giới hạn của header + dễ format
        ai_msg = f"🤖 *AI Gemini phân tích:*\n\n{ai_text}"
        # Telegram cap: chia nhỏ nếu > 4000
        for chunk in [ai_msg[i:i+4000] for i in range(0, len(ai_msg), 4000)]:
            await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=keyboard if chunk == ai_msg[-len(chunk):] else None)
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi khi phân tích {symbol}: {e}")


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Cú pháp: `/watch VNM`", parse_mode="Markdown")
        return
    symbol = normalize_symbol(context.args[0])
    if not symbol:
        await update.message.reply_text("❌ Mã cổ phiếu không hợp lệ.", parse_mode="Markdown")
        return
    chat_id = str(update.effective_chat.id)
    if wm.add_symbol(chat_id, symbol):
        await update.message.reply_text(f"✅ Đã thêm *{symbol}* vào danh mục theo dõi!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ *{symbol}* đã có trong danh mục rồi.", parse_mode="Markdown")


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Cú pháp: `/unwatch VNM`", parse_mode="Markdown")
        return
    symbol = normalize_symbol(context.args[0])
    if not symbol:
        await update.message.reply_text("❌ Mã cổ phiếu không hợp lệ.", parse_mode="Markdown")
        return
    chat_id = str(update.effective_chat.id)
    if wm.remove_symbol(chat_id, symbol):
        await update.message.reply_text(f"🗑️ Đã xóa *{symbol}* khỏi danh mục.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ Không tìm thấy *{symbol}* trong danh mục.", parse_mode="Markdown")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    watchlist = wm.get_user_watchlist(chat_id)
    if not watchlist:
        await update.message.reply_text(
            "📋 Danh mục của bạn trống.\n"
            "Dùng `/watch VNM` để thêm cổ phiếu.",
            parse_mode="Markdown",
        )
        return
    msg = await update.message.reply_text("⏳ Đang cập nhật danh mục...")
    lines = ["📋 *Danh mục theo dõi của bạn:*\n"]
    for sym in watchlist:
        try:
            data = await get_historical_data(sym, 50)
            if len(data) >= 2:
                analysis = analyze_stock(data)
                last = data[-1]
                lines.append(
                    f"{analysis['emoji']} *{sym}*: {format_price(last['close'])} "
                    f"({analysis['price_info']['change_pct']:+.2f}%) – {analysis['recommendation_vn']}"
                )
            else:
                lines.append(f"⚪ *{sym}*: Không có dữ liệu")
        except Exception:
            lines.append(f"⚪ *{sym}*: Lỗi")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang lấy top movers...")
    try:
        movers = await get_top_movers(5)
        gainers = movers.get("top_gainers", [])
        losers = movers.get("top_losers", [])
        lines = ["🏆 *Top thị trường hôm nay*\n", "📈 *Tăng mạnh nhất:*"]
        for s in gainers:
            lines.append(f"  🟢 *{s['symbol']}*: {format_price(s['price'])} ({s['change_pct']:+.2f}%)")
        lines.append("\n📉 *Giảm mạnh nhất:*")
        for s in losers:
            lines.append(f"  🔴 *{s['symbol']}*: {format_price(s['price'])} ({s['change_pct']:+.2f}%)")
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {e}")


async def on_watch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("watch_"):
        return
    symbol = normalize_symbol(data.removeprefix("watch_"))
    if not symbol:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Mã cổ phiếu không hợp lệ.")
        return
    chat_id = str(query.message.chat_id)
    added = wm.add_symbol(chat_id, symbol)
    text = f"✅ Đã thêm *{symbol}* vào danh mục theo dõi!" if added else f"⚠️ *{symbol}* đã có trong danh mục rồi."
    await query.message.reply_text(text, parse_mode="Markdown")


# ─── Alert System ─────────────────────────────────────────────────────────────

async def send_signal_alerts(app: Application):
    """Quét watchlist và gửi alert khi có tín hiệu mạnh"""
    symbols = wm.get_all_unique_symbols()
    for symbol in symbols:
        try:
            data = await get_historical_data(symbol, 200)
            if len(data) < 30:
                continue
            analysis = analyze_stock(data)
            score = analysis.get("score", 0)
            # Chỉ alert khi tín hiệu mạnh (score >= 5 hoặc <= -5)
            if abs(score) < 5:
                continue
            last = data[-1]
            text = (
                f"🔔 *CẢNH BÁO TÍN HIỆU – {symbol}*\n\n"
                f"💰 Giá: {format_price(last['close'])} VNĐ\n"
                f"{signal_badge(analysis['recommendation'])}\n"
                f"📊 Điểm: {score}/8\n\n"
                f"Dùng `/analyze {symbol}` để xem chi tiết."
            )
            users = wm.get_all_users_for_symbol(symbol)
            for chat_id in users:
                if not str(chat_id).lstrip("-").isdigit():
                    continue
                try:
                    await app.bot.send_message(
                        chat_id=int(chat_id), text=text, parse_mode="Markdown"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Alert scan error for {symbol}: {e}")


# ─── Bot Factory ──────────────────────────────────────────────────────────────

def build_telegram_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("entry", cmd_entry))
    app.add_handler(CommandHandler("quick", cmd_quick))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CallbackQueryHandler(on_watch_callback, pattern=r"^watch_[A-Z0-9]{2,10}$"))
    return app
