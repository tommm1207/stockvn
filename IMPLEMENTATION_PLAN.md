# StockVN Implementation Plan

## Mục Tiêu

Nâng StockVN từ bản dashboard/demo thành công cụ theo dõi cổ phiếu Việt Nam dùng được ổn định hơn trong thực tế. Plan này dành cho chuỗi làm việc nhiều agent:

1. Claude Code triển khai theo từng phase.
2. Codex review, sửa lỗi và bổ sung test/edge case.
3. Claude Code review lại thay đổi của Codex.
4. Antigravity kiểm tra toàn bộ project, luồng UI, API, runtime và chất lượng tổng thể.

Nguyên tắc chung:

- Không làm tất cả cùng lúc. Làm theo phase, mỗi phase phải chạy được trước khi qua phase tiếp theo.
- Ưu tiên dữ liệu đúng, trạng thái lỗi rõ ràng, và luồng người dùng dùng được hơn là thêm nhiều UI mới.
- Không thay đổi visual language hiện tại nếu không cần. UI đang là dashboard tối, card nhỏ, nhiều số liệu, phù hợp công cụ tài chính.
- Không đưa chức năng đặt lệnh thật hoặc khuyến nghị chắc chắn lợi nhuận. Nội dung AI và tín hiệu kỹ thuật phải có cảnh báo rủi ro.

## Hiện Trạng Sau Vòng Sửa Gần Nhất

Đã có:

- FastAPI backend trong `backend/main.py`.
- Fetch dữ liệu qua `yfinance` và DNSE trong `backend/data_fetcher.py`.
- Phân tích kỹ thuật trong `backend/technical_analysis.py`.
- Gemini AI trong `backend/ai_analyzer.py`.
- Telegram bot trong `backend/telegram_bot.py`.
- Frontend tĩnh: `frontend/index.html`, `frontend/stock.html`, `frontend/watchlist.html`, `frontend/chatbot.html`.
- CSS chung trong `frontend/css/style.css`.
- Watchlist vẫn lưu JSON nhưng đã có lock và atomic write.
- Frontend gọi API bằng `/api`, không còn hardcode `localhost`.
- Web watchlist dùng client id riêng dạng `web_<hex>` trong `localStorage`.
- Backend đã serve `/`, `/index.html`, `/stock.html`, `/watchlist.html`, `/css/style.css`.

Vẫn cần cải thiện:

- Chưa có database thật.
- Chưa có portfolio.
- Chưa có test suite.
- Chưa có data quality layer rõ ràng.
- Chưa có scanner/filter cổ phiếu.
- Chưa có alert cấu hình được.
- Tài liệu `CONTEXT.md` đang lệch một phần với code hiện tại.

## Phase 0: Baseline Và Dọn Nền

Mục tiêu: tạo nền ổn định trước khi thêm tính năng.

### Việc Cần Làm

- Cập nhật `CONTEXT.md` cho khớp code hiện tại:
  - Dashboard chính là `http://localhost:8000/`, không phải chỉ `/static/index.html`.
  - Frontend API dùng `/api`.
  - Watchlist web dùng client id localStorage, Telegram dùng chat id số.
  - `yfinance` có cache location trong `backend/.yfinance_cache`.
  - CORS lấy từ `CORS_ALLOW_ORIGINS`.

- Chuẩn hóa cấu hình môi trường:
  - Thêm file `.env.example`.
  - Document các biến:
    - `GEMINI_API_KEY`
    - `TELEGRAM_TOKEN`
    - `CORS_ALLOW_ORIGINS`
    - `YFINANCE_CACHE_DIR`
    - `DATABASE_URL` sau Phase 1

- Dọn runtime artifacts:
  - Không commit `__pycache__`.
  - Không commit `.yfinance_cache`.
  - Không commit log uvicorn.
  - Giữ `.gitignore` đồng bộ.

- Kiểm tra `run.bat`:
  - Đảm bảo chạy đúng từ root bất kể current directory.
  - In đúng dashboard URL: `http://localhost:8000/`.
  - Có hướng dẫn cài dependency nếu thiếu package.

### Acceptance Criteria

