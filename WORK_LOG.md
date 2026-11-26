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
| CP2 · Docker | ✅ Xong | `MISSION_ANSWERS.md` mục Part 2 |
| CP3 · API Security | ✅ Xong | `MISSION_ANSWERS.md` mục Part 4 |
| CP4 · Scaling & Reliability | ✅ Xong | `MISSION_ANSWERS.md` mục Part 5 |
| CP5 · Final Project | ✅ Xong — PASS 12/12 | Code `06-lab-complete/`, `MISSION_ANSWERS.md` mục Part 6 |
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

---

## CP2 — Docker (2026-11-26)

**Mục tiêu:** đóng gói agent thành image nhỏ, chạy giống nhau ở mọi máy.
**Thư mục:** `02-docker/`. Mọi lệnh `docker build` chạy từ **gốc repo** (lưu ý K5 số 4).

### Bước 1 — Exercise 2.1: đọc `02-docker/develop/Dockerfile`

Trả lời 4 câu: base `python:3.11`; `WORKDIR /app`; copy `requirements.txt` trước để tận dụng layer cache (layer `pip install` 53.3 MB không phải build lại khi chỉ sửa code); `CMD` là lệnh mặc định bị thay khi truyền lệnh vào `docker run`, `ENTRYPOINT` là phần cố định, tham số được nối thêm vào sau.

### Bước 2 — Exercise 2.2: build và chạy image develop

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name p2-develop -p 8000:8000 my-agent:develop
curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"   # 200
curl http://localhost:8000/health                                           # 200
docker exec p2-develop sh -c 'whoami; python --version'                     # root, Python 3.11.18
docker rm -f p2-develop
```

Container develop chạy bằng **root**.

### Bước 3 — Exercise 2.3: build image multi-stage và so sánh

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent
docker run -d --name p2-adv -p 8000:8000 my-agent:advanced
docker exec p2-adv sh -c 'whoami; which gcc || echo "no gcc"'   # appuser, no gcc
docker history my-agent:advanced
docker rm -f p2-adv
```

| Image | `docker images` | `docker image inspect` (nén) |
|---|---:|---:|
| `my-agent:develop` | **1.67 GB** | 426 319 939 bytes |
| `my-agent:advanced` | **240 MB** | 57 409 145 bytes |
| Giảm | **85.6 %** | 86.5 % |

Container advanced lên trạng thái `(healthy)` nhờ `HEALTHCHECK`, chạy bằng `appuser`, không có `gcc`.

### Bước 4 — Exercise 2.4: Docker Compose stack

```bash
cd 02-docker/production
touch .env.local                                   # lưu ý K5 số 5; đã bị .gitignore chặn
docker compose -p k5-day14-docker up -d --build    # -p riêng theo lưu ý K5 số 7
docker compose -p k5-day14-docker ps
curl -i http://localhost/health                    # 200, Server: nginx
curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'   # 200
curl -m 3 http://localhost:8000/health             # 000: agent không mở port ra host
# 40 request song song → 28 × 200, 12 × 429 (Nginx limit_req 10 r/s, burst 20)
docker compose -p k5-day14-docker exec agent python -c "import socket;print(socket.gethostbyname('redis'))"   # DNS theo tên service
docker compose -p k5-day14-docker down -v
```

4 service: nginx (cổng 80/443) → agent:8000 → redis:6379, qdrant:6333, cùng network `internal`. Đã vẽ sơ đồ trong MISSION_ANSWERS.

### Phát hiện thêm

- Log của `02-docker/production/main.py` là JSON lồng trong chuỗi không escape (`"msg":"{"event": ...}"`), nên **không phải JSON hợp lệ**. **Ghi nhớ cho CP5:** dùng formatter tự `json.dumps` cả dòng log.
- `docker images` trên Docker Desktop (containerd store) báo dung lượng trên đĩa, lớn hơn dung lượng nén của `docker image inspect`. Bài dùng số của `docker images` như đề yêu cầu.

### Lỗi gặp phải và cách xử lý

Không gặp lỗi. Đã tạo `.env.local` trước nên `docker compose up` không báo thiếu file.

