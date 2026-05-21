import numpy as np
from typing import List, Dict, Any

# ─── Indicators ───────────────────────────────────────────────────────────────

def ema(prices: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1)
    result = np.zeros(len(prices))
    result[0] = prices[0]
    for i in range(1, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result

def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_macd(closes: np.ndarray, fast=12, slow=26, signal_period=9) -> Dict:
    if len(closes) < slow + signal_period:
        return {"macd": 0, "signal": 0, "histogram": 0, "cross": "none"}
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow
    # signal_line is computed on the full macd_line (EMA smooths from index 0)
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    # Detect cross in last 2 bars
    cross = "none"
    if len(histogram) >= 2:
        if histogram[-2] < 0 and histogram[-1] >= 0:
            cross = "bullish"
        elif histogram[-2] > 0 and histogram[-1] <= 0:
            cross = "bearish"
    return {
        "macd": round(float(macd_line[-1]), 4),
        "signal": round(float(signal_line[-1]), 4),
        "histogram": round(float(histogram[-1]), 4),
        "cross": cross,
    }

def calculate_bollinger(closes: np.ndarray, period=20, std_mult=2.0) -> Dict:
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": "middle"}
    window = closes[-period:]
    middle = float(np.mean(window))
    std = float(np.std(window))
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    current = float(closes[-1])
    if current > upper:
        position = "above_upper"
    elif current < lower:
        position = "below_lower"
    elif current > middle:
        position = "upper_half"
    else:
        position = "lower_half"
    return {
        "upper": round(upper, 0),
        "middle": round(middle, 0),
        "lower": round(lower, 0),
        "position": position,
    }

def calculate_ma(closes: np.ndarray, period: int) -> float | None:
    if len(closes) >= period:
        return round(float(np.mean(closes[-period:])), 0)
    return None

def calculate_volume_signal(volumes: np.ndarray, closes: np.ndarray) -> Dict:
    if len(volumes) < 20:
        return {"ratio": 1.0, "signal": "normal"}
    avg_vol = float(np.mean(volumes[-20:]))
    latest_vol = float(volumes[-1])
    ratio = latest_vol / avg_vol if avg_vol > 0 else 1.0
    price_up = closes[-1] > closes[-2] if len(closes) >= 2 else False
    if ratio > 1.5 and price_up:
        signal = "surge_up"
    elif ratio > 1.5 and not price_up:
        signal = "surge_down"
    elif ratio < 0.5:
        signal = "low"
    else:
        signal = "normal"
    return {"ratio": round(ratio, 2), "signal": signal}

# ─── Main Signal Engine ───────────────────────────────────────────────────────


def calculate_support_resistance(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> Dict:
    if len(closes) < 20:
        return {"support": 0, "resistance": 0}
    
    recent_lows = lows[-20:]
    recent_highs = highs[-20:]
    
    # Tìm mức hỗ trợ/kháng cự cục bộ (giá trị min/max trong 20 phiên gần nhất)
    support = float(np.min(recent_lows))
    resistance = float(np.max(recent_highs))
    
    return {"support": round(support, 0), "resistance": round(resistance, 0)}

def calculate_entry_stoploss(current_price: float, bb: Dict, ma20: float, support: float, resistance: float) -> Dict:
    # Điểm cắt lỗ (Stop-loss): Dưới mức hỗ trợ hoặc dải BB dưới
    stop_loss_candidates = [val for val in [support, bb.get("lower"), ma20] if val and val < current_price]
    if stop_loss_candidates:
        stop_loss = max(stop_loss_candidates) * 0.98 # -2% buffer
    else:
        stop_loss = current_price * 0.95 # Mặc định -5%

    # Điểm vào (Entry): Vùng giá an toàn gần mức hỗ trợ hoặc MA20
    entry_candidates = [val for val in [ma20, bb.get("middle"), support] if val and val < current_price]
    if entry_candidates:
        entry = max(entry_candidates)
    else:
        entry = current_price
        
    # Điểm chốt lời (Target): Đỉnh cũ hoặc R/R = 1:1.5
    target_rr = entry + (entry - stop_loss) * 1.5
    target = max(resistance, target_rr) if resistance > current_price else target_rr
    
    risk_pct = (entry - stop_loss) / entry * 100 if entry else 0
    
    return {
        "entry": round(entry, 0),
        "target": round(target, 0),
        "stop_loss": round(stop_loss, 0),
        "risk_pct": round(risk_pct, 2)
    }

def detect_advanced_signals(data: List[Dict], rsi: float, bb: Dict, vol_signal: Dict, ma20: float) -> List[Dict]:
    """Phân tích các mẫu hình đặc biệt: Tích lũy, Phân phối, Đột biến"""
    signals = []
    if len(data) < 5:
        return signals
        
    closes = np.array([d["close"] for d in data[-5:]])
    volumes = np.array([d["volume"] for d in data[-5:]])
    
    current_price = closes[-1]
    
    # 1. Tích lũy (Accumulation): Giá đi ngang, khối lượng cạn kiệt hoặc tăng dần nhẹ, RSI thấp
    price_range = (np.max(closes) - np.min(closes)) / np.min(closes) * 100
    if price_range < 3.0 and rsi < 45 and bb["position"] in ["lower_half", "below_lower"]:
        signals.append({
            "type": "accumulation",
            "name": "Tích lũy",
            "emoji": "🟢",
            "note": "Giá đi ngang vùng đáy, rủi ro thấp, khả năng bật tăng cao."
        })
        
    # 2. Phân phối (Distribution): Giá không tăng nhưng khối lượng lớn, hoặc nến đỏ vol to vùng đỉnh
    if rsi > 60 and vol_signal["signal"] == "surge_down":
        signals.append({
            "type": "distribution",
            "name": "Phân phối",
            "emoji": "🔴",
            "note": "Khối lượng bán mạnh vùng đỉnh, rủi ro đảo chiều giảm."
        })
        
    # 3. Đột biến (Breakout): Giá vượt kháng cự kèm khối lượng lớn
    if bb["position"] == "above_upper" and vol_signal["ratio"] > 2.0 and closes[-1] > closes[-2]:
        signals.append({
            "type": "breakout",
            "name": "Đột biến tăng",
            "emoji": "💥",
            "note": "Giá phá vỡ dải Bollinger trên kèm khối lượng bùng nổ. Sóng tăng mới."
        })
        
    # 4. Phá đáy (Breakdown): Giá rớt hỗ trợ kèm khối lượng lớn
    if bb["position"] == "below_lower" and vol_signal["ratio"] > 2.0 and closes[-1] < closes[-2]:
        signals.append({
            "type": "breakdown",
            "name": "Khủng hoảng (Phá đáy)",
            "emoji": "💀",
            "note": "Giá thủng đáy kèm khối lượng lớn. Cực kỳ rủi ro, cần cắt lỗ ngay."
        })
        
    return signals

def analyze_stock(data: List[Dict]) -> Dict[str, Any]:
    """Phân tích kỹ thuật và trả về tín hiệu MUA/BÁN/CÂN NHẮC"""
    if len(data) < 30:
        return {"error": "Không đủ dữ liệu để phân tích"}

    closes = np.array([d["close"] for d in data], dtype=float)
    highs = np.array([d["high"] for d in data], dtype=float)
    lows = np.array([d["low"] for d in data], dtype=float)
    volumes = np.array([d["volume"] for d in data], dtype=float)

    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    bb = calculate_bollinger(closes)
    ma20 = calculate_ma(closes, 20)
    ma50 = calculate_ma(closes, 50)
    ma200 = calculate_ma(closes, 200)
    vol_signal = calculate_volume_signal(volumes, closes)

    current_price = float(closes[-1])
    prev_price = float(closes[-2])
    change_pct = (current_price - prev_price) / prev_price * 100 if prev_price else 0
    
    sr = calculate_support_resistance(closes, highs, lows)
    entry_sl = calculate_entry_stoploss(current_price, bb, ma20, sr["support"], sr["resistance"])
    advanced_signals = detect_advanced_signals(data, rsi, bb, vol_signal, ma20)

    score = 0
    signals = []

    # RSI
    if rsi < 30:
        score += 2
        signals.append({"indicator": "RSI", "value": rsi, "signal": "buy", "note": f"RSI {rsi} – Quá bán mạnh ✅"})
    elif rsi < 40:
        score += 1
        signals.append({"indicator": "RSI", "value": rsi, "signal": "buy_weak", "note": f"RSI {rsi} – Vùng tích lũy 🟡"})
    elif rsi > 70:
        score -= 2
        signals.append({"indicator": "RSI", "value": rsi, "signal": "sell", "note": f"RSI {rsi} – Quá mua mạnh ❌"})
    elif rsi > 60:
        score -= 1
        signals.append({"indicator": "RSI", "value": rsi, "signal": "sell_weak", "note": f"RSI {rsi} – Vùng phân phối 🟡"})
    else:
        signals.append({"indicator": "RSI", "value": rsi, "signal": "neutral", "note": f"RSI {rsi} – Trung tính ➖"})

    # MACD
    if macd["cross"] == "bullish":
        score += 2
        signals.append({"indicator": "MACD", "value": macd["histogram"], "signal": "buy", "note": "MACD vừa cắt lên Signal – Golden Cross ✅"})
    elif macd["histogram"] > 0 and macd["macd"] > 0:
        score += 1
        signals.append({"indicator": "MACD", "value": macd["histogram"], "signal": "buy_weak", "note": "MACD dương – Xu hướng tăng 🟡"})
    elif macd["cross"] == "bearish":
        score -= 2
        signals.append({"indicator": "MACD", "value": macd["histogram"], "signal": "sell", "note": "MACD vừa cắt xuống Signal – Death Cross ❌"})
    elif macd["histogram"] < 0 and macd["macd"] < 0:
        score -= 1
        signals.append({"indicator": "MACD", "value": macd["histogram"], "signal": "sell_weak", "note": "MACD âm – Xu hướng giảm 🟡"})
    else:
        signals.append({"indicator": "MACD", "value": macd["histogram"], "signal": "neutral", "note": "MACD trung tính ➖"})

    # Bollinger Bands
    if bb["position"] == "below_lower":
        score += 1
        signals.append({"indicator": "BB", "signal": "buy", "note": "Giá dưới Bollinger Band dưới – Quá bán ✅"})
    elif bb["position"] == "above_upper":
        score -= 1
        signals.append({"indicator": "BB", "signal": "sell", "note": "Giá trên Bollinger Band trên – Quá mua ❌"})
    else:
        signals.append({"indicator": "BB", "signal": "neutral", "note": f"Giá trong Bollinger Band ({bb['position']}) ➖"})

    # MA20/MA50 Cross
    if ma20 and ma50:
        if ma20 > ma50:
            score += 1
            signals.append({"indicator": "MA20/50", "signal": "buy", "note": f"MA20 ({ma20:,.0f}) > MA50 ({ma50:,.0f}) – Xu hướng tăng ✅"})
        else:
            score -= 1
            signals.append({"indicator": "MA20/50", "signal": "sell", "note": f"MA20 ({ma20:,.0f}) < MA50 ({ma50:,.0f}) – Xu hướng giảm ❌"})

    # Price vs MA20
    if ma20:
        if current_price > ma20:
            score += 1
            signals.append({"indicator": "Price/MA20", "signal": "buy", "note": f"Giá trên MA20 – Tích cực ✅"})
        else:
            score -= 1
            signals.append({"indicator": "Price/MA20", "signal": "sell", "note": f"Giá dưới MA20 – Tiêu cực ❌"})

    # Volume
    if vol_signal["signal"] == "surge_up":
        score += 1
        signals.append({"indicator": "Volume", "value": vol_signal["ratio"], "signal": "buy", "note": f"Khối lượng tăng {vol_signal['ratio']:.1f}x kèm giá tăng – Xác nhận ✅"})
    elif vol_signal["signal"] == "surge_down":
        score -= 1
        signals.append({"indicator": "Volume", "value": vol_signal["ratio"], "signal": "sell", "note": f"Khối lượng tăng {vol_signal['ratio']:.1f}x kèm giá giảm – Cảnh báo ❌"})

    # Determine recommendation
    if score >= 4:
        recommendation = "BUY"
        recommendation_vn = "NÊN MUA"
        color = "green"
        emoji = "🟢"
    elif score <= -4:
        recommendation = "SELL"
        recommendation_vn = "KHÔNG NÊN MUA"
        color = "red"
        emoji = "🔴"
    else:
        recommendation = "HOLD"
        recommendation_vn = "CÂN NHẮC"
        color = "yellow"
        emoji = "🟡"

    return {
        "recommendation": recommendation,
        "recommendation_vn": recommendation_vn,
        "emoji": emoji,
        "color": color,
        "score": score,
        "max_score": 8,
        "signals": signals,
        "indicators": {
            "rsi": rsi,
            "macd": macd,
            "bollinger": bb,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "volume": vol_signal,
        },
        "price_info": {
            "current": current_price,
            "change_pct": round(change_pct, 2),
            "support": sr["support"],
            "resistance": sr["resistance"],
        },
        "trade_plan": entry_sl,
        "advanced_signals": advanced_signals,
        "chart_data": {
            "closes": closes.tolist()[-60:],
            "highs": highs.tolist()[-60:],
            "lows": lows.tolist()[-60:],
            "volumes": volumes.tolist()[-60:],
            "dates": [d["date"] for d in data[-60:]],
        },
    }