- Chạy `run.bat` mở được dashboard có CSS.
- `GET /`, `/css/style.css`, `/api/symbols` trả `200`.
- Tài liệu không còn chỉ sai URL cũ.
- Không có file cache/log mới nằm ngoài `.gitignore`.

### Review Checklist

- Codex kiểm tra route static, docs, env example.
- Claude Code kiểm tra lại Windows flow bằng `run.bat`.
- Antigravity mở UI trên desktop và mobile viewport.

## Phase 1: Chuyển Watchlist Sang SQLite

Mục tiêu: thay JSON bằng storage ổn định, tránh mất dữ liệu khi nhiều request cùng lúc.

### Thiết Kế

Dùng SQLite trước, chưa cần Postgres. Project nhỏ, chạy local/desktop, SQLite đủ tốt và dễ bảo trì.

File đề xuất:

- `backend/database.py`
- `backend/repositories/watchlist_repo.py` hoặc nếu muốn ít file hơn: thay `watchlist_manager.py` thành SQLite-backed manager.

Schema tối thiểu:

```sql
CREATE TABLE IF NOT EXISTS watchlists (
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, symbol)
);
```

Nên thêm bảng metadata:

```sql
CREATE TABLE IF NOT EXISTS app_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

### Việc Cần Làm

- Tạo SQLite database tại `backend/stockvn.db` mặc định.
- Cho phép override bằng `DATABASE_URL` hoặc `SQLITE_PATH`.
- Implement migration nhẹ:
  - Khi app startup, tạo bảng nếu chưa có.
  - Nếu `watchlist_data.json` tồn tại, migrate các symbol sang SQLite.
  - Ghi metadata `watchlist_json_migrated=true` để không migrate lặp.
  - Không xóa JSON cũ tự động; có thể rename thủ công sau khi verify.

- Giữ API contract hiện tại:
  - `GET /api/watchlist/{chat_id}`
  - `POST /api/watchlist/{chat_id}/{symbol}`
  - `DELETE /api/watchlist/{chat_id}/{symbol}`
  - `GET /api/watchlist/{chat_id}/analyze`

- Telegram bot vẫn dùng cùng manager/repo.

### Acceptance Criteria

- Add/remove watchlist từ web lưu vào SQLite.
- Add/remove từ Telegram dùng chung storage.
- Restart server không mất watchlist.
- Nếu JSON cũ có dữ liệu, migrate được sang SQLite.
- Không còn ghi file JSON trong luồng runtime bình thường.

### Tests

- Unit test:
  - Add symbol mới trả `True`.
  - Add symbol trùng trả `False`.
  - Remove symbol có tồn tại trả `True`.
  - Remove symbol không tồn tại trả `False`.
  - `get_all_unique_symbols` không duplicate.
  - `get_all_users_for_symbol` đúng user.

- Integration test:
  - FastAPI watchlist endpoints với SQLite temp file.

## Phase 2: Data Quality Và Cache Layer

Mục tiêu: dữ liệu thị trường lỗi/chậm phải được quản lý rõ, không làm UI mơ hồ.

### Vấn Đề Hiện Tại

- `yfinance` có thể fail do network, cache, rate limit.
- DNSE có thể fail ngoài mạng hoặc đổi API.
- Dashboard gọi nhiều mã một lúc, dễ chậm.
- Frontend hiện chủ yếu hiển thị empty/error đơn giản.

### Thiết Kế

Tạo lớp kết quả dữ liệu có metadata:

```python
{
  "data": [...],
  "source": "yfinance",
  "cached": true,
  "fetched_at": "2026-05-21T...",
  "error": null
}
```

Không nhất thiết phải thay toàn bộ API public ngay. Có thể giữ response hiện tại và thêm field:

- `data_source`
- `cached`
- `fetched_at`
- `warnings`

### Việc Cần Làm

- Tách cache helper rõ hơn trong `data_fetcher.py`.
- Cache theo symbol/period thay vì chỉ symbol/days nếu hợp lý.
- Thêm TTL cấu hình bằng env:
  - `HISTORICAL_CACHE_TTL_SECONDS`
  - `TOP_MOVERS_CACHE_TTL_SECONDS`
  - `MARKET_OVERVIEW_CACHE_TTL_SECONDS`

- Thêm fallback strategy:
  - Historical daily: yfinance `.VN`, fallback raw symbol.
  - Intraday: DNSE, nếu lỗi trả `[]` kèm warning.
  - Market overview: nếu DNSE lỗi, trả zero hiện tại nhưng phải kèm warning để frontend biết.

- Backend không nên trả `500` cho lỗi nguồn dữ liệu thông thường nếu vẫn có response fallback. Chỉ `500` khi lỗi app thật.

### Acceptance Criteria

- Khi mất mạng, dashboard không crash.
- API trả warning rõ ràng.
- Frontend hiển thị thông báo dữ liệu tạm thời không khả dụng.
- Cache hit không gọi lại network trong TTL.

### Tests

- Mock yfinance trả empty.
- Mock DNSE timeout.
- Test cache hit/cache expire.
- Test API response có warnings.

## Phase 3: Portfolio Tracker

Mục tiêu: biến app từ “xem tín hiệu” thành công cụ theo dõi danh mục thật.

### Tính Năng

Người dùng web có thể:

- Thêm lệnh mua/bán thủ công.
- Lưu:
  - `symbol`
  - `side`: BUY/SELL
  - `quantity`
  - `price`
  - `fee`
  - `trade_date`
  - `note`
- Xem tổng hợp:
  - Tổng vốn
  - Giá trị hiện tại
  - Lãi/lỗ tuyệt đối
  - Lãi/lỗ %
  - Tỷ trọng từng mã
  - Giá vốn bình quân

### Schema Đề Xuất

```sql
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  quantity REAL NOT NULL CHECK (quantity > 0),
  price REAL NOT NULL CHECK (price > 0),
  fee REAL NOT NULL DEFAULT 0,
  trade_date TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
