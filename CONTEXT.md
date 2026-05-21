# 📈 StockVN – Context & Documentation

## Tổng Quan Dự Án

**StockVN** là ứng dụng phân tích cổ phiếu Việt Nam thời gian thực, tích hợp:
- 🌐 **Web App (PWA)** – Dashboard đẹp, biểu đồ nến, Scanner quét tín hiệu, UI chuẩn mobile
- 🤖 **Telegram Bot** – Nhận cảnh báo tín hiệu mua bán, quét thị trường qua chat
- 🧠 **Trợ lý AI** – Nhận xét thị trường, phân tích kỹ thuật cổ phiếu

---

## 📁 Cấu Trúc Thư Mục

```
D:\stock-analyzer\
├── backend\
│   ├── main.py                 # FastAPI server chính
│   ├── data_fetcher.py         # Lấy dữ liệu (Wifeed API & VNDirect API)
│   ├── market_scanner.py       # Background worker quét 1800+ mã mỗi 15 phút
│   ├── technical_analysis.py   # Tính toán RSI, MACD, BB, Entry/Stoploss, Breakout
│   ├── ai_analyzer.py          # Tích hợp AI (Gemini/NIM fallback)
│   ├── telegram_bot.py         # Telegram bot handlers
│   ├── database.py             # SQLite connection
│   ├── portfolio_manager.py    # Quản lý giao dịch/holdings
│   ├── watchlist_manager.py    # Quản lý watchlist
│   ├── alert_manager.py        # Cảnh báo rủi ro/đột biến
│   ├── requirements.txt        # Python dependencies
│   ├── .env                    # API keys (KHÔNG commit)
│   └── stockvn.db              # SQLite database (tự tạo)
│
├── frontend\
│   ├── index.html              # Dashboard
│   ├── stock.html              # Phân tích kỹ thuật chi tiết
│   ├── scanner.html            # Bộ lọc toàn thị trường
│   ├── watchlist.html          # Danh sách theo dõi
│   ├── portfolio.html          # Quản lý danh mục
│   ├── manifest.json           # Cấu hình PWA
│   ├── sw.js                   # Service Worker cho PWA
│   └── css/style.css           # UI/UX Dark theme
│
├── README.md                   # Hướng dẫn cài đặt và deploy
├── CONTEXT.md                  # File này
├── .gitignore                  
└── run.bat                     # Script khởi chạy Windows
```

## 🚀 Tính năng nổi bật gần đây (V2)
1. **Wifeed & VNDirect API**: Thay thế Yahoo Finance, dữ liệu chính xác 100% cho thị trường VN, tốc độ realtime.
2. **Full-Market Scanner**: Quét 1800+ mã cổ phiếu ngầm mỗi 15 phút, lưu vào RAM Cache. Lọc thanh khoản > 10.000 cổ/ngày.
3. **Advanced Technical Analysis**: Tự động phát hiện dòng tiền Tích lũy, Đột biến, Phân phối, và cung cấp điểm Vào (Entry) / Cắt lỗ (Stoploss).
4. **Mobile Optimization & PWA**: Cài đặt như app Native, vuốt mượt mà, không bị lag bảng grid.

## 🔑 Biến Môi Trường (.env)

Yêu cầu các khóa: `GEMINI_API_KEY`, `TELEGRAM_TOKEN`, `NVIDIA_API_KEY` (tuỳ chọn). Mặc định chạy `http://127.0.0.1:8000`.
