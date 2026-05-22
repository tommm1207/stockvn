"""
ai_analyzer.py – Gemini AI integration with safety & quality features.

Features:
  - Multi-model fallback (2.5-flash → 2.0-flash → 2.0-flash-lite)
  - AI result cache by symbol/date/score (TTL configurable)
  - Fallback to local technical summary when Gemini fails
  - Standardized output sections
  - Message length validation
  - Disclaimer in all outputs
"""

import os
import re
import time
import logging
import asyncio
import httpx
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List, Dict

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "minimaxai/minimax-m2.7")
NVIDIA_TIMEOUT_SECONDS = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "45"))
CHAT_DATA_TIMEOUT_SECONDS = float(os.getenv("CHAT_DATA_TIMEOUT_SECONDS", "8"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Model chain theo thứ tự ưu tiên
GEMINI_MODEL_NAMES = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]
_models = {name: genai.GenerativeModel(name) for name in GEMINI_MODEL_NAMES}

# ─── AI Cache ─────────────────────────────────────────────────────────────────
AI_CACHE_TTL = int(os.getenv("AI_CACHE_TTL_SECONDS", "600"))  # 10 minutes default
_ai_cache: Dict[str, tuple] = {}  # key -> (timestamp, text)
_commentary_cache: Dict[str, tuple] = {}
_COMMENTARY_TTL = 600


def _ai_cache_key(symbol: str, last_date: str, score: int) -> str:
    """Cache key based on symbol, last trading date, and score."""
    return f"{symbol}|{last_date}|{score}"


async def _generate_gemini(prompt: str) -> str:
    """Call Gemini with fallback between configured model names."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY chưa được cấu hình")

    last_err = None
    for name in GEMINI_MODEL_NAMES:
        try:
            response = await _models[name].generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Model {name} gặp lỗi: {e}. Thử model tiếp theo…")
            last_err = e
            continue
    raise last_err or RuntimeError("Tất cả model Gemini đều không khả dụng")


async def _generate_nvidia(prompt: str) -> str:
    """Call NVIDIA NIM OpenAI-compatible chat completions API."""
    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY chưa được cấu hình")

    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là StockBot, trợ lý phân tích chứng khoán Việt Nam. "
                    "Trả lời bằng tiếng Việt, dùng đúng số liệu người dùng cung cấp, "
                    "không bịa dữ liệu và luôn nhắc đây không phải khuyến nghị đầu tư."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "top_p": 0.9,
        "max_tokens": 1400,
    }

    url = f"{NVIDIA_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=NVIDIA_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"NVIDIA response không hợp lệ: {data}") from e
    if not text:
        raise RuntimeError("NVIDIA trả về nội dung rỗng")
    return text


async def _generate_groq(prompt: str) -> str:
    """Call Groq API (Llama 3 70B). Fast and powerful fallback."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY chưa được cấu hình")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là StockBot, trợ lý phân tích chứng khoán Việt Nam. "
                    "Trả lời bằng tiếng Việt chuyên nghiệp, dùng đúng số liệu người dùng cung cấp, "
                    "không bịa dữ liệu và luôn nhắc đây không phải khuyến nghị đầu tư."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "top_p": 0.9,
        "max_tokens": 1400,
    }

    url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Groq response không hợp lệ: {data}") from e
    if not text:
        raise RuntimeError("Groq trả về nội dung rỗng")
    return text


async def _generate(prompt: str) -> str:
    """Generate text using NVIDIA NIM (Llama 4) first, then Groq, then Gemini."""
    errors = []

    try:
        return await _generate_nvidia(prompt)
    except Exception as e:
        errors.append(f"NVIDIA: {e}")
        logger.warning(f"NVIDIA provider failed, trying Groq: {e}")

    try:
        return await _generate_groq(prompt)
    except Exception as e:
        errors.append(f"Groq: {e}")
        logger.warning(f"Groq provider failed, trying Gemini: {e}")

    try:
        return await _generate_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini: {e}")
        logger.warning(f"Gemini provider failed: {e}")

    raise RuntimeError("Không provider AI nào khả dụng. " + " | ".join(errors))