```

Có thể tính holding từ trades mỗi request để tránh lỗi đồng bộ. Nếu sau này lớn mới denormalize.

### API Đề Xuất

- `GET /api/portfolio/{user_id}`
- `GET /api/portfolio/{user_id}/trades`
- `POST /api/portfolio/{user_id}/trades`
- `PUT /api/portfolio/{user_id}/trades/{trade_id}`
- `DELETE /api/portfolio/{user_id}/trades/{trade_id}`

### Frontend

Thêm trang mới:

- `frontend/portfolio.html`

Thêm nav item:

- Dashboard
- Watchlist
- Portfolio

UI yêu cầu:

- Bảng holdings dạng dense, dễ scan.
- Form thêm giao dịch compact.
- Không làm landing page.
- Mobile phải dùng được: bảng có scroll ngang hoặc card list.

### Acceptance Criteria

- Thêm giao dịch BUY tạo holding.
- Thêm SELL giảm quantity.
- Không cho SELL vượt số lượng đang nắm giữ, trừ khi quyết định hỗ trợ short. Mặc định không hỗ trợ short.
- Tính P/L dựa trên giá mới nhất từ data layer.
- Restart server không mất dữ liệu.

### Tests

- Average cost calculation.
- Sell partial.
- Sell full.
- Fee included in cost.
- API validation.

## Phase 4: Stock Scanner Và Bộ Lọc

Mục tiêu: giúp người dùng tìm cơ hội thay vì chỉ nhập từng mã.

### Tính Năng

Trang hoặc section scanner:

- Lọc theo:
  - Recommendation: BUY/HOLD/SELL.
  - Score min/max.
  - RSI range.
  - Volume ratio.
  - Price above/below MA20.
  - MACD cross.
  - Bollinger position.

- Sort theo:
  - Score cao nhất.
  - Change %.
  - Volume ratio.
  - RSI thấp nhất/cao nhất.

### Backend API

- `GET /api/scanner`

Query params:

- `symbols`: optional CSV.
- `recommendation`
- `min_score`
- `max_score`
- `min_rsi`
- `max_rsi`
- `min_volume_ratio`
- `macd_cross`
- `bb_position`
- `sort`
- `limit`

Default universe:

- Bắt đầu với `POPULAR_STOCKS`.
- Sau đó có thể mở rộng sang `VN_STOCKS`.

### Acceptance Criteria

- Scanner chạy được với ít nhất `POPULAR_STOCKS`.
- Có loading/progress hoặc thông báo nếu scan chậm.
- API giới hạn `limit` để không scan quá nhiều mã một lúc.
- Cache scanner result ngắn hạn.

### Tests

- Filter score.
- Filter recommendation.
- Sort.
- Limit.
- Invalid query params.

## Phase 5: Alert Nâng Cao

Mục tiêu: alert không chỉ dựa vào `abs(score) >= 5`, mà user cấu hình được.

### Tính Năng

User có thể tạo rule:

- Symbol-specific hoặc toàn watchlist.
- Điều kiện:
  - Price above/below.
  - RSI below/above.
  - Score above/below.
  - MACD bullish/bearish cross.
  - Volume ratio above.
  - Price crosses MA20/MA50.

- Channel:
  - Web only, Telegram only, hoặc cả hai.

### Schema Đề Xuất

```sql
CREATE TABLE IF NOT EXISTS alert_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  symbol TEXT,
  rule_type TEXT NOT NULL,
  operator TEXT NOT NULL,
  threshold REAL,
  enabled INTEGER NOT NULL DEFAULT 1,
  channel TEXT NOT NULL DEFAULT 'telegram',
  cooldown_minutes INTEGER NOT NULL DEFAULT 60,
  last_triggered_at TEXT,
  created_at TEXT NOT NULL
);
```

### API

- `GET /api/alerts/{user_id}`
- `POST /api/alerts/{user_id}`
- `PUT /api/alerts/{user_id}/{rule_id}`
- `DELETE /api/alerts/{user_id}/{rule_id}`

### Acceptance Criteria

- Rule không spam nhờ cooldown.
- Scheduler scan rule enabled.
- Telegram chỉ gửi cho user id số.
- Web user có thể lưu rule nhưng nếu không có Telegram chat id thì không gửi Telegram.

### Tests

- Rule matching.
- Cooldown.
- Disabled rule.
- Invalid threshold/operator.

## Phase 6: AI Và Prompt Safety

Mục tiêu: AI hữu ích hơn nhưng không bịa dữ liệu và không đưa cam kết đầu tư.

### Việc Cần Làm

- Chuẩn hóa output AI:
  - Có section cố định.
  - Có disclaimer ngắn.
  - Không dùng số ngoài snapshot.

- Thêm AI fallback:
  - Nếu Gemini lỗi quota, dùng phân tích kỹ thuật local để tạo summary.
  - Không để UI chỉ nói “AI lỗi” nếu vẫn có indicators.

- Thêm cache cho AI theo:
  - symbol
  - last_date
  - score
  - model

- Tránh gửi history quá dài trong chatbot.
- Validate message length:
  - Backend reject hoặc truncate message quá dài.

### Acceptance Criteria

- `/api/stock/{symbol}/ai` không gọi Gemini lại nếu cùng dữ liệu trong TTL.
- Chatbot không nhận payload quá lớn.
- Khi Gemini lỗi, frontend vẫn hiển thị fallback summary.

### Tests

- Gemini exception fallback.
- Cache key theo symbol/date.
- Message length validation.

## Phase 7: Test Suite Và CI Local

Mục tiêu: các agent sau sửa code có lưới an toàn.

### Tooling

Thêm vào `backend/requirements.txt` hoặc `requirements-dev.txt`:

- `pytest`
- `pytest-asyncio`
- `respx` hoặc `pytest-httpx`
- `fastapi[testclient]` nếu cần

### Cấu Trúc Test

```text
tests/
  test_technical_analysis.py
  test_watchlist_manager.py
  test_portfolio.py
  test_data_fetcher_cache.py
  test_api_watchlist.py
  test_api_scanner.py