### Kết quả CP2

- [x] `MISSION_ANSWERS.md` mục Part 2: 4 câu Exercise 2.1, kết quả gọi container, kích thước image đo được kèm %, sơ đồ stack 2.4, kết quả test qua Nginx.
- [x] Tự kiểm tra: số MB là số đo trên máy (1.67 GB / 240 MB), không chép từ README (README ghi ~800 MB / ~160 MB).
- [x] Đã xoá container `p2-develop`, `p2-adv` và dọn stack (`down -v`); cổng 80, 8000 trống.

---

## CP3 — API Security / Part 4 (2026-11-26)

**Mục tiêu:** chặn truy cập trái phép, gọi quá nhanh và tiêu quá ngân sách.
**Thư mục:** `04-api-gateway/`. Làm theo lưu ý K5 số 6.

### Bước 1 — Exercise 4.1: API key (`develop/`)

```bash
cd 04-api-gateway/develop
pip install -r requirements.txt
AGENT_API_KEY=secret-key-123 python app.py
```

| Trường hợp | Kết quả |
|---|---|
| Không có `X-API-Key` | **401** `Missing API key` |
| Key sai | **403** `Invalid API key.` |
| Key đúng `secret-key-123` | **200** |
| `/health` không key | 200 (public) |

Đọc code: check ở dependency `verify_api_key` (L39-54), gắn vào `/ask` bằng `Depends` (L70). Rotate key: đổi env `AGENT_API_KEY` rồi restart, không sửa code.

### Bước 2 — Exercise 4.2: JWT (`production/`)

Tắt bản develop, `pip install -r requirements.txt`, `python app.py`. Lấy token ở `POST /auth/token` với `student` / `demo123` (không phải `/token` và `admin`/`secret` như CODE_LAB).

| Trường hợp | Kết quả |
|---|---|
| Sai mật khẩu | 401 `Invalid credentials` |
| Đúng mật khẩu | 200, trả `access_token` (đã che khi dán vào bài) |
| `/ask` không token | **401**, header `www-authenticate: Bearer` |
| `/ask` token giả `abc.def.ghi` | 403 `Invalid token.` |
| `/ask` token đúng | **200**, `requests_remaining: 9` |

Decode payload token: `{'sub': 'student', 'role': 'user', 'iat': ..., 'exp': ...}`, `exp − iat = 3600 s`. JWT chỉ được ký, không mã hoá.

### Bước 3 — Exercise 4.3: Rate limit

Vòng lặp 20 request với token student: request 1–9 trả **200** (`requests_remaining` giảm 8 → 0), request 10–20 trả **429** (tổng 10 request thành công tính cả request ở bước 2 = đúng limit 10/phút). Response 429 có header `retry-after: 61`, `x-ratelimit-limit: 10`, `x-ratelimit-remaining: 0`.

Thêm: token `teacher` (admin) gửi 15 request đều 200 (limit 100/phút); `/admin/stats` bằng token student → 403, teacher → 200; `question` rỗng → 422.

Thuật toán: sliding window log (deque timestamp mỗi user, cửa sổ 60 s), lưu trong RAM.

### Bước 4 — Exercise 4.4: Cost guard

Đọc `production/cost_guard.py` (in-memory, $1/ngày/user → 402, $10/ngày toàn hệ thống → 503). Tự viết `check_budget(user_id, estimated_cost)` theo đề ($10/tháng, Redis, reset đầu tháng) trong một **script thử ở scratchpad** (không sửa code của đề), dùng Lua script để đọc + so sánh + cộng nguyên khối (tránh race khi nhiều instance).

```bash
docker run -d --rm --name p4-redis -p 6390:6379 redis:7-alpine
pip install redis
python p4_cost_guard.py redis://localhost:6390/0
docker stop p4-redis
```

Kết quả: mỗi request $1.8, request 1–5 OK (tổng $9.00), request 6–7 bị chặn (402), tổng giữ $9.00; key `budget:student:2026-11` TTL 2 764 800 s (32 ngày); user `teacher` không bị ảnh hưởng.

### Phát hiện thêm