def _build_local_fallback(symbol: str, analysis: dict) -> str:
    """Generate a technical summary without AI when Gemini is unavailable."""
    indicators = analysis.get("indicators", {})
    signals = analysis.get("signals", [])
    price_info = analysis.get("price_info", {})
    rsi = indicators.get("rsi", 50)
    macd = indicators.get("macd", {})
    bb = indicators.get("bollinger", {})
    vol = indicators.get("volume", {})
    ma20 = indicators.get("ma20") or 0
    ma50 = indicators.get("ma50") or 0
    ma200 = indicators.get("ma200") or 0

    # Build structured summary
    sections = []

    sections.append(f"*📊 Tổng quan*\nGiá hiện tại: {price_info.get('current', 0):,.0f} VNĐ ({price_info.get('change_pct', 0):+.2f}%). "
                    f"Khuyến nghị hệ thống: {analysis.get('emoji', '')} {analysis.get('recommendation_vn', 'CÂN NHẮC')} (điểm {analysis.get('score', 0)}/8).")

    # Trend
    trend_parts = []
    if ma20 and ma50:
        if ma20 > ma50:
            trend_parts.append(f"MA20 ({ma20:,.0f}) > MA50 ({ma50:,.0f}) – xu hướng tăng ngắn hạn")
        else:
            trend_parts.append(f"MA20 ({ma20:,.0f}) < MA50 ({ma50:,.0f}) – xu hướng giảm ngắn hạn")
    if ma200:
        current = price_info.get("current", 0)
        if current > ma200:
            trend_parts.append(f"giá trên MA200 ({ma200:,.0f}) – xu hướng dài hạn tích cực")
        else:
            trend_parts.append(f"giá dưới MA200 ({ma200:,.0f}) – xu hướng dài hạn tiêu cực")
    sections.append(f"*📈 Xu hướng*\n" + ". ".join(trend_parts) + "." if trend_parts else "")

    # Support/Resistance
    sections.append(f"*🎯 Hỗ trợ – Kháng cự*\n"
                    f"BB dưới: {bb.get('lower', 0):,.0f} | BB giữa: {bb.get('middle', 0):,.0f} | BB trên: {bb.get('upper', 0):,.0f}. "
                    f"Vị trí: {bb.get('position', 'N/A')}.")

    # Momentum
    rsi_desc = "quá bán" if rsi < 30 else "quá mua" if rsi > 70 else "trung tính"
    macd_desc = "bullish cross" if macd.get("cross") == "bullish" else "bearish cross" if macd.get("cross") == "bearish" else "không cross"
    sections.append(f"*⚡ Động lượng*\n"
                    f"RSI(14): {rsi} ({rsi_desc}). MACD histogram: {macd.get('histogram', 0):+.4f} ({macd_desc}). "
                    f"Volume ratio: {vol.get('ratio', 1):.2f}x.")

    # Risks
    risks = []
    if rsi > 70:
        risks.append("RSI quá mua – rủi ro điều chỉnh")
    if rsi < 30:
        risks.append("RSI quá bán – có thể tiếp tục giảm")
    if vol.get("signal") == "surge_down":
        risks.append("Khối lượng tăng mạnh kèm giá giảm")
    if macd.get("cross") == "bearish":
        risks.append("MACD death cross")
    if not risks:
        risks.append("Không có tín hiệu rủi ro đặc biệt")
    sections.append("*⚠️ Rủi ro*\n" + "\n".join(f"• {r}" for r in risks[:3]))

    # Disclaimer
    sections.append("_⚠️ Phân tích kỹ thuật tự động, không phải khuyến nghị đầu tư. Đầu tư có rủi ro._")

    return "\n\n".join(s for s in sections if s)


