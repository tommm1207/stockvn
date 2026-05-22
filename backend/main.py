import time
import os
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from telegram.ext import Application

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s [%(module)s] %(message)s",
)
logger = logging.getLogger(__name__)

from data_fetcher import (
    get_historical_data, get_current_quote, get_market_overview,
    get_top_movers, get_intraday_chart, get_fundamentals, get_deep_fundamentals, get_stock_news, POPULAR_STOCKS,
)
from technical_analysis import analyze_stock
from market_scanner import run_full_market_scan, get_market_scan_results, MARKET_SCAN_CACHE
from ai_analyzer import analyze_with_ai, get_market_commentary, chat_with_ai
from watchlist_manager import WatchlistManager
from portfolio_manager import PortfolioManager
from alert_manager import AlertManager
from telegram_bot import build_telegram_app, send_signal_alerts
from vn_symbols import VN_STOCKS
from database import init_db, check_db_health

APP_VERSION = "2.0.0"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]
wm = WatchlistManager()
pm = PortfolioManager()
am = AlertManager()
tg_app: Application = None
scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")
CHAT_ID_RE = re.compile(r"^-?\d{1,20}$|^web_[a-f0-9]{32}$")


def normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="Mã cổ phiếu không hợp lệ")
    return value


def normalize_chat_id(chat_id: str) -> str:
    value = chat_id.strip()
    if not CHAT_ID_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="Watchlist ID không hợp lệ")
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tg_app
    # Initialize SQLite database
    init_db()
    logger.info("Database initialized ✅")

    # Start Telegram bot
    if TELEGRAM_TOKEN:
        try:
            tg_app = build_telegram_app(TELEGRAM_TOKEN)
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot started ✅")
        except Exception as e:
            logger.warning(f"Telegram bot failed to start (network issue?): {e}. Web app vẫn chạy bình thường.")

    # Start initial full market scan
    asyncio.create_task(run_full_market_scan())

    # Schedule alert scans every 5 minutes
    async def scan_job():
        # Chạy market scanner 15 phút / lần (dùng cơ chế mod)
        if int(time.time() / 60) % 15 < 5:
            await run_full_market_scan()
            
        if tg_app:
            await send_signal_alerts(tg_app)
        await _evaluate_custom_alerts()

    scheduler.add_job(scan_job, "interval", minutes=5, id="signal_scan")
    scheduler.start()
    logger.info("Scheduler started")

    yield

    scheduler.shutdown()
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