- **Bản develop trả 403 khi sai key**, còn script chấm Part 6 yêu cầu **401 cho cả thiếu và sai key**. **Ghi nhớ cho CP5** (`06-lab-complete/app/auth.py`).
- `retry_after_seconds` luôn ra 61 thay vì ≤ 60 do `int(...) + 1`.
- Response `/ask` có `budget_remaining_usd` nhưng giá trị là số **đã dùng** (`usage.total_cost_usd`); `/me/usage` mới cho số còn lại đúng (`0.999802`).
- Rate limiter và cost guard của bản này lưu trong RAM: nhiều instance thì đếm riêng, restart là mất. Part 6 phải dùng Redis (script chấm kiểm state còn sau khi restart).

### Lỗi gặp phải và cách xử lý

| Lỗi | Xử lý |
|---|---|
| Bản develop và production đều `reload=True` nên có 2 process | Tắt bằng `pkill -TERM -P <pid>` rồi `kill -TERM <pid>` để tắt cả reloader lẫn worker |
| Token không được lộ khi dán vào bài | Lọc output qua `sed` thay `eyJ...` thành `eyJ***MASKED***` |

### Kết quả CP3

- [x] `MISSION_ANSWERS.md` mục Part 4: output `curl -i` các trường hợp 401, 403, 200, 429 (đã che token); giải thích JWT flow, thuật toán rate limit; cách làm cost guard kèm code và kết quả chạy với Redis.
- [x] Tự kiểm tra: thấy 429 bằng vòng lặp curl của chính mình (từ request thứ 11).
- [x] Đã tắt server, dừng container Redis tạm; cổng 8000 trống.

---

## CP4 — Scaling & Reliability / Part 5 (2026-11-26)

**Mục tiêu:** chạy nhiều instance mà không mất state, tắt không cắt ngang request.
**Thư mục:** `05-scaling-reliability/`. Làm theo lưu ý K5 số 7.

### Bước 1 — Exercise 5.1: health check (`develop/`)

Bản develop đã có sẵn `/health` và `/ready`, chỉ chạy và đọc code.

```bash
cd 05-scaling-reliability/develop
pip install -r requirements.txt     # có psutil
python app.py
curl http://localhost:8000/health   # 200, có check memory
curl http://localhost:8000/ready    # 200, in_flight_requests
curl -X POST "http://localhost:8000/ask?question=hello"   # 200, ~2.8 s (mock delay 3 s)
```

### Bước 2 — Exercise 5.2: graceful shutdown

Gửi 2 request `/ask` song song → sau 0.5 s `kill -TERM <PID>` → sau 0.3 s gửi request thứ 3.

| Request | Kết quả |
|---|---|
| req1, req2 (đang chạy khi SIGTERM) | **200**, mỗi cái 5.7 s |
| req3 (gửi sau SIGTERM) | Không được nhận (HTTP 000, curl exit 56) |
| Process | Thoát với **exit code 0** |

Log thấy thứ tự: `Shutting down` → 2 dòng `200 OK` → `Graceful shutdown initiated` → `Shutdown complete` → `Finished server process`.

### Bước 3 — Exercise 5.3: stateless (`production/app.py`)

Đọc code: session lưu `SETEX session:<id> 3600 <json>` trong Redis. Thí nghiệm ngược: chạy 2 instance `uvicorn app:app --port 8001/8002` với `REDIS_URL` trỏ tới cổng không có Redis (app tự rơi về in-memory). Tạo session ở 8001 → đọc history ở 8002 trả **404**.

### Bước 4 — Exercise 5.4: load balancing

