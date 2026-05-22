"""
market_scanner.py – Engine quét toàn thị trường nền (Background Scanner)
Tự động quét toàn bộ ~1800 mã mỗi 15 phút, lọc mã có thanh khoản,
chạy phân tích kỹ thuật và lưu kết quả (Top Signals, Bảng giá) vào RAM.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Any

from data_fetcher import get_all_symbols, get_historical_data
from technical_analysis import analyze_stock

logger = logging.getLogger(__name__)

# Cache lưu trữ kết quả quét toàn thị trường
MARKET_SCAN_CACHE: Dict[str, Any] = {
    "last_updated": None,
    "total_scanned": 0,
    "active_symbols": 0,
    "summary": {"BUY": 0, "SELL": 0, "HOLD": 0},
    "signals": [],  # Chứa các mã có tín hiệu đặc biệt (tích lũy, đột biến...)
    "all_results": [], # Danh sách đầy đủ đã phân tích
    "is_scanning": False
}

async def scan_single_stock(symbol: str) -> Dict[str, Any] | None:
    """Quét 1 mã cổ phiếu."""
    try:
        data = await get_historical_data(symbol, days=60)
        if len(data) < 30:
            return None
            
        # Lọc thanh khoản: Trung bình volume 5 phiên gần nhất phải > 10,000
        recent_vols = [d["volume"] for d in data[-5:]]
        avg_vol = sum(recent_vols) / len(recent_vols)
        if avg_vol < 10000:
            return None
            
        analysis = analyze_stock(data)
        
        # Chỉ lấy các trường cần thiết để tiết kiệm RAM
        ind = analysis.get("indicators", {})
        return {
            "symbol": symbol,
            "price": analysis["price_info"]["current"],
            "change_pct": analysis["price_info"]["change_pct"],
            "recommendation": analysis["recommendation"],
            "recommendation_vn": analysis["recommendation_vn"],
            "score": analysis["score"],
            "emoji": analysis["emoji"],
            "rsi": ind.get("rsi", 50),
            "macd_cross": ind.get("macd", {}).get("cross", "none"),
            "volume_ratio": ind.get("volume", {}).get("ratio", 1),
            "trade_plan": analysis.get("trade_plan", {}),
            "advanced_signals": analysis.get("advanced_signals", []),
            "avg_vol": avg_vol
        }
    except Exception as e:
        # Không log chi tiết để tránh rác console
        return None

async def run_full_market_scan():
    """Hàm chạy quét toàn bộ thị trường."""
    if MARKET_SCAN_CACHE["is_scanning"]:
        logger.info("Market scan is already running. Skipping.")
        return
        
    MARKET_SCAN_CACHE["is_scanning"] = True
    start_time = time.time()
    
    try:
        logger.info("Bắt đầu quét toàn thị trường...")
        symbols = await get_all_symbols()
        
        # Chia batch để không bị sập kết nối và nghẽn CPU (Render Free)
        batch_size = 50
        all_results = []
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [scan_single_stock(sym) for sym in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in batch_results:
                if isinstance(res, dict) and res:
                    all_results.append(res)
            
            # Delay nhẹ giữa các batch để tránh quá tải CPU/API và nhường event loop
            await asyncio.sleep(1.0)
            
        # Tổng hợp dữ liệu
        summary = {"BUY": 0, "SELL": 0, "HOLD": 0}
        advanced_signals = []
        
        for r in all_results:
            rec = r["recommendation"]
            if rec in summary:
                summary[rec] += 1
                
            # Trích xuất các mã có advanced_signals
            if r["advanced_signals"]:
                for sig in r["advanced_signals"]:
                    # Tạo copy để flatten
                    sig_item = r.copy()
                    del sig_item["advanced_signals"]
                    sig_item["signal_type"] = sig["type"]
                    sig_item["signal_name"] = sig["name"]
                    sig_item["signal_emoji"] = sig["emoji"]
                    sig_item["signal_note"] = sig["note"]
                    advanced_signals.append(sig_item)
                    
        # Sắp xếp advanced signals theo sức mạnh (score, volume)
        advanced_signals.sort(key=lambda x: (x["score"], x["volume_ratio"]), reverse=True)
        
        # Lưu vào cache
        MARKET_SCAN_CACHE["all_results"] = sorted(all_results, key=lambda x: x["score"], reverse=True)
        MARKET_SCAN_CACHE["signals"] = advanced_signals
        MARKET_SCAN_CACHE["summary"] = summary
        MARKET_SCAN_CACHE["total_scanned"] = len(symbols)
        MARKET_SCAN_CACHE["active_symbols"] = len(all_results)
        MARKET_SCAN_CACHE["last_updated"] = datetime.now().isoformat()
        
        elapsed = time.time() - start_time
        logger.info(f"Hoàn thành quét toàn thị trường! {len(all_results)}/{len(symbols)} mã active. Mất {elapsed:.1f}s")
        
    except Exception as e:
        logger.error(f"Lỗi khi quét toàn thị trường: {e}")
    finally:
        MARKET_SCAN_CACHE["is_scanning"] = False

def get_market_scan_results() -> Dict[str, Any]:
    """Lấy kết quả từ Cache."""
    return {
        "last_updated": MARKET_SCAN_CACHE["last_updated"],
        "total_scanned": MARKET_SCAN_CACHE["total_scanned"],
        "active_symbols": MARKET_SCAN_CACHE["active_symbols"],
        "summary": MARKET_SCAN_CACHE["summary"],
        "signals": MARKET_SCAN_CACHE["signals"],
        "is_scanning": MARKET_SCAN_CACHE["is_scanning"],
        # Cắt bớt all_results để trả về API cho nhẹ (top 100)
        "top_buy": MARKET_SCAN_CACHE["all_results"][:50] if MARKET_SCAN_CACHE["all_results"] else [],
        "top_sell": MARKET_SCAN_CACHE["all_results"][-50:] if MARKET_SCAN_CACHE["all_results"] else [],
    }