app = FastAPI(title="Stock Analyzer API", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")
    icons_dir = os.path.join(FRONTEND_DIR, "icons")
    if os.path.exists(icons_dir):
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")


@app.get("/manifest.json")
async def manifest_json():
    return FileResponse(os.path.join(FRONTEND_DIR, "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(os.path.join(FRONTEND_DIR, "sw.js"), media_type="application/javascript")


@app.get("/favicon.ico")
async def favicon_ico():
    svg_path = os.path.join(FRONTEND_DIR, "icons", "icon.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404)


def frontend_file(filename: str):
    path = os.path.join(FRONTEND_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frontend file not found")
    return FileResponse(path)


# ─── Frontend Routes ──────────────────────────────────────────────────────────

@app.get("/")
async def root():
    if os.path.exists(FRONTEND_DIR):
        return frontend_file("index.html")
    return {"message": "Stock Analyzer API is running!"}


@app.get("/index.html")
async def index_page():
    return frontend_file("index.html")


@app.get("/stock.html")
async def stock_page():
    return frontend_file("stock.html")


@app.get("/watchlist.html")
async def watchlist_page():
    return frontend_file("watchlist.html")


@app.get("/portfolio.html")
async def portfolio_page():
    return frontend_file("portfolio.html")


@app.get("/scanner.html")
async def scanner_page():
    return frontend_file("scanner.html")


# ─── Stock API ────────────────────────────────────────────────────────────────

@app.get("/api/stock/{symbol}")
async def get_stock(symbol: str, days: int = 300):
    """Lấy dữ liệu + phân tích kỹ thuật cho một mã"""
    symbol = normalize_symbol(symbol)
    if days < 30 or days > 10000:
        raise HTTPException(status_code=400, detail="days phải nằm trong khoảng 30-10000")
    try:
        data = await get_historical_data(symbol, days)
        if len(data) < 30:
            raise HTTPException(status_code=404, detail=f"Không đủ dữ liệu cho mã {symbol}")
        analysis = analyze_stock(data)
        return {
            "symbol": symbol,
            "last_price": data[-1]["close"],
            "last_date": data[-1]["date"],
            "analysis": analysis,
            "raw_data": data,  # Trả về toàn bộ – frontend tự slice theo nút 3T/6T/1N
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/fundamentals")
async def get_stock_fundamentals(symbol: str):
    """Chỉ số cơ bản: P/E, P/B, EPS, vốn hoá, ROE, 52w high/low…"""
    symbol = normalize_symbol(symbol)
    try:
        f = await get_fundamentals(symbol)
        return {"symbol": symbol, "fundamentals": f}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/deep_fundamentals")
async def get_stock_deep_fundamentals(symbol: str):
    """Lấy báo cáo kết quả kinh doanh và bảng cân đối kế toán chuyên sâu (4 quý/năm gần nhất)"""
    symbol = normalize_symbol(symbol)
    try:
        f = await get_deep_fundamentals(symbol)
        return {"symbol": symbol, "deep_fundamentals": f}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/intraday")
async def get_stock_intraday(symbol: str, resolution: str = "15", hours: int = 72):
    """Nến intraday từ DNSE – resolution 1/5/15/30/60 phút"""
    symbol = normalize_symbol(symbol)
    if resolution not in {"1", "5", "15", "30", "60"}:
        raise HTTPException(status_code=400, detail="resolution phải là 1, 5, 15, 30 hoặc 60")
    if hours < 1 or hours > 720:
        raise HTTPException(status_code=400, detail="hours phải nằm trong khoảng 1-720")
    try:
        data = await get_intraday_chart(symbol, resolution, hours)
        return {"symbol": symbol, "resolution": resolution, "hours": hours, "raw_data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/ai")
async def get_stock_ai(symbol: str):
    """Lấy phân tích AI từ Gemini"""
    symbol = normalize_symbol(symbol)
    try:
        data = await get_historical_data(symbol, 300)
        if len(data) < 30:
            raise HTTPException(status_code=404, detail=f"Không đủ dữ liệu cho mã {symbol}")
        analysis = analyze_stock(data)
        ai_text = await analyze_with_ai(symbol, analysis)
        return {"symbol": symbol, "ai_analysis": ai_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/news")
async def get_stock_news_endpoint(symbol: str):
    """Lấy tin tức mới nhất về mã cổ phiếu"""
    symbol = normalize_symbol(symbol)
    try:
        news = await get_stock_news(symbol)
        return {"symbol": symbol, "news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{symbol}/news_sentiment")
async def get_stock_news_sentiment(symbol: str):
    """Dùng AI phân tích cảm xúc (sentiment) từ các tin tức mới nhất"""
    symbol = normalize_symbol(symbol)
    try:
        news = await get_stock_news(symbol, limit=5)
        if not news:
            return {"symbol": symbol, "sentiment": "neutral", "summary": "Không có tin tức nào nổi bật."}
        
        # Tạo prompt cho AI
        news_text = "\n".join([f"- {n['title']} ({n['date']})" for n in news])
        prompt = (
            f"Bạn là chuyên gia chứng khoán. Hãy đọc các tin tức mới nhất sau đây về mã cổ phiếu {symbol}:\n{news_text}\n\n"
            f"Yêu cầu:\n"
            f"1. Đánh giá tổng quan tâm lý (Sentiment) của các tin tức này. Chọn 1 trong 3 trạng thái: TÍCH CỰC, TIÊU CỰC, TRUNG LẬP.\n"
            f"2. Viết 2-3 câu ngắn gọn tóm tắt lý do tác động chính đến cổ phiếu.\n"
            f"Không dài dòng, trả về đúng format:\n"
            f"Trạng thái: [TÍCH CỰC/TIÊU CỰC/TRUNG LẬP]\n"
            f"Tóm tắt: [Nội dung tóm tắt]"
        )
        # Tái sử dụng chat_with_ai để phân tích
        ai_reply = await chat_with_ai(prompt, [])
        return {"symbol": symbol, "analysis": ai_reply, "news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Market API ───────────────────────────────────────────────────────────────

@app.get("/api/symbols")
async def list_symbols():
    """Danh sách mã CK VN cho autocomplete tìm kiếm"""
    return {"symbols": [{"symbol": s, "name": n} for s, n in VN_STOCKS]}


@app.get("/api/market/overview")
async def market_overview():
    """Tổng quan chỉ số thị trường"""
    try:
        overview = await get_market_overview()
        warnings = overview.pop("_warnings", [])
        commentary = await get_market_commentary(overview)
        result = {"overview": overview, "commentary": commentary}
        if warnings:
            result["warnings"] = warnings
        return result
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        return JSONResponse(
            status_code=200,
            content={
                "overview": {k: {"value": 0, "change": 0, "change_pct": 0} for k in ["VNINDEX", "HNX", "UPCOM"]},
                "commentary": "Không thể lấy dữ liệu thị trường lúc này.",
                "warnings": [str(e)],
            },
        )


@app.get("/api/market/top-movers")
async def top_movers():
    """Top tăng/giảm mạnh"""
    try:
        return await get_top_movers(10)
    except Exception as e:
        logger.error(f"Top movers error: {e}")
        return {"top_gainers": [], "top_losers": [], "warnings": [str(e)]}


# ─── Watchlist API ────────────────────────────────────────────────────────────

@app.get("/api/watchlist/{chat_id}")
async def get_watchlist(chat_id: str):
    chat_id = normalize_chat_id(chat_id)
    symbols = wm.get_user_watchlist(chat_id)
    return {"chat_id": chat_id, "symbols": symbols}


@app.post("/api/watchlist/{chat_id}/{symbol}")
async def add_to_watchlist(chat_id: str, symbol: str):
    chat_id = normalize_chat_id(chat_id)
    symbol = normalize_symbol(symbol)
    added = wm.add_symbol(chat_id, symbol)
    return {"success": added, "symbol": symbol, "message": "Đã thêm" if added else "Đã tồn tại"}


@app.delete("/api/watchlist/{chat_id}/{symbol}")
async def remove_from_watchlist(chat_id: str, symbol: str):
    chat_id = normalize_chat_id(chat_id)
    symbol = normalize_symbol(symbol)
    removed = wm.remove_symbol(chat_id, symbol)
    return {"success": removed, "symbol": symbol}


@app.get("/api/watchlist/{chat_id}/analyze")
async def analyze_watchlist(chat_id: str):
    """Phân tích toàn bộ watchlist"""
    chat_id = normalize_chat_id(chat_id)
    symbols = wm.get_user_watchlist(chat_id)
    if not symbols:
        return {"symbols": []}
    results = []
    for sym in symbols:
        try:
            data = await get_historical_data(sym, 200)
            if len(data) >= 30:
                analysis = analyze_stock(data)
                results.append({
                    "symbol": sym,
                    "price": data[-1]["close"],
                    "change_pct": analysis["price_info"]["change_pct"],
                    "recommendation": analysis["recommendation"],
                    "recommendation_vn": analysis["recommendation_vn"],
                    "score": analysis["score"],
                    "emoji": analysis["emoji"],
                })
        except Exception:
            pass
    return {"symbols": results}


# ─── Portfolio API ────────────────────────────────────────────────────────────

class TradeRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    price: float
    fee: float = 0
    trade_date: str = None
    note: str = None


class TradeUpdateRequest(BaseModel):
    symbol: str = None
    side: str = None
    quantity: float = None
    price: float = None
    fee: float = None
    trade_date: str = None
    note: str = None


@app.get("/api/portfolio/{user_id}")
async def get_portfolio(user_id: str):
    """Get portfolio summary with P/L"""
    user_id = normalize_chat_id(user_id)
    holdings = pm.get_holdings(user_id)
    # Fetch current prices for P/L calculation
    prices = {}
    for h in holdings:
        try:
            data = await get_historical_data(h["symbol"], days=5)
            if data:
                prices[h["symbol"]] = data[-1]["close"]
        except Exception:
            pass
    summary = pm.get_portfolio_summary(user_id, prices)
    return {"user_id": user_id, **summary}


@app.get("/api/portfolio/{user_id}/trades")
async def get_trades(user_id: str, symbol: str = None):
    """Get trade history"""
    user_id = normalize_chat_id(user_id)
    if symbol:
        symbol = normalize_symbol(symbol)
    trades = pm.get_trades(user_id, symbol)
    return {"user_id": user_id, "trades": trades}


@app.post("/api/portfolio/{user_id}/trades")
async def add_trade(user_id: str, req: TradeRequest):
    """Add a new trade"""
    user_id = normalize_chat_id(user_id)
    symbol = normalize_symbol(req.symbol)
    try:
        trade = pm.add_trade(
            user_id, symbol, req.side, req.quantity,
            req.price, req.fee, req.trade_date, req.note,
        )
        return {"success": True, "trade": trade}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/portfolio/{user_id}/trades/{trade_id}")
async def update_trade(user_id: str, trade_id: int, req: TradeUpdateRequest):
    """Update a trade"""
    user_id = normalize_chat_id(user_id)
    updates = req.model_dump(exclude_none=True)
    if "symbol" in updates:
        updates["symbol"] = normalize_symbol(updates["symbol"])
    try:
        updated = pm.update_trade(user_id, trade_id, **updates)
        return {"success": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/portfolio/{user_id}/trades/{trade_id}")
async def delete_trade(user_id: str, trade_id: int):
    """Delete a trade"""
    user_id = normalize_chat_id(user_id)
    deleted = pm.delete_trade(user_id, trade_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"success": True}


# ─── Full Market Scanner API ──────────────────────────────────────────────────

@app.get("/api/market-signals")
async def get_market_signals():
    """Lấy dữ liệu toàn thị trường từ cache."""
    return get_market_scan_results()

@app.get("/api/stock/{symbol}/entry-stoploss")
async def get_entry_stoploss(symbol: str):
    """Tính điểm vào và cắt lỗ cho 1 mã cụ thể."""
    data = await get_historical_data(symbol, 60)
    if not data:
        raise HTTPException(status_code=404, detail="Không tìm thấy dữ liệu")
        
    analysis = analyze_stock(data)
    return {
        "symbol": symbol.upper(),
        "price": analysis["price_info"]["current"],
        "trade_plan": analysis.get("trade_plan", {}),
        "advanced_signals": analysis.get("advanced_signals", [])
    }

# ─── Scanner API ──────────────────────────────────────────────────────────────

@app.get("/api/scanner")
async def stock_scanner(
    symbols: str = None,
    recommendation: str = None,
    min_score: int = None,
    max_score: int = None,
    min_rsi: float = None,
    max_rsi: float = None,
    min_volume_ratio: float = None,
    macd_cross: str = None,
    bb_position: str = None,
    sort: str = "score",
    limit: int = 50,
):
    """Stock scanner with filters – scans POPULAR_STOCKS by default"""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit phải nằm trong 1-200")

    # Determine symbol universe
    if symbols:
        sym_list = [normalize_symbol(s) for s in symbols.split(",") if s.strip()]
    else:
        sym_list = POPULAR_STOCKS

    results = []
    warnings = []

    async def scan_one(sym):
        try:
            data = await get_historical_data(sym, 200)
            if len(data) < 30:
                return None
            analysis = analyze_stock(data)
            ind = analysis.get("indicators", {})
            return {
                "symbol": sym,
                "price": data[-1]["close"],
                "change_pct": analysis["price_info"]["change_pct"],
                "recommendation": analysis["recommendation"],
                "recommendation_vn": analysis["recommendation_vn"],
                "score": analysis["score"],
                "emoji": analysis["emoji"],
                "rsi": ind.get("rsi", 50),
                "macd_cross": ind.get("macd", {}).get("cross", "none"),
                "macd_histogram": ind.get("macd", {}).get("histogram", 0),
                "bb_position": ind.get("bollinger", {}).get("position", "middle"),
                "volume_ratio": ind.get("volume", {}).get("ratio", 1),
                "ma20": ind.get("ma20"),
                "ma50": ind.get("ma50"),
            }
        except Exception as e:
            warnings.append(f"{sym}: {str(e)[:50]}")
            return None

    raw_results = await asyncio.gather(*[scan_one(s) for s in sym_list], return_exceptions=True)
    for r in raw_results:
        if isinstance(r, dict) and r:
            results.append(r)

    # Apply filters
    if recommendation:
        results = [r for r in results if r["recommendation"] == recommendation.upper()]
    if min_score is not None:
        results = [r for r in results if r["score"] >= min_score]
    if max_score is not None:
        results = [r for r in results if r["score"] <= max_score]
    if min_rsi is not None:
        results = [r for r in results if r["rsi"] >= min_rsi]
    if max_rsi is not None:
        results = [r for r in results if r["rsi"] <= max_rsi]
    if min_volume_ratio is not None:
        results = [r for r in results if r["volume_ratio"] >= min_volume_ratio]
    if macd_cross:
        results = [r for r in results if r["macd_cross"] == macd_cross]
    if bb_position:
        results = [r for r in results if r["bb_position"] == bb_position]

    # Sort
    sort_keys = {
        "score": lambda x: x["score"],
        "change_pct": lambda x: x["change_pct"],
        "volume_ratio": lambda x: x["volume_ratio"],
        "rsi_low": lambda x: x["rsi"],
        "rsi_high": lambda x: -x["rsi"],
    }
    sort_fn = sort_keys.get(sort, sort_keys["score"])
    results.sort(key=sort_fn, reverse=(sort not in ("rsi_low",)))

    result = {"results": results[:limit], "total": len(results), "scanned": len(sym_list)}
    if warnings:
        result["warnings"] = warnings
    return result


# ─── Alert API ────────────────────────────────────────────────────────────────

class AlertRuleRequest(BaseModel):
    rule_type: str
    operator: str = "gt"
    threshold: float = None
    symbol: str = None
    channel: str = "telegram"
    cooldown_minutes: int = 60


class AlertRuleUpdateRequest(BaseModel):
    rule_type: str = None
    operator: str = None
    threshold: float = None
    symbol: str = None
    channel: str = None
    cooldown_minutes: int = None
    enabled: int = None


@app.get("/api/alerts/{user_id}")
async def get_alerts(user_id: str):
    """Get all alert rules for a user"""
    user_id = normalize_chat_id(user_id)
    rules = am.get_rules(user_id)
    return {"user_id": user_id, "rules": rules}


@app.post("/api/alerts/{user_id}")
async def create_alert(user_id: str, req: AlertRuleRequest):
    """Create a new alert rule"""
    user_id = normalize_chat_id(user_id)
    symbol = normalize_symbol(req.symbol) if req.symbol else None
    try:
        rule = am.create_rule(
            user_id, req.rule_type, req.operator, req.threshold,
            symbol, req.channel, req.cooldown_minutes,
        )
        return {"success": True, "rule": rule}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/alerts/{user_id}/{rule_id}")
async def update_alert(user_id: str, rule_id: int, req: AlertRuleUpdateRequest):
    """Update an alert rule"""
    user_id = normalize_chat_id(user_id)
    updates = req.model_dump(exclude_none=True)
    if "symbol" in updates and updates["symbol"]:
        updates["symbol"] = normalize_symbol(updates["symbol"])
    try:
        updated = am.update_rule(user_id, rule_id, **updates)
        return {"success": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/alerts/{user_id}/{rule_id}")
async def delete_alert(user_id: str, rule_id: int):
    """Delete an alert rule"""
    user_id = normalize_chat_id(user_id)
    deleted = am.delete_rule(user_id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True}


# ─── Chat API ─────────────────────────────────────────────────────────────────

MAX_CHAT_MESSAGE_LENGTH = 2000

class ChatRequest(BaseModel):
    message: str
    history: list = Field(default_factory=list)

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Chatbot AI hỏi đáp về chứng khoán"""
    if len(req.message) > MAX_CHAT_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Tin nhắn quá dài. Tối đa {MAX_CHAT_MESSAGE_LENGTH} ký tự.",
        )
    # Truncate history to prevent huge prompts
    history = req.history[-6:] if req.history else []
    try:
        reply = await chat_with_ai(req.message, history)
        return {"reply": reply}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── System API ───────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check – trạng thái app + database"""
    db_health = check_db_health()
    status = "ok" if db_health["status"] == "ok" else "degraded"
    status_code = 200 if status == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "database": db_health,
            "version": APP_VERSION,
        },
    )


@app.get("/api/version")
async def version_info():
    """Version and build info"""
    return {
        "version": APP_VERSION,
        "app": "StockVN",
        "api": "FastAPI",
    }


# ─── Alert Evaluation ────────────────────────────────────────────────────────

async def _evaluate_custom_alerts():
    """Evaluate all enabled custom alert rules."""
    rules = am.get_enabled_rules()
    if not rules:
        return

    # Group rules by symbol
    symbol_rules = {}
    for rule in rules:
        sym = rule.get("symbol")
        if sym:
            symbol_rules.setdefault(sym, []).append(rule)

    for sym, sym_rules in symbol_rules.items():
        try:
            data = await get_historical_data(sym, 200)
            if len(data) < 30:
                continue
            analysis = analyze_stock(data)
            current_price = data[-1]["close"]

            for rule in sym_rules:
                if not am.should_fire(rule):
                    continue
                if am.check_rule(rule, analysis, current_price):
                    am.mark_triggered(rule["id"])
                    # Send notification based on channel
                    if rule.get("channel") in ("telegram", "both") and tg_app:
                        user_id = rule["user_id"]
                        if str(user_id).lstrip("-").isdigit():
                            try:
                                msg = (
                                    f"🔔 *Alert: {sym}*\n"
                                    f"Rule: {rule['rule_type']} {rule.get('operator', '')} {rule.get('threshold', '')}\n"
                                    f"Giá hiện tại: {current_price:,.0f}\n"
                                    f"Score: {analysis.get('score', 0)}/8"
                                )
                                await tg_app.bot.send_message(
                                    chat_id=int(user_id), text=msg, parse_mode="Markdown"
                                )
                            except Exception:
                                pass
                    logger.info(f"Alert fired: rule {rule['id']} for {sym} user {rule['user_id']}")
        except Exception as e:
            logger.error(f"Alert eval error for {sym}: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