```bash
cd 05-scaling-reliability/production
touch .env.local                    # bị .gitignore chặn
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

- 5 container: agent-1/2/3 (healthy), nginx (8080), redis.
- 6 request liên tiếp: `X-Served-By` lần lượt `.3 → .4 → .5 → .3 → .4 → .5` (round-robin).
- 10 request, đếm trong `docker compose -p k5-day14-scaling logs agent`: agent-1: 3, agent-2: 4, agent-3: 3.

### Bước 5 — Exercise 5.5: test stateless

```bash
python test_stateless.py
```

5 câu cùng session, được cả 3 instance phục vụ luân phiên; history đọc lại đủ 10 message.

Thí nghiệm thêm (script không tự làm): tạo session → `docker stop k5-day14-scaling-agent-2` → gửi thêm 6 câu: đều **200**, chỉ agent-1 và agent-3 phục vụ, history đủ 7 câu (14 message), TTL key Redis 3599 s. `docker start` lại agent-2 → sau > 10 s agent-2 nhận traffic trở lại với `INSTANCE_ID` mới (`instance-5f18d3`).

```bash
docker compose -p k5-day14-scaling down
```

### Phát hiện thêm

- `develop/app.py`: endpoint `async def` gọi `time.sleep(3)` đồng bộ nên **chặn event loop**, 2 request "song song" thực ra chạy nối tiếp (5.7 s). **Ghi nhớ cho CP5:** endpoint gọi hàm chặn nên khai báo `def` thường.
- `production/app.py`: trường `turn` lệch +1; `append_to_history` là read-modify-write (có thể mất message nếu 2 request đồng thời cùng session); không có Redis thì âm thầm rơi về in-memory.
- Nginx giữ instance chết ngoài vòng chia trong `fail_timeout` (10 s mặc định) sau khi nó sống lại.
- **Ghi nhớ cho CP5:** `/health` không phụ thuộc Redis (luôn 200), `/ready` ping Redis (503 khi mất Redis), giống `production/app.py` của Part 5.

### Lỗi gặp phải và cách xử lý

| Lỗi | Xử lý |
|---|---|
| Đoạn Python đọc header `X-Served-By` từ `curl -D -` báo `IndexError` | Đổi sang `curl -i` rồi `tr -d '\r'` và `grep -i '^x-served-by'` |

### Kết quả CP4

- [x] `MISSION_ANSWERS.md` mục Part 5: health/ready, graceful shutdown có log, stateless có thí nghiệm in-memory 404, load balancing có phân bố request, output `test_stateless.py` kèm giải thích, thí nghiệm tắt 1 instance.
- [x] Tự kiểm tra: đã chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` + `python test_stateless.py` và giải thích kết quả; đã `down`.

---

## CP5 — Final Project / Part 6 (2026-11-26)

**Mục tiêu:** sửa hết `TODO` trong `06-lab-complete/` tới khi `check_production_ready.py` báo `PASS 12/12`.
**Thư mục:** `06-lab-complete/` (làm ngay tại đây, theo lưu ý K5 số 1). Không sửa `check_production_ready.py`.

### Bước 1 — Đọc yêu cầu và mốc xuất phát

Đọc `06-lab-complete/README.md` (bảng *Script chấm dựa vào những tiêu chí dưới đây*), CODE_LAB Part 6 và **toàn bộ `check_production_ready.py`** để biết chính xác script kiểm gì:
- chạy `uvicorn app.main:app --workers 2` với `ENVIRONMENT=staging`, API key ngẫu nhiên, `RATE_LIMIT_PER_MINUTE=5`;
- restart agent để kiểm state rate limit nằm trong Redis;
- trỏ `REDIS_URL` tới cổng chết để kiểm `/ready` 503;
- đặt budget `0.000001` để kiểm 402;
- SIGTERM khi đang có request;
- build image, đo size, `docker stop` phải exit 0 trong < 10 s.

```bash
cd 06-lab-complete
pip install -r requirements.txt
python check_production_ready.py --static-only    # 0/12 tiêu chí · 5/24 checks
```

### Bước 2 — Viết code theo thứ tự gợi ý

`config.py` → `redis_client.py` → `auth.py` → `rate_limiter.py` → `cost_guard.py` → `main.py` (log JSON, `/health`, `/ready`, nối `/ask`, exception handler, lifespan) → `Dockerfile` → `.dockerignore` → `docker-compose.yml` → `.env.example` → `railway.toml` + `render.yaml`. Chi tiết từng file: bảng trong MISSION_ANSWERS Part 6.