```

### Commands

```bat
cd D:\stock-analyzer
python -m pytest
python -m compileall backend
```

### Acceptance Criteria

- Test không cần network thật.
- Các test data fetch phải mock network.
- `python -m pytest` chạy được trên Windows.
- README/CONTEXT có ghi command test.

## Phase 8: Frontend Robustness

Mục tiêu: UI không vỡ khi API chậm/lỗi và dùng ổn trên desktop/mobile.

### Việc Cần Làm

- Tạo helper JS chung nếu tiếp tục dùng vanilla HTML:
  - `frontend/js/api.js`
  - `frontend/js/storage.js`
  - `frontend/js/dom.js`

- Không bắt buộc refactor toàn bộ ngay. Nhưng các logic lặp như `cleanSymbol`, `getClientId`, `esc`, search dropdown nên đưa vào helper khi chạm nhiều file.

- Cải thiện states:
  - loading
  - empty
  - partial data
  - API offline
  - AI unavailable

- Kiểm tra responsive:
  - Dashboard cards.
  - Chart toolbar trên mobile.
  - Watchlist table.
  - Portfolio table sau Phase 3.

### Acceptance Criteria

- Không còn text tràn khỏi button/card ở mobile width 375px.
- Chart toolbar không làm layout ngang vỡ khó dùng.
- Search không inject HTML.
- Các page chính reload trực tiếp được:
  - `/`
  - `/stock.html?symbol=VNM`
  - `/watchlist.html`
  - `/portfolio.html` sau Phase 3

## Phase 9: Observability Và Runtime Operations

Mục tiêu: khi app lỗi, biết lỗi ở đâu.

### Việc Cần Làm

- Logging có cấu trúc hơn:
  - source
  - symbol
  - endpoint
  - latency nếu đơn giản.

- Thêm health endpoint:
  - `GET /api/health`
  - Trả:
    - app status
    - database status
    - optional external data status cache

- Thêm version endpoint:
  - `GET /api/version`

- Không log API key/token.

### Acceptance Criteria

- `/api/health` trả `200` nếu app + DB ok.
- Nếu DB lỗi, health trả `503`.
- Logs đủ để biết data source nào fail.

## Agent Handoff Protocol

Mỗi agent khi làm xong phải cập nhật cuối file này phần “Progress Log”.

Format bắt buộc:

```markdown
## Progress Log