async def analyze_with_ai(symbol: str, analysis: dict, raw_data: list = None) -> str:
    """Gọi Gemini AI cho phân tích chi tiết có cấu trúc.
    Có cache theo symbol/date/score. Fallback local nếu Gemini lỗi."""
    indicators = analysis.get("indicators", {})
    signals = analysis.get("signals", [])
    price_info = analysis.get("price_info", {})
    rsi = indicators.get("rsi", 50)
    macd = indicators.get("macd", {})
    bb = indicators.get("bollinger", {})
    vol = indicators.get("volume", {})
    ma20 = indicators.get("ma20") or 0
    ma50 = indicators.get("ma50") or 0
    ma200 = indicators.get("ma200") or 0

    # Check AI cache
    last_date = ""
    if raw_data and raw_data:
        last_date = raw_data[-1].get("date", "")
    cache_key = _ai_cache_key(symbol, last_date, analysis.get("score", 0))
    cached = _ai_cache.get(cache_key)
    if cached and time.time() - cached[0] < AI_CACHE_TTL:
        return cached[1]

    signal_notes = "\n".join([f"  • {s.get('note', '')}" for s in signals])

    advanced = analysis.get("advanced_signals", [])
    adv_text = ""
    if advanced:
        adv_text = "\nCÁC TÍN HIỆU ĐẶC BIỆT TỪ SCANNER:\n" + "\n".join([f"  • {s.get('emoji', '')} {s.get('name', '')}: {s.get('note', '')}" for s in advanced])
    
    tp = analysis.get("trade_plan", {})
    tp_text = ""
    if tp and tp.get("entry"):
        tp_text = f"\nKẾ HOẠCH GIAO DỊCH GỢI Ý:\n  • Vùng Mua (Entry): {tp.get('entry', 0):,.0f}\n  • Cắt Lỗ (Stoploss): {tp.get('stoploss', 0):,.0f}\n  • Chốt Lời (Target): {tp.get('target', 0):,.0f}\n"

    extra = ""
    if raw_data and len(raw_data) >= 6:
        last = raw_data[-1]
        chg_5d = (last["close"] - raw_data[-6]["close"]) / raw_data[-6]["close"] * 100 if raw_data[-6]["close"] else 0
        recent = raw_data[-20:]
        high_20 = max(b["high"] for b in recent)
        low_20 = min(b["low"] for b in recent)
        chg_60d = 0
        if len(raw_data) >= 61 and raw_data[-61]["close"]:
            chg_60d = (last["close"] - raw_data[-61]["close"]) / raw_data[-61]["close"] * 100
        extra = (
            f"\nBIẾN ĐỘNG:\n"
            f"  • 5 phiên: {chg_5d:+.2f}% | 60 phiên: {chg_60d:+.2f}%\n"
            f"  • Đỉnh 20 phiên: {high_20:,.0f} | Đáy 20 phiên: {low_20:,.0f}\n"
            f"  • Volume hiện tại: {last['volume']:,} (tỉ lệ {vol.get('ratio', 1):.2f}x trung bình 20 phiên)\n"
        )

    prompt = f"""Bạn là chuyên gia phân tích chứng khoán Việt Nam, 10 năm kinh nghiệm.

DỮ LIỆU MÃ {symbol.upper()}:
GIÁ:
  • Hiện tại: {price_info.get('current', 0):,.0f} VNĐ ({price_info.get('change_pct', 0):+.2f}%)
{extra}
CHỈ BÁO:
  • RSI(14): {rsi} {'(quá bán)' if rsi < 30 else '(quá mua)' if rsi > 70 else '(trung tính)'}
  • MACD: {macd.get('macd', 0):.2f} | Signal: {macd.get('signal', 0):.2f} | Hist: {macd.get('histogram', 0):.2f} | Cross: {macd.get('cross', 'none')}
  • MA20: {ma20:,.0f} | MA50: {ma50:,.0f} | MA200: {ma200:,.0f}
  • Bollinger: {bb.get('lower', 0):,.0f} – {bb.get('middle', 0):,.0f} – {bb.get('upper', 0):,.0f} (vị trí: {bb.get('position', '?')})

TÍN HIỆU CHI TIẾT:
{signal_notes}
{adv_text}
{tp_text}
KHUYẾN NGHỊ HỆ THỐNG: {analysis.get('emoji', '')} {analysis.get('recommendation_vn', '')} (điểm {analysis.get('score', 0)}/8)

VIẾT PHÂN TÍCH CHI TIẾT THEO 6 PHẦN SAU – mỗi phần 2-3 câu, dùng số liệu THỰC TẾ ở trên, KHÔNG bịa số.
Đặc biệt phần "Gợi ý hành động", phải GIẢI THÍCH RÕ tại sao mã này lại có tín hiệu đặc biệt đó (nếu có) và nhận xét tính hợp lý của Kế Hoạch Giao Dịch:

*📊 Tổng quan*
[Giá hiện tại, biến động ngắn/trung hạn]

*📈 Xu hướng & Chart*
[Phân tích từ MA20/50/200, vị trí giá so với MA, ý nghĩa giao cắt]

*🎯 Hỗ trợ – Kháng cự*
[Vùng giá cụ thể từ MA, BB, đỉnh-đáy 20 phiên]

*⚡ Động lượng*
[RSI, MACD, khối lượng giao dịch]

*⚠️ Rủi ro chính*
[2-3 rủi ro cụ thể]

*💡 Gợi ý hành động*
[Vùng giá mua/bán/chờ cụ thể, cắt lỗ]

DÙNG ĐỊNH DẠNG TELEGRAM MARKDOWN:
- Bold dùng *một asterisk* (KHÔNG dùng **hai** dấu sao)
- KHÔNG dùng heading # ##
- Kết thúc bằng disclaimer: _⚠️ Phân tích tham khảo, không phải khuyến nghị đầu tư._
- KHÔNG bảo đảm lợi nhuận."""

    try:
        result = await _generate(prompt)
        _ai_cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logger.error(f"Gemini AI error for {symbol}: {e}")
        fallback = _build_local_fallback(symbol, analysis)
        _ai_cache[cache_key] = (time.time(), fallback)
        return fallback