Áp dụng các ghi nhớ từ CP1–CP4:
- CP1: `logging.basicConfig(..., force=True)`.
- CP2: formatter `json.dumps` cả dòng log, không ghép chuỗi.
- CP3: sai key trả **401** (không phải 403); rate limit + cost guard lưu Redis, không lưu RAM.
- CP4: `/health` không phụ thuộc Redis, `/ready` ping Redis; endpoint `/ask` là `def` thường để `time.sleep` không chặn event loop.

### Bước 3 — Chạy script chấm

| Lần | Lệnh | Kết quả |
|---|---|---|
| 1 | `--static-only` (bản khung) | 0/12 · 5/24 checks |
| 2 | `--skip-docker` | 10/12 · 39/39 checks (2 mục ⚠️ cần Docker) |
| 3 | đầy đủ | **PASS 12/12 · 43/43 checks · exit code 0** |

Số đo trong lần chạy đầy đủ: image 63 MB; 429 sau 5 request; restart vẫn 429; 15 dòng log JSON; SIGTERM giữa request → 200, exit 0; `docker stop` 1.3 s, exit 0.

### Bước 4 — Test bằng tay qua Docker Compose

```bash
# .env tạm với AGENT_API_KEY ngẫu nhiên (gitignore, xoá sau khi test)
docker compose -p k5-day14-final up -d --build
# ... các lệnh curl, xem MISSION_ANSWERS Part 6
docker compose -p k5-day14-final down -v
```

Kết quả: thiếu/sai key → 401; đúng key → 200; body sai (rỗng, thiếu field, JSON hỏng, > 2000 ký tự) → 422; quá 10 request/phút → 429 kèm `Retry-After`; `docker compose restart agent` vẫn 429; dừng Redis → `/health` 200, `/ready` 503, `/ask` 503 (không lộ stack trace), bật lại → `/ready` 200; container chạy uid 999, PID 1 là uvicorn; log không chứa API key; `docker stop` 1.34 s, exit 0.

Đánh dấu `[x]` 12 mục *Checklist Deliverable* trong `06-lab-complete/README.md`.

### Phát hiện thêm

- Cost guard báo 402 ngay request thứ 1 trong bài test của script, vì các lần chạy trước trong cùng Redis tạm đã cộng chi phí vượt 0.000001 USD. Đúng hành vi: budget là tổng chung theo ngày.
- Khi Redis bị dừng, `/ask` mất ~8 s mới trả 503 (chờ timeout kết nối/DNS). Có thể cải thiện bằng circuit breaker.
- `docker images` báo image Part 6 là 286 MB (dung lượng trên đĩa của Docker Desktop), còn `docker image inspect` (script chấm dùng) là 63 MB; cả hai đều < 500 MB.

### Lỗi gặp phải và cách xử lý

| Lỗi | Nguyên nhân | Xử lý |
|---|---|---|
| Lần chạy đầy đủ đầu tiên bị cắt giữa chừng, Redis tạm báo `docker run redis thất bại` | Pipe output qua `tee ... \| head -30`: `head` đóng pipe sớm làm script bị ngắt | Chạy lại, ghi toàn bộ output vào file `/tmp/check_full.txt` rồi mới đọc → PASS 12/12 |
| Lo ngại comment cùng dòng trong `.env.example` (`ENVIRONMENT=development  # ...`) bị đọc thành giá trị | Không phải parser `.env` nào cũng bỏ comment cùng dòng | Chuyển comment lên dòng riêng |
| `render.yaml` dùng `rootDir` + đường dẫn tương đối dễ hiểu nhầm gốc | File nằm trong thư mục con | Dùng `dockerfilePath: ./06-lab-complete/Dockerfile`, `dockerContext: ./06-lab-complete` (tính từ gốc repo) |

### Kết quả CP5

- [x] `python check_production_ready.py` (đầy đủ, có Docker, trong WSL) → **`PASS 12/12`**.
- [x] Dán phần "📋 Checklist Deliverable" vào `MISSION_ANSWERS.md` mục Part 6.
- [x] Không sửa `check_production_ready.py`; không commit `.env` (đã xoá file `.env` tạm).
- [x] Đã `down -v` stack `k5-day14-final`; script chấm tự dọn container/image tạm.