### 2026-05-21 - Agent Name

- Phase worked on:
- Files changed:
- Commands run:
- Tests passed:
- Known remaining issues:
- Suggested next step:
```

Không ghi chung chung. Nếu không chạy test được, phải nói rõ lý do.

## Review Checklist Tổng

Trước khi coi là hoàn tất một phase:

- Backend import được:

```bat
cd D:\stock-analyzer\backend
python -c "import main; print('import ok')"
```

- Backend compile được:

```bat
cd D:\stock-analyzer
python -m compileall backend
```

- Server chạy được:

```bat
cd D:\stock-analyzer\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- Smoke test:

```text
GET http://127.0.0.1:8000/
GET http://127.0.0.1:8000/css/style.css
GET http://127.0.0.1:8000/api/symbols
GET http://127.0.0.1:8000/api/health
```

- UI manual test:
  - Dashboard render có CSS.
  - Search mã hợp lệ.
  - Search input độc hại không inject HTML.
  - Mở stock detail.
  - Add/remove watchlist.
  - Reload page vẫn giữ client id.
  - Telegram bot không crash khi mất mạng.

## Rủi Ro Cần Theo Dõi

- Nguồn dữ liệu miễn phí có thể đổi API hoặc rate limit.
- AI Gemini có quota và model name có thể thay đổi.
- Telegram polling cần network ổn định.
- Vanilla JS trong HTML đang lớn dần; nếu thêm nhiều tính năng, nên cân nhắc tách JS module trước khi code khó maintain.
- SQLite ổn cho local/small app nhưng nếu deploy nhiều user đồng thời, cần đánh giá lại.

## Progress Log

### 2026-05-21 - Codex

- Phase worked on: Planning.
- Files changed: `IMPLEMENTATION_PLAN.md`.
- Commands run: `rg --files`, `Get-Content -Raw CONTEXT.md`.
- Tests passed: Not applicable, planning-only change.
- Known remaining issues: `CONTEXT.md` still needs update in Phase 0.
- Suggested next step: Claude Code should start with Phase 0, then Phase 1 SQLite migration.

### 2026-05-21 - Antigravity