async def get_market_commentary(overview: dict) -> str:
    """Bình luận tổng quan thị trường từ Gemini (có cache 10 phút)"""
    vnindex = overview.get("VNINDEX", {})
    hnx = overview.get("HNX", {})
    upcom = overview.get("UPCOM", {})

    cache_key = f"{vnindex.get('value')}|{hnx.get('value')}|{upcom.get('value')}"
    now = time.time()
    cached = _commentary_cache.get(cache_key)
    if cached and now - cached[0] < _COMMENTARY_TTL:
        return cached[1]

    prompt = f"""Bạn là nhà phân tích thị trường chứng khoán Việt Nam.

Dữ liệu thị trường hôm nay:
- VN-Index: {vnindex.get('value', 0):,.2f} ({vnindex.get('change_pct', 0):+.2f}%)
- HNX-Index: {hnx.get('value', 0):,.2f} ({hnx.get('change_pct', 0):+.2f}%)
- UPCOM-Index: {upcom.get('value', 0):,.2f} ({upcom.get('change_pct', 0):+.2f}%)

Viết nhận xét thị trường ngắn gọn (2-3 câu) bằng tiếng Việt, tự nhiên, về xu hướng chung hôm nay. KHÔNG bảo đảm kết quả đầu tư."""

    try:
        text = await _generate(prompt)
        _commentary_cache[cache_key] = (now, text)
        return text
    except Exception as e:
        logger.error(f"Gemini market commentary error: {e}")
        # Fallback commentary
        vn_val = vnindex.get('value', 0)
        vn_chg = vnindex.get('change_pct', 0)
        if vn_val == 0:
            return "Không thể lấy dữ liệu thị trường lúc này."
        direction = "tăng" if vn_chg >= 0 else "giảm"
        return (f"VN-Index {direction} {abs(vn_chg):.2f}%, đạt {vn_val:,.2f} điểm. "
                f"Nhà đầu tư cần thận trọng và quản lý rủi ro phù hợp.")


