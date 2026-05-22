# 📈 StockVN – Phân Tích Cổ Phiếu Toàn Thị Trường

StockVN là hệ thống toàn diện giúp nhà đầu tư phân tích, theo dõi và tìm kiếm cơ hội giao dịch trên thị trường chứng khoán Việt Nam.

## 🌟 Tính Năng Chính
- **Scanner Toàn Thị Trường:** Quét ngầm `1800+` mã cổ phiếu, lọc ra các mã có tín hiệu Tích luỹ, Đột biến bùng nổ, và Rủi ro phân phối.
- **Trợ lý AI & Chatbot:** Phân tích kỹ thuật tự động và nhận định thị trường dựa trên công nghệ AI (Gemini).
- **Telegram Bot:** Nhận tin nhắn cảnh báo biến động trực tiếp trên Telegram, xem kế hoạch giao dịch (Entry/Stoploss) bằng lệnh `/entry`.
- **UI/UX Mobile First (PWA):** Giao diện Dark mode tối giản, tốc độ tải siêu nhanh và có thể cài đặt như app gốc trên điện thoại.

## 🛠 Cài đặt (Chạy Local)

1. Cài đặt Python 3.9+
2. Khởi tạo môi trường và cài thư viện:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
3. Tạo file `.env` trong thư mục `backend/` (sử dụng mẫu từ `.env.example`):
   ```env
   GEMINI_API_KEY=your_gemini_key
   TELEGRAM_TOKEN=your_telegram_bot_token
   ```
4. Chạy hệ thống:
   ```bash
   cd backend
   python main.py
   ```
   *Web sẽ khởi chạy tại: `http://localhost:8000`*

## 🌐 Triển khai lên Render.com (Miễn phí)

Hệ thống được thiết kế hoàn hảo để đẩy lên **Render** (được cung cấp tên miền đẹp `your-app.onrender.com` và chạy Bot/Scanner ngầm 24/7):

1. Đẩy mã nguồn này lên GitHub của bạn.
2. Đăng nhập [Render.com](https://render.com) bằng GitHub.
3. Tạo mới một **Web Service**.
4. Liên kết với Repository GitHub của bạn.
5. Cấu hình Web Service:
   - **Root Directory:** Để trống (hoặc `backend`)
   - **Build Command:** `pip install -r backend/requirements.txt`
   - **Start Command:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Trong mục **Environment Variables**, thêm các biến:
   - `GEMINI_API_KEY` = (Key của bạn)
   - `TELEGRAM_TOKEN` = (Key của bạn)
7. Nhấn **Deploy** và đợi Render cấp tên miền.

## 📚 Công nghệ sử dụng
- **Backend:** Python (FastAPI), SQLite, AsyncIO.
- **Data APIs:** VNDirect Data API, Wifeed API, DNSE Entrade API (Loại bỏ hoàn toàn yfinance).
- **Frontend:** Vanilla JS, CSS Variables, Lightweight Charts.
- **AI:** Google Gemini Pro.
