# 📈 StockVN – Context & Documentation

## Tổng Quan Dự Án

**StockVN** là ứng dụng phân tích cổ phiếu Việt Nam thời gian thực, tích hợp:
- 🌐 **Web App** – Dashboard đẹp, biểu đồ nến, chỉ báo kỹ thuật, chatbot AI
- 🤖 **Telegram Bot** – Nhận cảnh báo tín hiệu, phân tích nhanh qua chat
- 🧠 **AI Gemini + NVIDIA NIM fallback** – Bình luận thị trường, phân tích cổ phiếu, chatbot hỏi đáp

---

## 📁 Cấu Trúc Thư Mục

```
D:\stock-analyzer\
├── backend\
│   ├── main.py                 # FastAPI server chính
│   ├── data_fetcher.py         # Lấy dữ liệu giá cổ phiếu (yfinance + DNSE)
│   ├── technical_analysis.py   # Tính toán RSI, MACD, BB, MA
│   ├── ai_analyzer.py          # Gemini AI + NVIDIA NIM fallback + local fallback
│   ├── telegram_bot.py         # Telegram bot handlers + alert system
│   ├── database.py             # SQLite connection & schema management
│   ├── watchlist_manager.py    # Quản lý watchlist (SQLite-backed)
│   ├── portfolio_manager.py    # Quản lý giao dịch và holdings
│   ├── alert_manager.py        # Alert rule nâng cao
│   ├── vn_symbols.py           # Danh sách ~1600 mã CK Việt Nam
│   ├── requirements.txt        # Python dependencies
│   ├── .env                    # API keys (KHÔNG commit lên git)
│   ├── .env.example            # Template biến môi trường
│   └── stockvn.db              # SQLite database (tự tạo khi chạy)
│
├── frontend\
│   ├── index.html              # Dashboard chính
│   ├── stock.html              # Trang chi tiết cổ phiếu
│   ├── watchlist.html          # Trang danh mục theo dõi
│   ├── portfolio.html          # Trang quản lý danh mục đầu tư
│   ├── scanner.html            # Trang lọc cổ phiếu theo chỉ báo
│   ├── chatbot.html            # Widget chatbot (dùng chung)
│   ├── js\
│   │   ├── api.js              # Helper gọi API + loading/error state
│   │   └── storage.js          # Client ID, format, escape helpers
│   └── css\
│       └── style.css           # Toàn bộ CSS (dark theme)
│
├── tests\
│   └── test_watchlist_manager.py  # Unit tests cho watchlist
│
├── CONTEXT.md                  # File này
├── IMPLEMENTATION_PLAN.md      # Kế hoạch triển khai theo phase
├── .gitignore                  # Loại trừ cache, DB, logs, .env
└── run.bat                     # Script khởi động nhanh
```

---

## 🚀 Cách Chạy

```bat
# Double-click:
D:\stock-analyzer\run.bat

# Hoặc thủ công:
cd D:\stock-analyzer\backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

- **Dashboard**: http://localhost:8000/
- **API Docs**: http://localhost:8000/docs

> [!NOTE]
> Dashboard được serve trực tiếp từ root `/`, không phải `/static/index.html`.
> Frontend gọi API qua prefix `/api` (relative URL), không hardcode `localhost`.

### Chạy Test

```bat
cd D:\stock-analyzer
python -m pytest -q
```

---

## 🔑 Biến Môi Trường (.env)

| Key | Dịch vụ | Ghi chú |
|-----|---------|---------|
| `GEMINI_API_KEY` | Google Gemini AI | Free tier tại aistudio.google.com |
| `NVIDIA_API_KEY` | NVIDIA NIM AI fallback | Lấy tại build.nvidia.com; dùng khi Gemini lỗi/quota |
| `NVIDIA_MODEL` | NVIDIA NIM model | Mặc định: `minimaxai/minimax-m2.7` |
| `NVIDIA_BASE_URL` | NVIDIA NIM API base URL | Mặc định: `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_TIMEOUT_SECONDS` | Timeout gọi NVIDIA | Mặc định: `45` |
| `TELEGRAM_TOKEN` | Telegram Bot | Lấy từ @BotFather |
| `CORS_ALLOW_ORIGINS` | CORS config | Mặc định: `http://localhost:8000,http://127.0.0.1:8000` |
| `YFINANCE_CACHE_DIR` | yfinance timezone cache | Mặc định: `backend/.yfinance_cache` |
| `SQLITE_PATH` | SQLite database path | Mặc định: `backend/stockvn.db` |