def _extract_symbol(message: str) -> str | None:
    """Tìm mã CK trong tin nhắn."""
    m = re.search(r"/analy[sz]e\s+([A-Za-z0-9]{2,10})\b", message, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    candidates = re.findall(r"\b([A-Za-z0-9]{2,10})\b", message)
    blacklist = {
        "AI", "VN", "USD", "VND", "OK",
        "EPS", "PE", "PB", "ROE", "ROA",
        "RSI", "MACD", "MA", "SMA", "EMA", "BB",
        "HOSE", "HNX", "UPCOM", "VNINDEX", "GDP", "CPI",
    }
    known_symbols = None
    try:
        from vn_symbols import VN_STOCKS
        known_symbols = {symbol for symbol, _ in VN_STOCKS}
    except Exception:
        pass

    for c in candidates:
        value = c.upper()
        if value in blacklist:
            continue
        if known_symbols is not None and value not in known_symbols:
            continue
        return value
    return None


async def _fetch_analysis_snapshot(symbol: str) -> str:
    """Lấy snapshot phân tích kỹ thuật đầy đủ cho 1 mã – inject vào prompt Gemini."""
    try:
        from data_fetcher import get_historical_data
        from technical_analysis import analyze_stock

        data = await asyncio.wait_for(get_historical_data(symbol, 200), timeout=CHAT_DATA_TIMEOUT_SECONDS)
        if len(data) < 30:
            return ""
        an = analyze_stock(data)
        ind = an.get("indicators", {})
        macd = ind.get("macd", {})
        bb = ind.get("bollinger", {})
        vol = ind.get("volume", {})
        last = data[-1]
        prev = data[-2] if len(data) >= 2 else last
        change_pct = (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0

        recent = data[-20:]
        high_20 = max(b["high"] for b in recent)
        low_20 = min(b["low"] for b in recent)
        chg_5d = (last["close"] - data[-6]["close"]) / data[-6]["close"] * 100 if len(data) >= 6 and data[-6]["close"] else 0
        chg_60d = (last["close"] - data[-61]["close"]) / data[-61]["close"] * 100 if len(data) >= 61 and data[-61]["close"] else 0
        avg_vol_20 = sum(b["volume"] for b in recent) / len(recent)

        signal_notes = "\n".join(f"  • {s.get('note', '')}" for s in an.get("signals", []))

        return (
            f"\nDỮ LIỆU THỰC TẾ MÃ {symbol} – ngày {last['date']}:\n"
            f"GIÁ:\n"
            f"  • Hiện tại: {last['close']:,.0f} VNĐ ({change_pct:+.2f}% phiên qua)\n"
            f"  • 5 phiên: {chg_5d:+.2f}% | 60 phiên: {chg_60d:+.2f}%\n"
            f"  • Cao nhất 20 phiên: {high_20:,.0f} | Thấp nhất 20 phiên: {low_20:,.0f}\n"
            f"CHỈ BÁO KỸ THUẬT:\n"
            f"  • RSI(14): {ind.get('rsi', 0)} {'(quá bán)' if ind.get('rsi', 50) < 30 else '(quá mua)' if ind.get('rsi', 50) > 70 else '(trung tính)'}\n"
            f"  • MACD: {macd.get('macd', 0):.2f} / Signal {macd.get('signal', 0):.2f} / Hist {macd.get('histogram', 0):.2f} – Cross: {macd.get('cross', 'none')}\n"
            f"  • MA20: {ind.get('ma20', 0):,.0f} | MA50: {ind.get('ma50', 0):,.0f} | MA200: {ind.get('ma200', 0):,.0f}\n"
            f"  • Bollinger: {bb.get('lower', 0):,.0f} – {bb.get('middle', 0):,.0f} – {bb.get('upper', 0):,.0f} (vị trí: {bb.get('position', '?')})\n"
            f"  • Khối lượng: {last['volume']:,} (trung bình 20 phiên: {avg_vol_20:,.0f}, tỉ lệ {vol.get('ratio', 1):.2f}x)\n"
            f"TÍN HIỆU CHI TIẾT:\n{signal_notes}\n"
            f"KHUYẾN NGHỊ HỆ THỐNG: {an.get('emoji', '')} {an.get('recommendation_vn', '')} (điểm {an.get('score', 0)}/8)\n"
        )
    except Exception as e:
        logger.warning(f"Snapshot fetch error for {symbol}: {e}")
        return ""


async def _build_symbol_chat_fallback(symbol: str) -> str:
    """Build a useful stock answer from local data when Gemini chat is unavailable."""
    try:
        from data_fetcher import get_historical_data
        from technical_analysis import analyze_stock

        data = await asyncio.wait_for(get_historical_data(symbol, 200), timeout=CHAT_DATA_TIMEOUT_SECONDS)
        if len(data) < 30:
            return (
                f"Hiện chưa đủ dữ liệu để phân tích mã {symbol}. "
                "Bạn thử lại sau hoặc kiểm tra mã cổ phiếu có đúng không."
            )
        analysis = analyze_stock(data)
        return _build_local_fallback(symbol, analysis)
    except Exception as e:
        logger.warning(f"Symbol chat fallback error for {symbol}: {e}")
        return (
            f"Hiện không lấy được dữ liệu phân tích cho {symbol}. "
            "Bạn thử lại sau ít phút hoặc kiểm tra kết nối dữ liệu."
        )


async def _build_market_chat_fallback() -> str:
    """Build market overview from local data without AI providers."""
    try:
        from data_fetcher import get_market_overview

        overview = await asyncio.wait_for(get_market_overview(), timeout=CHAT_DATA_TIMEOUT_SECONDS)
        warnings = overview.pop("_warnings", [])
        vnindex = overview.get("VNINDEX", {})
        hnx = overview.get("HNX", {})
        upcom = overview.get("UPCOM", {})

        def line(name: str, item: dict) -> str:
            value = item.get("value", 0)
            change_pct = item.get("change_pct", 0)
            direction = "tăng" if change_pct >= 0 else "giảm"
            return f"- {name}: {value:,.2f} điểm, {direction} {abs(change_pct):.2f}%"

        vn_chg = vnindex.get("change_pct", 0)
        mood = "tích cực nhẹ" if vn_chg > 0.3 else "tiêu cực" if vn_chg < -0.3 else "giằng co"
        text = (
            "*Tổng quan thị trường*\n"
            f"{line('VN-Index', vnindex)}\n"
            f"{line('HNX-Index', hnx)}\n"
            f"{line('UPCOM-Index', upcom)}\n\n"
            f"Diễn biến chung đang nghiêng về trạng thái *{mood}*. "
            "Nên ưu tiên quản trị tỷ trọng, tránh mua đuổi khi tín hiệu kỹ thuật chưa xác nhận rõ.\n\n"
            "_Thông tin tham khảo, không phải khuyến nghị đầu tư._"
        )
        if warnings:
            text += f"\n\n_Dữ liệu có cảnh báo: {'; '.join(warnings[:2])}_"
        return text
    except Exception as e:
        logger.warning(f"Market chat fallback error: {e}")
        return (
            "Hiện chưa lấy được dữ liệu thị trường. Bạn thử tải lại dashboard hoặc kiểm tra backend/data source.\n\n"
            "_Thông tin tham khảo, không phải khuyến nghị đầu tư._"
        )


def _build_general_chat_fallback(message: str) -> str:
    """Rule-based answers for common questions when Gemini chat is unavailable."""
    msg = message.lower()

    if msg.strip() in {"hi", "hello", "hey", "chào", "xin chào", "chao", "alo"}:
        return (
            "Chào bạn. StockBot đang sẵn sàng hỗ trợ phân tích cổ phiếu Việt Nam.\n\n"
            "Bạn có thể nhập mã như `VNM`, `HPG`, `FPT`, hoặc hỏi nhanh: `RSI là gì`, `MACD là gì`, `thị trường hôm nay thế nào`."
        )
    if "rsi" in msg:
        return (
            "*RSI* là chỉ báo đo sức mạnh dao động giá, thường dùng chu kỳ 14 phiên.\n"
            "- RSI dưới 30: cổ phiếu có thể đang quá bán.\n"
            "- RSI trên 70: cổ phiếu có thể đang quá mua.\n"
            "- RSI 40-60: vùng trung tính, cần kết hợp xu hướng và khối lượng.\n\n"
            "_Lưu ý: RSI không nên dùng một mình để ra quyết định mua bán._"
        )
    if "macd" in msg:
        return (
            "*MACD* dùng để đánh giá xu hướng và động lượng giá.\n"
            "- MACD cắt lên Signal: tín hiệu tích cực hơn.\n"
            "- MACD cắt xuống Signal: tín hiệu yếu đi.\n"
            "- Histogram mở rộng: động lượng đang mạnh lên.\n\n"
            "_Nên kết hợp MACD với xu hướng MA, RSI và thanh khoản._"
        )
    if "bollinger" in msg or "bb" in msg:
        return (
            "*Bollinger Bands* gồm dải trên, dải giữa và dải dưới quanh đường MA.\n"
            "- Giá sát dải trên: lực tăng mạnh nhưng có thể nóng.\n"
            "- Giá sát dải dưới: áp lực bán mạnh hoặc vùng quá bán ngắn hạn.\n"
            "- Dải bó hẹp: thị trường có thể sắp biến động mạnh.\n\n"
            "_Không nên xem chạm dải dưới là mua ngay nếu xu hướng chính vẫn giảm._"
        )
    if "thị trường" in msg or "vn-index" in msg or "vnindex" in msg:
        return (
            "Hiện Gemini đang tạm không khả dụng, nhưng bạn vẫn có thể xem phần "
            "*AI Gemini nhận xét thị trường* trên Dashboard vì hệ thống có fallback từ dữ liệu chỉ số. "
            "Nếu VN-Index giảm mạnh, ưu tiên quản trị rủi ro, giảm mua đuổi và theo dõi thanh khoản. "
            "_Đây là thông tin tham khảo, không phải khuyến nghị đầu tư._"
        )
    return (
        "Gemini đang tạm quá tải hoặc hết quota, nên StockBot đang chạy ở chế độ offline. "
        "Bạn vẫn có thể hỏi theo dạng mã cổ phiếu như `VNM`, `HPG`, `FPT` để hệ thống phân tích bằng dữ liệu kỹ thuật local. "
        "Với câu hỏi kiến thức, hãy hỏi cụ thể như `RSI là gì`, `MACD là gì`, hoặc `Bollinger Bands là gì`."
    )


async def chat_with_ai(message: str, history: List[Dict] = None) -> str:
    """Chatbot hỏi đáp tự do về chứng khoán Việt Nam."""
    has_symbol_hint = bool(_extract_symbol(message))
    symbol = _extract_symbol(message)

    # Answer deterministic/basic prompts locally. This avoids wasting Gemini quota
    # and prevents generic terms like RSI/MACD from being answered as stock symbols.
    msg_lower = message.lower()
    if not symbol and (
        msg_lower.strip() in {"hi", "hello", "hey", "chào", "xin chào", "chao", "alo"}
        or "rsi" in msg_lower
        or "macd" in msg_lower
        or "bollinger" in msg_lower
        or re.search(r"\bbb\b", msg_lower)
    ):
        return _build_general_chat_fallback(message)

    if not symbol and ("thị trường" in msg_lower or "thi truong" in msg_lower or "vn-index" in msg_lower or "vnindex" in msg_lower):
        return await _build_market_chat_fallback()

    if has_symbol_hint:
        system_context = """Bạn là StockBot – chuyên gia phân tích chứng khoán Việt Nam, 10 năm kinh nghiệm.
Khi phân tích MỘT MÃ cụ thể, hãy viết phân tích CHI TIẾT, đầy đủ, có cấu trúc rõ ràng theo các phần sau (dùng emoji + heading):

📊 **Tổng quan**: Giá hiện tại, biến động ngắn/trung hạn (5 phiên, 60 phiên).
📈 **Xu hướng & Chart**: Đánh giá xu hướng từ MA20/50/200, vị trí giá so với các MA, ý nghĩa giao cắt.
🎯 **Hỗ trợ – Kháng cự**: Ước tính từ MA, Bollinger Bands, đỉnh/đáy 20 phiên.
⚡ **Động lượng**: Phân tích RSI (quá mua/bán), MACD (cross, histogram), khối lượng giao dịch.
⚠️ **Rủi ro chính**: Liệt kê 2-3 rủi ro cụ thể cần lưu ý.
💡 **Gợi ý hành động**: Khuyến nghị cụ thể (vùng giá nên mua/bán/chờ, cắt lỗ).

Văn phong tiếng Việt tự nhiên, dùng số liệu THỰC TẾ từ dữ liệu bên dưới, KHÔNG bịa số. Mỗi phần 2-3 câu. KHÔNG đảm bảo lợi nhuận."""
    else:
        system_context = """Bạn là StockBot – trợ lý phân tích chứng khoán Việt Nam thân thiện.
Trả lời bằng tiếng Việt ngắn gọn (3-5 câu), giải thích kiến thức rõ ràng dễ hiểu.
Nhắc nhở: đầu tư có rủi ro, không đảm bảo lợi nhuận."""

    snapshot = ""
    if symbol:
        snapshot = await _fetch_analysis_snapshot(symbol)

    conversation_text = ""
    if history:
        for h in history[-6:]:
            role = "Người dùng" if h.get("role") == "user" else "StockBot"
            conversation_text += f"{role}: {h.get('content', '')}\n"

    prompt = f"""{system_context}
{snapshot}
{conversation_text}Người dùng: {message}
StockBot:"""

    try:
        return await _generate(prompt)
    except Exception as e:
        logger.error(f"Chat AI error: {e}")
        if symbol:
            return await _build_symbol_chat_fallback(symbol)
        return _build_general_chat_fallback(message)