- Phase worked on: Phase 0 (Baseline) + Phase 1 (SQLite Migration).
- Files changed:
  - `CONTEXT.md` – Full rewrite: fixed URLs, documented env vars, client IDs, SQLite storage, /api/health, all endpoints.
  - `backend/.env.example` – **NEW** – Template for all env vars.
  - `.gitignore` – Added *.db, runtime JSON, IDE files, OS artifacts.
  - `run.bat` – Portable paths via `%~dp0`, dependency check step, correct URL.
  - `backend/database.py` – **NEW** – SQLite connection (WAL, thread-local), schema, JSON→SQLite migration, health check.
  - `backend/watchlist_manager.py` – Rewritten: JSON → SQLite-backed, same public API.
  - `backend/main.py` – Added `init_db()` in lifespan, added `/api/health` endpoint.
  - `tests/test_watchlist_manager.py` – **NEW** – 18 unit tests covering CRUD, migration, health.
- Commands run:
  - `python -m compileall backend` → OK
  - `python -c "import main; print('import ok')"` → OK
  - `python -m pytest tests/ -v` → 18/18 passed (0.43s)
- Tests passed: 18/18 (TestAddSymbol: 4, TestRemoveSymbol: 3, TestGetUserWatchlist: 3, TestGetAllUniqueSymbols: 2, TestGetAllUsersForSymbol: 2, TestGetAllUsers: 2, TestJsonMigration: 1, TestDatabaseHealth: 1)
- Known remaining issues:
  - `uvicorn.verify.out.log` still exists in root (not deleted, only added to gitignore).
  - Telegram bot not tested (no token in test env).
  - Server smoke test (GET /, /css/style.css, /api/health) not yet automated.
- Suggested next step: Start Phase 2 (Data Quality & Cache Layer) or Phase 3 (Portfolio Tracker).

### 2026-05-21 - Codex

- Phase worked on: Review fixes for Phase 0/1 plus stabilization for partially implemented Phase 3/4/5.
- Files changed:
  - `frontend/scanner.html` – Fixed filter values to match backend contract (`BUY/SELL`, `below_lower/above_upper`).
  - `backend/main.py` – Added symbol validation for portfolio, scanner, and alert endpoints.
  - `backend/portfolio_manager.py` – Added update-time validation for quantity, price, fee, and oversell prevention.
  - `backend/tests/test_portfolio.py` – Added tests for invalid trade updates and oversell updates.
  - `backend/tests/test_api_endpoints.py` – Added invalid symbol API tests for portfolio, scanner, and alerts.
  - `pytest.ini` – Added root-level pytest config with `pythonpath=backend` and `testpaths=backend/tests`.
  - `CONTEXT.md` – Updated test command, file structure, API docs, storage docs, and roadmap status.
- Commands run:
  - `python -m pytest -q` from project root.
  - `python -m compileall backend`.
  - `python -c "import main; print('import ok')"` from `backend`.
- Tests passed: `python -m pytest -q` -> 16 passed; `python -m compileall backend` -> OK; backend import -> OK; smoke test for `/`, `/css/style.css`, `/api/health`, `/portfolio.html`, `/scanner.html` -> all 200.
- Known remaining issues:
  - Data quality/cache layer is still incomplete.
  - AI fallback/cache safety is still incomplete.
  - Runtime artifacts may still exist locally but are ignored by `.gitignore`.
- Suggested next step: Run full verification, then continue Phase 2.

### 2026-05-21 - Codex

- Phase worked on: Phase 6 AI fallback.
- Files changed:
  - `backend/ai_analyzer.py` – Added NVIDIA NIM provider fallback after Gemini, using OpenAI-compatible `/chat/completions`; retained local fallback after provider failures.
  - `backend/.env.example` – Added `NVIDIA_API_KEY`, `NVIDIA_MODEL`, `NVIDIA_BASE_URL`, `NVIDIA_TIMEOUT_SECONDS`.
  - `CONTEXT.md` – Documented Gemini → NVIDIA NIM → local fallback flow.
- Commands run:
  - `python -m pytest -q`
  - `python -m compileall backend`
- Tests passed: `python -m pytest -q` -> 16 passed; `python -m compileall backend` -> OK.
- Known remaining issues:
  - NVIDIA API cannot be live-tested until `NVIDIA_API_KEY` is provided in `.env`.
  - Existing port 8000 may still have stale server processes from earlier reload attempts; restart cleanly after adding env.
- Suggested next step: Add real NVIDIA key to `backend/.env`, restart backend, then test `/api/chat`.