> [!CAUTION]
> Không chia sẻ file `.env` hay commit lên GitHub public.
> Copy `.env.example` thành `.env` và điền giá trị thật.

---

## 📡 Nguồn Dữ Liệu

| Nguồn | Dùng cho | Ghi chú |
|-------|----------|---------|
| **yfinance (Yahoo Finance)** | Lịch sử daily OHLCV | 24/7, miễn phí, suffix `.VN` |
| **DNSE Entrade API** | Nến intraday 1 phút + Indices | `services.entrade.com.vn/chart-api/v2/ohlcs` |
| **Google Gemini** | Phân tích AI, chatbot | Multi-model fallback: 2.5-flash → 2.0-flash → 2.0-flash-lite |
| **NVIDIA NIM** | AI fallback | OpenAI-compatible endpoint, mặc định model `minimaxai/minimax-m2.7` |

### Cơ chế hoạt động
- **Ngoài giờ giao dịch**: Yahoo Finance – giá đóng cửa ngày gần nhất (24/7)
- **Trong giờ giao dịch** (T2–T6, 9:00–15:00): DNSE – nến 1 phút real-time
- **Indices** (VNINDEX, HNX, UPCOM): DNSE entrade index API

---

## 🌐 API Backend Endpoints

### Stock
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/stock/{symbol}` | OHLCV + phân tích kỹ thuật đầy đủ |
| GET | `/api/stock/{symbol}/ai` | Phân tích AI Gemini |
| GET | `/api/stock/{symbol}/fundamentals` | Chỉ số cơ bản P/E, P/B, EPS… |
| GET | `/api/stock/{symbol}/intraday` | Nến intraday từ DNSE |
| GET | `/api/stock/{symbol}?days=300` | Tùy chỉnh số ngày lịch sử |

### Market
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/market/overview` | VNINDEX/HNX/UPCOM + AI commentary |
| GET | `/api/market/top-movers` | Top tăng/giảm mạnh |

### Watchlist
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/watchlist/{chat_id}` | Lấy danh mục |
| POST | `/api/watchlist/{chat_id}/{symbol}` | Thêm mã |
| DELETE | `/api/watchlist/{chat_id}/{symbol}` | Xóa mã |
| GET | `/api/watchlist/{chat_id}/analyze` | Phân tích toàn danh mục |

### AI Chat
| Method | Endpoint | Body | Mô tả |
|--------|----------|------|-------|
| POST | `/api/chat` | `{message, history[]}` | Chatbot hỏi đáp |

### Portfolio
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/portfolio/{user_id}` | Tổng hợp holdings + lãi/lỗ |
| GET | `/api/portfolio/{user_id}/trades` | Lịch sử giao dịch |
| POST | `/api/portfolio/{user_id}/trades` | Thêm giao dịch |
| PUT | `/api/portfolio/{user_id}/trades/{trade_id}` | Sửa giao dịch |
| DELETE | `/api/portfolio/{user_id}/trades/{trade_id}` | Xóa giao dịch |

### Scanner & Alerts
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/scanner` | Lọc cổ phiếu theo chỉ báo kỹ thuật |
| GET | `/api/alerts/{user_id}` | Danh sách alert rule |
| POST | `/api/alerts/{user_id}` | Tạo alert rule |
| PUT | `/api/alerts/{user_id}/{rule_id}` | Sửa alert rule |
| DELETE | `/api/alerts/{user_id}/{rule_id}` | Xóa alert rule |

### System
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/symbols` | Danh sách mã CK cho autocomplete |
| GET | `/api/health` | Health check (app + database) |

---

## 👤 Hệ Thống Client ID

- **Telegram**: Dùng numeric chat ID (`str(update.effective_chat.id)`)
- **Web**: Dùng client ID dạng `web_<32-hex>` lưu trong `localStorage`
- Cả hai dùng chung storage (SQLite) qua cùng `WatchlistManager`

---

## 📊 Hệ Thống Chỉ Báo Kỹ Thuật

### Chấm điểm (score: -8 đến +8)

| Chỉ báo | Tín hiệu MUA (+) | Tín hiệu BÁN (-) |
|---------|-----------------|-----------------|
| RSI(14) | <30 (+2), 30-40 (+1) | >70 (-2), 60-70 (-1) |
| MACD | Cross bullish (+2), histogram>0 (+1) | Cross bearish (-2), histogram<0 (-1) |
| Bollinger Bands | Giá < Lower (+1) | Giá > Upper (-1) |
| MA20/MA50 | MA20>MA50 Golden Cross (+1) | MA20<MA50 Death Cross (-1) |
| Giá vs MA20 | Giá > MA20 (+1) | Giá < MA20 (-1) |
| Volume | KL>1.5x TB + giá tăng (+1) | KL>1.5x TB + giá giảm (-1) |

