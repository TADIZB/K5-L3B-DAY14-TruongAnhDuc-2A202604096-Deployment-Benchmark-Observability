# Nhật ký làm bài — Day 14

Ghi lại chi tiết từng checkpoint: đã làm gì, chạy lệnh gì, kết quả ra sao, gặp lỗi gì và xử lý thế nào.
Câu trả lời chính thức để chấm nằm trong [MISSION_ANSWERS.md](MISSION_ANSWERS.md); file này là nhật ký quá trình.

## Môi trường làm bài

Mỗi lần mở terminal Ubuntu (WSL2) mới:

```bash
source ~/venvs/day14/bin/activate
cd "/mnt/d/Coding/K5-L3B-DAY14-TruongAnhDuc-2A202604096-Deployment-Benchmark-Observability"
```

| Thành phần | Phiên bản |
|---|---|
| Python (WSL Ubuntu, venv `~/venvs/day14`) | 3.12.3, `os.name` = `posix` |
| Docker / Compose | 28.1.1 / v2.35.1 |

## Tiến độ

| Checkpoint | Trạng thái | Sản phẩm |
|---|---|---|
| CP0 · Setup | ✅ Xong | Repo đúng tên, Public; venv WSL; Docker chạy `hello-world` |
| CP1 · Localhost vs Production | ✅ Xong | `MISSION_ANSWERS.md` mục Part 1 |
| CP2 · Docker | ⏳ | |
| CP3 · API Security | ⏳ | |
| CP4 · Scaling & Reliability | ⏳ | |
| CP5 · Final Project | ⏳ | |
| CP6 · Cloud Deployment | ⏳ | |
| CP7 · Benchmark local | ⏳ | |
| CP8 · Observability + nộp | ⏳ | |

---

## CP1 — Localhost vs Production (2026-11-26)

**Mục tiêu:** chỉ ra vì sao code chạy trên laptop chưa sẵn sàng cho production.
**Thư mục:** `01-localhost-vs-production/`

### Bước 1 — Exercise 1.1: đọc `develop/app.py` tìm anti-pattern

Đọc file, tìm được 10 vấn đề (yêu cầu tối thiểu 5): hardcode `OPENAI_API_KEY` và `DATABASE_URL` (L17-18), in secret ra log (L34), `DEBUG`/`MAX_TOKENS` cứng (L21-22), dùng `print()` (L33-38), không có `/health`, bind `localhost` (L51), port cứng 8000 (L52), `reload=True` (L53), không xử lý shutdown, `question` đi qua query string. Chi tiết từng dòng ở MISSION_ANSWERS Part 1.

### Bước 2 — Exercise 1.2: chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
curl -i -X POST "http://localhost:8000/ask?question=Hello"   # 200
curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'   # 422
curl -i http://localhost:8000/health   # 404
```

Kết quả:
- Gọi qua query → **200**, trả câu trả lời mock.
- Gửi JSON → **422** (`loc: ["query","question"]`), đúng như lưu ý K5 số 3.
- `/health` → **404**, chứng minh không có health check.
- Log server có dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`: **secret bị in thẳng ra log**.

### Bước 3 — Exercise 1.3: chạy bản production và so sánh

```bash
cd ../production
cp .env.example .env          # .env bị .gitignore chặn (đã kiểm bằng git check-ignore)
pip install -r requirements.txt
python app.py
```

| Lệnh | Kết quả |
|---|---|
| `GET /health` | 200, có `uptime_seconds`, `environment`, `timestamp` |
| `GET /ready` | 200 `{"ready":true}` |
| `POST /ask` JSON `{"question":"What is deploy?"}` | 200, có `question`, `answer`, `model` |
| `POST /ask` JSON `{}` | 422 `question field is required` |

Ba thí nghiệm thêm để kiểm chứng bảng so sánh:

1. `PORT=9000 ENVIRONMENT=staging python app.py` → `/health` trên cổng 9000 trả `"environment":"staging"`. Config đổi được qua env, không sửa code.
2. `ENVIRONMENT=production python app.py` (không có `AGENT_API_KEY`) → app dừng ngay với `ValueError: AGENT_API_KEY must be set in production!` (fail fast).
3. Gửi `POST /ask` rồi 30 ms sau gửi `SIGTERM` cho server → request vẫn trả **200**, log có `Shutting down → Application shutdown complete → Finished server process`, **exit code 0** (graceful shutdown).

Điền bảng so sánh 10 dòng (Config, Secrets, Validate config, Host/Port, Health check, Logging, Shutdown, Reload, Input, CORS) vào MISSION_ANSWERS.

### Phát hiện thêm

- **Log JSON của bản production không hiện.** `config.py` gọi `logging.warning()` lúc import, trước `logging.basicConfig()` trong `app.py`, nên root logger đã bị cấu hình với format mặc định và level WARNING; các dòng `logger.info(json.dumps(...))` bị bỏ. Sửa bằng `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import config. **Ghi nhớ cho CP5:** script chấm Part 6 yêu cầu mỗi dòng log là JSON hợp lệ.
- **`.env` không được nạp.** Có `python-dotenv` trong requirements nhưng code không gọi `load_dotenv()`; config chỉ lấy từ env thật của shell/platform.

### Lỗi gặp phải và cách xử lý

| Lỗi | Nguyên nhân | Xử lý |
|---|---|---|
| Dùng `pkill -f "app.py"` để tắt server thì shell của chính mình cũng bị kill (exit code 15) | Dòng lệnh của shell cũng chứa chữ `app.py` nên bị khớp | Tắt server bằng PID (`kill -TERM $PID`) thay vì `pkill -f` |
| Bản develop bật `reload=True` nên có 2 process (reloader + server) | Đặc điểm của chế độ reload | Ctrl+C ở terminal chạy server là tắt cả hai |

### Kết quả CP1

- [x] `MISSION_ANSWERS.md` mục Part 1: 10 anti-pattern có số dòng, output gọi bản develop, bảng so sánh có cột giải thích.
- [x] Tự kiểm tra: chỉ ra anti-pattern L17/L34 của develop đã được production sửa ở `config.py` và `app.py` L111-115.
- [x] Đã tắt hết server, cổng 8000 trống cho CP2.