### Kết quả tín hiệu
- **Score ≥ +4** → 🟢 **NÊN MUA**
- **Score ≤ -4** → 🔴 **KHÔNG NÊN MUA**
- **-3 đến +3** → 🟡 **CÂN NHẮC / THEO DÕI**

---

## 🤖 Telegram Bot Commands

| Lệnh | Ví dụ | Mô tả |
|------|-------|-------|
| `/start` | | Bắt đầu + hướng dẫn |
| `/analyze VNM` | | Phân tích đầy đủ + AI |
| `/quick VNM` | | Tín hiệu nhanh |
| `/watch VNM` | | Thêm vào watchlist |
| `/unwatch VNM` | | Xóa khỏi watchlist |
| `/watchlist` | | Xem toàn bộ watchlist |
| `/market` | | Tổng quan thị trường |
| `/top` | | Top tăng/giảm |

**Alert tự động**: Scan mỗi 5 phút, alert khi `|score| ≥ 5`

---

## 🎨 Design System

**Palette (dark theme, GitHub-inspired):**
```
--bg: #0f1117       Nền chính
--card: #1c2333     Card
--txt: #cdd9e5      Text chính
--green: #3fb950    Tín hiệu MUA
--red: #f85149      Tín hiệu BÁN
--yellow: #d29922   CÂN NHẮC
--blue: #58a6ff     Accent / link
--indigo: #818cf8   Chatbot
```

**Frontend libs (CDN):**
- Lucide Icons – SVG icons
- TradingView Lightweight Charts – candlestick chart
- Inter + JetBrains Mono – Google Fonts

---

## 🔄 Luồng Xử Lý

```
Dashboard load
  → /api/market/overview    DNSE indices + Gemini commentary
  → /api/stock/{sym} x15   yfinance daily + technical analysis
  → Render cards với signal badges

Stock detail
  → /api/stock/{sym}?days=300   yfinance historical
  → Vẽ chart (Lightweight Charts): candle + MA + BB + RSI + MACD
  → /api/stock/{sym}/ai         Gemini AI phân tích

Chatbot
  → POST /api/chat {message, history}
  → Gemini context-aware về VN stocks
  → Nếu Gemini lỗi/quota: NVIDIA NIM
  → Nếu cả hai provider lỗi: fallback local/rule-based

Telegram Alert (5 phút/lần)
  → Scan tất cả watchlist symbols
  → Tính score → alert nếu |score| ≥ 5
```

---

## 💾 Storage

**SQLite Database** (`backend/stockvn.db`):
- `watchlists(user_id, symbol, created_at)` – Danh mục theo dõi
- `trades(...)` – Lịch sử giao dịch portfolio
- `alert_rules(...)` – Rule cảnh báo nâng cao
- `app_metadata(key, value)` – Metadata hệ thống (migration status, etc.)

Khi app khởi động lần đầu, nếu `watchlist_data.json` tồn tại, dữ liệu sẽ được migrate tự động sang SQLite. File JSON cũ không bị xóa (có thể rename thủ công sau).

---

## 🐛 Known Issues & Lịch Sử Fix

| Issue | Trạng thái |
|-------|-----------| 
| TCBS API 404 (đổi endpoint) | ✅ Chuyển sang yfinance |
| VNDirect DNS fail | ✅ Chuyển sang yfinance |
| VNINDEX không có trên Yahoo | ✅ Dùng DNSE entrade index |
| Dữ liệu ngoài giờ = 0 | ✅ yfinance daily data 24/7 |
| Telegram crash khi mất mạng | ✅ Try/except graceful |
| Chatbot lỗi file:// CORS | ✅ Dùng localhost:8000 |
| Watchlist JSON race condition | ✅ Migrated sang SQLite |
| Gemini hết quota làm chatbot trả lỗi cụt | ✅ Thêm NVIDIA NIM fallback + local fallback |

---

## 🛣️ Roadmap

- [x] SQLite watchlist storage
- [x] Health endpoint
- [x] Portfolio tracker – Tính lãi/lỗ cơ bản
- [x] Stock scanner/filter cơ bản
- [x] Alert nâng cao rule-based cơ bản
- [ ] Data quality & cache layer
- [x] AI prompt safety & fallback
- [ ] Frontend robustness
- [ ] Backtesting engine
- [ ] Deploy cloud (Railway/Render)
