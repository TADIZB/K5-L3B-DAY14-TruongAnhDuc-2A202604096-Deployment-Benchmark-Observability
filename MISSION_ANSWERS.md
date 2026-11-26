# Day 14 Lab - Mission Answers

> Môi trường chạy: WSL2 Ubuntu, Python 3.12.3 (`os.name` = `posix`), Docker 28.1.1, Docker Compose v2.35.1.
> Mọi output bên dưới là output thật từ máy, chạy ngày 2026-11-26.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong `01-localhost-vs-production/develop/app.py`:

| # | Anti-pattern | Dòng code | Hậu quả |
|---|---|---|---|
| 1 | **Hardcode secret** | L17 `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`, L18 `DATABASE_URL = "postgresql://admin:password123@..."` | Push lên GitHub là lộ key và mật khẩu DB; nằm vĩnh viễn trong lịch sử git, muốn đổi phải sửa code và deploy lại |
| 2 | **Log ra secret** | L34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | Key xuất hiện trong log server (đã thấy thật khi chạy, xem Exercise 1.2), ai đọc được log là lấy được key |
| 3 | **Config cứng, không đọc env** | L21-22 `DEBUG = True`, `MAX_TOKENS = 500` | Không đổi được giữa dev / staging / production nếu không sửa code (vi phạm 12-factor "Config") |
| 4 | **Dùng `print()` thay vì logging** | L33, L34, L38 | Không có level, không có timestamp, không phải JSON nên log aggregator (Loki, Datadog...) không parse/lọc được; in cả nội dung câu hỏi và câu trả lời |
| 5 | **Không có health check** | Không có `/health`, `/ready` (gọi thử `GET /health` → 404) | Platform (Railway, Render, K8s) không biết app còn sống hay đã treo để restart; load balancer không biết lúc nào nên gửi traffic |
| 6 | **Bind `localhost`** | L51 `host="localhost"` | Trong container chỉ nhận kết nối từ chính container, từ ngoài vào không được. Production phải bind `0.0.0.0` |
| 7 | **Port cố định** | L52 `port=8000` | Railway/Render inject `PORT` qua env; app không đọc nên platform không route được vào app |
| 8 | **`reload=True`** | L53 | Chế độ dev: tốn tài nguyên theo dõi file, tự restart khi file đổi; không dùng cho production |
| 9 | **Không xử lý shutdown** | Không có lifespan / xử lý SIGTERM | Khi platform tắt/redeploy, không có bước dọn dẹp (đóng kết nối, đánh dấu not-ready) |
| 10 | **Không validate input** | L31 `question: str` qua query string | Câu hỏi nằm trên URL (dễ bị ghi vào access log, proxy log); không giới hạn độ dài |

### Exercise 1.2: Chạy basic version

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
```

Theo lưu ý K5 số 3, bản develop nhận `question` qua **query**, không phải JSON:

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Log server, **thấy rõ secret bị in ra**:

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [2115] using WatchFiles
Starting agent on localhost:8000...
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:33232 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Quan sát:** app chạy được, nhưng chưa sẵn sàng cho production: lộ key trong log, không có `/health`, chỉ nghe `localhost`, port cứng, bật reload.

### Exercise 1.3: Comparison table

Chạy bản production:

```bash
cd ../production
cp .env.example .env      # .env đã nằm trong .gitignore, không commit
pip install -r requirements.txt
python app.py
```

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":...,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:37:12.727201+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is deploy?"}'
HTTP/1.1 200 OK
{"question":"What is deploy?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}
```

Thử thêm 3 thí nghiệm để kiểm chứng bảng so sánh:

```text
# 1. Config từ env: đổi PORT và ENVIRONMENT mà không sửa code
$ PORT=9000 ENVIRONMENT=staging python app.py
$ curl http://localhost:9000/health
{"status":"ok","uptime_seconds":3.6,"version":"1.0.0","environment":"staging",...}

# 2. Fail fast: production mà thiếu AGENT_API_KEY thì không cho khởi động
$ ENVIRONMENT=production python app.py
ValueError: AGENT_API_KEY must be set in production!

# 3. Graceful shutdown: gửi SIGTERM ngay khi đang có 1 request /ask (mock LLM mất ~0.1s)
in-flight request HTTP 200
process exit code: 0
INFO:     127.0.0.1:37404 - "POST /ask HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [2306]
```

| Feature | Develop (basic) | Production (advanced) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | `config.py` đọc env (`HOST`, `PORT`, `DEBUG`, `ENVIRONMENT`, `MAX_TOKENS`...), có `.env.example` | Một bản build chạy được ở mọi môi trường, chỉ đổi biến môi trường; đã thử `PORT=9000 ENVIRONMENT=staging` không cần sửa code |
| Secrets | `OPENAI_API_KEY = "sk-..."`, mật khẩu DB trong code, còn in key ra log | `os.getenv("OPENAI_API_KEY")`, `AGENT_API_KEY`; không log secret, chỉ log độ dài câu hỏi | Secret không nằm trong git, đổi key không cần deploy lại code; log không làm lộ key |
| Validate config | Không có | `Settings.validate()` dừng app nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` | Fail fast lúc khởi động tốt hơn là chạy với cấu hình sai rồi lỗi lúc có traffic |
| Host / Port | `localhost:8000` cố định | `0.0.0.0`, port từ `PORT` | Container và cloud cần bind `0.0.0.0` và nghe đúng port mà platform inject |
| Health check | Không có (`/health` → 404) | `GET /health` (liveness, có uptime) và `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform dựa vào `/health` để restart app treo, load balancer dựa vào `/ready` để chỉ gửi traffic vào instance đã sẵn sàng |
| Logging | `print()` text thường, in cả secret | `logging` với format JSON, log theo event (`agent_request`, `agent_response`), không log secret | Log JSON parse và lọc được trong log aggregator; có level và timestamp |
| Shutdown | Đột ngột, không có lifecycle | `lifespan` (startup/shutdown) + handler SIGTERM; uvicorn chờ request đang chạy xong | Khi redeploy/scale down, request đang xử lý vẫn trả 200 (đã thử: SIGTERM giữa request → 200, exit code 0) |
| Reload / Debug | `reload=True` luôn bật | `reload` chỉ bật khi `DEBUG=true` | Production không nên tự restart khi file đổi, tốn tài nguyên |
| Input | `question` qua query string | Body JSON, thiếu `question` → 422 có thông báo rõ | Không để câu hỏi lộ trên URL/access log; báo lỗi rõ cho client |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ cho phép frontend được cấu hình gọi API |

**Hai điểm tôi tự phát hiện khi chạy bản production** (bản production vẫn chưa hoàn hảo):

1. **Log JSON của app không hiện ra.** `config.py` gọi `logging.warning(...)` lúc import (dòng `settings = Settings().validate()`), trước khi `app.py` chạy `logging.basicConfig(...)`. Lệnh `logging.warning` đã tự cấu hình root logger với format mặc định và level WARNING, nên `basicConfig` sau đó không có tác dụng. Kết quả: log chỉ có `WARNING:root:OPENAI_API_KEY not set — using mock LLM`, các dòng `logger.info(json.dumps(...))` bị bỏ. Cách sửa: gọi `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`. Ở Part 6 cần chú ý điểm này vì script chấm yêu cầu mỗi dòng log là JSON.
2. **`.env` không được nạp tự động.** `requirements.txt` có `python-dotenv` nhưng code không gọi `load_dotenv()`, nên sửa file `.env` không có tác dụng; config chỉ lấy từ biến môi trường thật của shell (hoặc do platform/Docker inject).

### Checkpoint 1 — Tự kiểm tra

- **Vì sao hardcode secret nguy hiểm:** secret đi theo code vào git, ai có quyền đọc repo (hoặc repo public) đều thấy; xoá file không xoá được khỏi lịch sử commit; bot quét GitHub tìm key chỉ trong vài phút. Ở bản develop còn tệ hơn: key bị in vào log (`develop/app.py` L34).
- **Cách dùng env vars:** đọc bằng `os.getenv("TÊN", "mặc định")` tập trung trong `config.py`; liệt kê trong `.env.example` (commit được), giá trị thật đặt ở `.env` (gitignore) hoặc trên dashboard của platform.
- **Vai trò health check:** liveness (`/health`) trả lời "process còn sống không", sai thì platform restart; readiness (`/ready`) trả lời "đã nhận traffic được chưa", sai thì load balancer tạm không gửi request vào.
- **Graceful shutdown:** khi nhận SIGTERM, ngừng nhận request mới, chờ request đang chạy xong, dọn dẹp (đóng kết nối), rồi thoát với exit code 0.
- **Một anti-pattern develop đã được production sửa, kèm dòng code:** develop `app.py` L17 `OPENAI_API_KEY = "sk-hardcoded-..."` và L34 in key ra log → production `config.py` `openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))`, và `app.py` L111-115 chỉ log `question_length`, `client_ip`.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ (Debian kèm compiler, header, công cụ build). Chạy trong container thấy `Python 3.11.18`.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong thư mục này; xem bằng `docker exec` thấy `/app` có `app.py`, `requirements.txt`, `utils/`.
3. **Tại sao `COPY requirements.txt` trước:** Docker cache từng layer, và một layer bị build lại thì mọi layer phía sau cũng build lại. `requirements.txt` ít khi đổi, còn code đổi liên tục. Copy `requirements.txt` rồi `RUN pip install` trước khi copy code thì khi chỉ sửa `app.py`, layer `pip install` (53.3 MB theo `docker history`) vẫn được dùng lại từ cache, build chỉ mất vài giây. Nếu `COPY . .` trước thì mỗi lần sửa code đều phải cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT:**
   - `CMD ["python", "app.py"]` là lệnh **mặc định**, bị thay thế hoàn toàn nếu truyền lệnh khi chạy (`docker run my-agent:develop python -c "print(1)"` sẽ chạy `python -c ...` thay cho `app.py`).
   - `ENTRYPOINT` là phần **cố định** của lệnh; tham số truyền vào `docker run` (hoặc `CMD`) được **nối thêm** vào sau. Muốn đổi phải dùng cờ `--entrypoint`.
   - Thường dùng `ENTRYPOINT` cho chương trình chính và `CMD` cho tham số mặc định. Dockerfile này chỉ có `CMD`.

### Exercise 2.2: Build và run

Build từ **gốc repo** (lưu ý K5 số 4), vì Dockerfile `COPY` theo đường dẫn tính từ gốc:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name p2-develop -p 8000:8000 my-agent:develop
```

Bản develop nhận `question` qua query (lưu ý K5 số 3):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.3,"container":true}

$ docker ps --filter name=p2-develop
p2-develop my-agent:develop Up 5 seconds 0.0.0.0:8000->8000/tcp

$ docker exec p2-develop sh -c 'whoami; python --version'
root
Python 3.11.18
```

Container develop chạy bằng user **root**: nếu app bị khai thác, kẻ tấn công có quyền root trong container.

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev` để build package cần compile, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này chỉ để build, không deploy.
- **Stage 2 (`runtime`):** bắt đầu lại từ `python:3.11-slim` sạch, tạo user `appuser` (non-root), chỉ `COPY --from=builder /root/.local /home/appuser/.local` (40.8 MB theo `docker history`) cùng `main.py` và `utils/mock_llm.py`, chuyển sang `USER appuser`, có `HEALTHCHECK`, chạy `uvicorn main:app --workers 2`.
- **Tại sao image nhỏ hơn:**
  1. Base `python:3.11-slim` thay cho `python:3.11` đầy đủ (bản đầy đủ có sẵn gcc, header, nhiều thư viện hệ thống).
  2. `gcc`, `libpq-dev`, cache apt ở stage builder **bị bỏ lại**, không vào image cuối; image cuối chỉ có kết quả đã cài.
  3. Kiểm chứng: trong container advanced `which gcc` → `no gcc`.

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

```text
$ docker images my-agent
REPOSITORY   TAG        IMAGE ID       CREATED          SIZE
my-agent     advanced   cb1128297398   3 seconds ago    240MB
my-agent     develop    22dae7496376   43 seconds ago   1.67GB
```

**Image size comparison** (số đo bằng `docker images` trên máy tôi):

- Develop: **1670 MB** (1.67 GB)
- Production (advanced): **240 MB**
- Difference: (1670 − 240) / 1670 = **85.6 %** nhỏ hơn (develop gấp ~7 lần)

> Ghi chú: Docker Desktop (containerd image store) cho `docker images` là dung lượng chiếm trên đĩa. `docker image inspect --format '{{.Size}}'` cho dung lượng nén: develop 426 319 939 bytes (~426 MB), advanced 57 409 145 bytes (~57 MB), cũng giảm ~86.5 %.

Chạy thử container advanced:

```text
$ docker run -d --name p2-adv -p 8000:8000 my-agent:advanced
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ docker ps --filter name=p2-adv --format '{{.Names}} {{.Status}}'
p2-adv Up 9 seconds (healthy)        ← HEALTHCHECK hoạt động

$ docker exec p2-adv sh -c 'whoami; which gcc || echo "no gcc"'
appuser
no gcc
```

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

Theo lưu ý K5 số 5 và 7: tạo `.env.local` rỗng (đã kiểm `git check-ignore`: bị `.gitignore` chặn), bật stack với tên project riêng:

```bash
cd 02-docker/production
touch .env.local
docker compose -p k5-day14-docker up -d --build
```

**Architecture diagram:**

```text
                      Máy host (localhost)
                             │  cổng 80 / 443
                             ▼
               ┌──────────────────────────────┐
               │ nginx (nginx:alpine)         │  reverse proxy, rate limit 10 r/s/IP
               │ ports 80:80, 443:443         │  (burst 20), security headers
               └──────────────┬───────────────┘
                              │ proxy_pass http://agent:8000
   ┌──────────────────────────┼──────────── network "internal" (bridge) ─────┐
   │                          ▼                                              │
   │            ┌──────────────────────────┐                                 │
   │            │ agent (build Dockerfile, │  uvicorn main:app, 2 workers    │
   │            │ target: runtime) :8000   │  không mở port ra host          │
   │            └──────┬────────────┬──────┘                                 │
   │   REDIS_URL       │            │  QDRANT_URL                            │
   │ redis://redis:6379│            │  http://qdrant:6333                    │
   │                   ▼            ▼                                        │
   │     ┌──────────────────┐  ┌─────────────────────┐                       │
   │     │ redis:7-alpine   │  │ qdrant/qdrant:v1.9.0│                       │
   │     │ :6379, volume    │  │ :6333, volume       │                       │
   │     │ redis_data       │  │ qdrant_data         │                       │
   │     └──────────────────┘  └─────────────────────┘                       │
   └─────────────────────────────────────────────────────────────────────────┘
   Thứ tự khởi động: redis, qdrant (chờ healthy) → agent (chờ healthy) → nginx
```

**Services nào được start:** 4 service: `nginx`, `agent`, `redis`, `qdrant`.

```text
$ docker compose -p k5-day14-docker ps
NAME                       IMAGE                   SERVICE   STATUS                    PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up 4 seconds (healthy)    8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up 4 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up 15 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up 15 seconds (healthy)   6379/tcp
```

**Chúng communicate thế nào:**
- Cả 4 service cùng network bridge `internal` (`k5-day14-docker_internal`). Docker có DNS nội bộ nên gọi nhau bằng **tên service**: từ trong agent, `redis` → `172.21.0.3`, `qdrant` → `172.21.0.2`.
- Chỉ **nginx** mở port ra host (80, 443). Client → nginx → `proxy_pass http://agent_backend` (`agent:8000`). Agent không mở port: gọi thẳng `http://localhost:8000/health` từ host không kết nối được (`000`).
- Agent nhận địa chỉ Redis và Qdrant qua biến môi trường `REDIS_URL`, `QDRANT_URL`.
- `depends_on` + `condition: service_healthy`: agent chỉ khởi động khi redis và qdrant đã healthy (log compose thấy `qdrant-1 Healthy`, `redis-1 Healthy` rồi mới `agent-1 Starting`).

**Kết quả test qua Nginx:**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":11.9,"version":"2.0.0","timestamp":"2026-11-26T07:52:41.089604"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Header `Server: nginx` và các security header chứng tỏ request đi qua Nginx. Thêm thí nghiệm: gửi **40 request `/ask` song song** → **28 lần 200, 12 lần 429**: Nginx `limit_req` (10 r/s, burst 20) chặn phần vượt.

Dọn stack: `docker compose -p k5-day14-docker down -v`.

### Checkpoint 2 — Tự kiểm tra

- **Cấu trúc Dockerfile:** `FROM` (base) → `WORKDIR` → `COPY requirements` + `RUN pip install` (layer ít đổi) → `COPY` code (layer hay đổi) → `EXPOSE` → `USER` → `HEALTHCHECK` → `CMD`.
- **Lợi ích multi-stage:** image nhỏ hơn 85.6 %, không chứa compiler/build tool (giảm bề mặt tấn công), chạy non-root, pull/deploy nhanh hơn.
- **Compose orchestration:** một file khai báo nhiều service, network nội bộ có DNS theo tên service, volume giữ dữ liệu, `depends_on` + healthcheck điều khiển thứ tự khởi động.
- **Debug container:** `docker ps` (trạng thái, healthy), `docker logs <container>` / `docker compose -p <project> logs agent`, `docker exec -it <container> sh` (đã dùng để xem user, file, DNS), `docker history <image>` (dung lượng từng layer).
- **Quan sát thêm:** log của agent trong stack có dạng `{"time":...,"msg":"{"event": "request", "q_len": 2}"}`: JSON lồng trong chuỗi mà không escape dấu `"`, nên dòng log này **không phải JSON hợp lệ**. Ở Part 6 cần tạo log bằng formatter `json.dumps` cho cả dòng, không ghép chuỗi bằng format string.

## Part 3: Cloud Deployment

> Theo CHECKPOINTS (CP6), lớp K5 deploy **chính agent Part 6** (`06-lab-complete/`), không deploy app mẫu trong `03-cloud-deployment/`. Chi tiết đầy đủ: [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.1: Railway deployment (nền tảng chính)

- **URL:** https://agent-production-7dc48df9.up.railway.app
- **Project:** `day14-agent` trên Railway, 2 service: `agent` (build từ `Dockerfile` theo `railway.toml`) + `Redis` (database template, private network `redis.railway.internal`).
- **Biến môi trường** đặt trên Railway, không ghi trong code: `AGENT_API_KEY` (sinh ngẫu nhiên, đặt qua `--stdin`), `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`, `LOG_LEVEL=INFO`. `PORT` do Railway tự cấp.
- **Screenshot:** [dashboard](screenshots/dashboard.png) · [service running](screenshots/running.png) · [test](screenshots/test.png)

Các lệnh đã chạy (trong `06-lab-complete/`): `railway init --name day14-agent` → `railway add --database redis` → `railway add --service agent` → `railway variable set ...` → `railway up --service agent --ci` → `railway domain --service agent`.

4 lệnh tự kiểm của CP6:

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     → 200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      → 200
$ curl ... -X POST "$BASE/ask" (không key)                     → 401
$ curl ... -X POST "$BASE/ask" -H "X-API-Key: $AGENT_API_KEY"  → 200
```

Thêm: trên cloud gửi 12 request liên tiếp → `200 ×8, 429 ×4` (tính cả 2 request trước đó là đúng 10 request/phút), `retry-after: 42`. Script chấm kèm `--public-url` → `✅ Public URL: GET .../health → 200`, **12/12 · 44/44 checks**.

**Xem log trên cloud:** `railway logs --service agent`. Railway tự đọc log JSON của app thành các field (`event`, `path`, `status`, `ms`...), lọc được ngay trên dashboard.

### Exercise 3.2: So sánh `railway.toml` với `render.yaml` (nền tảng còn lại)

Tôi viết cả hai file trong `06-lab-complete/` (cả hai đều được script chấm kiểm ✅). Chỉ deploy thật lên Railway; Render dùng phần so sánh này.

| Khía cạnh | `railway.toml` | `render.yaml` | Vì sao khác |
|---|---|---|---|
| Phạm vi | Cấu hình **1 service** (service mà thư mục đang link tới) | **Blueprint** khai báo **cả hạ tầng**: web service + Key Value (Redis) trong cùng file | Railway tạo service và database bằng CLI/dashboard (`railway add --database redis`), file chỉ nói cách build/chạy. Render theo hướng Infrastructure-as-Code: một file dựng toàn bộ stack |
| Định dạng | TOML, các bảng `[build]`, `[deploy]` | YAML, danh sách `services:` | Quy ước riêng của từng nền tảng |
| Cách build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, `dockerContext` | Tương đương nhau; Render cần chỉ rõ context vì file nằm trong thư mục con |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 60` | `healthCheckPath: /health` | Cùng mục đích: chỉ chuyển traffic sang bản deploy mới khi `/health` trả 200 |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Không khai báo (Render tự restart service crash) | Railway cho chỉnh chính sách restart trong file |
| Biến môi trường | **Không có trong file**: đặt bằng `railway variable set` hoặc dashboard | Khai báo trong `envVars` | Railway tách config ra khỏi code hẳn. Render khai báo ngay trong file nên phải có cơ chế riêng cho secret |
| Secret | Đặt qua CLI `--stdin`, không bao giờ nằm trong repo | `AGENT_API_KEY: generateValue: true` (Render tự sinh) hoặc `sync: false` (nhập tay trên dashboard), **không** ghi `value:` | File `render.yaml` được commit lên git, nên secret không được có giá trị thật |
| Kết nối Redis | Reference variable `REDIS_URL=${{Redis.REDIS_URL}}` đặt trên service | `fromService: {type: keyvalue, name: day14-redis, property: connectionString}` | Cả hai đều không hardcode URL Redis; nền tảng tự điền khi deploy |
| Vị trí file | Đọc từ thư mục chạy `railway up` (`06-lab-complete/`) | Mặc định đọc `render.yaml` ở **gốc repo**; vì nằm trong thư mục con nên phải chọn Blueprint Path `06-lab-complete/render.yaml` | Railway upload từ máy (CLI), Render kéo code từ GitHub |
| Cách deploy | `railway up` upload thư mục hiện tại từ máy | Push lên GitHub → Render tự build (`autoDeploy: true`) | Railway CLI-first, Render Git-first |
| PORT | Railway cấp `PORT`, Dockerfile nghe `${PORT:-8000}` | Render cũng cấp `PORT` (mặc định 10000) | Cùng một Dockerfile chạy được trên cả hai nhờ đọc `PORT` từ env |

Ghi chú: khi deploy, Railway CLI cảnh báo *"Config as Code (railway.json / railway.toml) is deprecated. Prefer Infrastructure as Code (.railway/railway.ts) ... Existing files keep working until 2026-12-01"*. Bài vẫn dùng `railway.toml` vì đề và script chấm yêu cầu file này.

### Exercise 3.3: Cloud Run CI/CD pipeline (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` là pipeline Cloud Build chạy khi push lên `main`, gồm 4 bước nối tiếp (`waitFor`):
1. **test:** trong `python:3.11-slim`, cài `requirements.txt` + `pytest` rồi chạy `pytest tests/`; test fail thì pipeline dừng, không build.
2. **build:** `docker build` image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push:** đẩy cả hai tag lên Container Registry.
4. **deploy:** `gcloud run deploy ai-agent` với image theo `$COMMIT_SHA` (biết chính xác commit nào đang chạy, rollback được) ở `asia-southeast1`: public, 1–10 instance, 512 Mi / 1 CPU, timeout 60 s, `ENVIRONMENT=production`, `OPENAI_API_KEY` lấy từ **Secret Manager** thay vì ghi trong file.

`service.yaml` là bản khai báo (IaC) của cùng service để `gcloud run services replace`: autoscale 1–10 instance, mỗi instance tối đa 80 request đồng thời, `AGENT_API_KEY` và `OPENAI_API_KEY` đọc từ Secret Manager, `livenessProbe` gọi `/health` mỗi 30 s, `startupProbe` gọi `/ready` trước khi nhận traffic. Ghi chú: thư mục mẫu này không có `tests/`, nên bước test sẽ không tìm thấy test nào nếu chạy nguyên trạng.

### Checkpoint 3 — Tự kiểm tra

- [x] Deploy thành công lên Railway, URL public hoạt động (4 lệnh ra 200/200/401/200).
- [x] Đặt biến môi trường trên cloud bằng `railway variable set` (secret qua `--stdin`), Redis nối bằng reference variable.
- [x] Xem log bằng `railway logs --service agent`.

## Part 4: API Security

> Token JWT trong các output dưới đây đã được che (`eyJ***MASKED***`). Header `date`, `server`, `content-length` lược bớt cho gọn.

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

**API key được check ở đâu?** Trong dependency `verify_api_key` (L39-54). Hàm đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` (L36) và so với `API_KEY = os.getenv("AGENT_API_KEY", ...)` (L35). Endpoint `/ask` gắn dependency bằng `_key: str = Depends(verify_api_key)` (L70), nên key được kiểm **trước khi** chạy code của endpoint. `/` và `/health` không gắn dependency nên vẫn public (platform cần gọi `/health`).

**Điều gì xảy ra nếu sai key?**
- Không gửi header → **401** `Missing API key...` (L44-48).
- Gửi key sai → **403** `Invalid API key.` (L49-53).
- Request không tới được LLM, không tốn tiền.
- Ghi chú cho Part 6: script chấm Part 6 yêu cầu **cả thiếu lẫn sai key đều trả 401**, nên ở `06-lab-complete/app/auth.py` không được trả 403 như bản này.

**Làm sao rotate key?** Key đọc từ biến môi trường `AGENT_API_KEY`, không nằm trong code, nên rotate không cần sửa code:
1. Sinh key mới, đặt lại `AGENT_API_KEY` trên platform (Railway/Render dashboard, hoặc `.env`).
2. Restart/redeploy service để process đọc giá trị mới.
3. Gửi key mới cho client; key cũ hết tác dụng ngay sau khi restart.

Muốn rotate không gián đoạn thì cho app nhận **nhiều key** cùng lúc (ví dụ `AGENT_API_KEYS=new,old`), chuyển client sang key mới rồi mới gỡ key cũ. Bản demo hiện chỉ nhận 1 key.

Test (chạy `AGENT_API_KEY=secret-key-123 python app.py`, theo lưu ý K5 số 6):

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -s -o /dev/null -w 'health HTTP %{http_code}\n' http://localhost:8000/health
health HTTP 200
```

Nhược điểm thấy được: `app.py` L91-92 in API key ra console khi khởi động, và giá trị mặc định `"demo-key-change-in-production"` khiến app vẫn chạy với key đoán được nếu quên đặt env.

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)

**JWT flow:**
1. Client `POST /auth/token` với `username`/`password`. `authenticate_user()` so với `DEMO_USERS` (sai → 401 `Invalid credentials`).
2. `create_token()` tạo payload `{sub, role, iat, exp = now + 60 phút}` và ký bằng **HS256** với `JWT_SECRET` (đọc từ env).
3. Client gửi `Authorization: Bearer <token>` ở mỗi request.
4. `verify_token()` kiểm chữ ký và hạn bằng `jwt.decode(...)`. Không có header → 401; token hết hạn → 401 `Token expired`; token giả hoặc sai chữ ký → 403 `Invalid token`. Hợp lệ thì trả `{username, role}` cho endpoint.
5. Server **không lưu session**: thông tin user và role nằm trong token, chỉ cần secret để verify (stateless, scale nhiều instance dễ).

Lưu ý: payload JWT chỉ được **ký**, không được **mã hoá**. Ai có token cũng đọc được nội dung bằng base64 (thử bên dưới), nên không để thông tin nhạy cảm trong token. Token cũng phải được giữ kín như mật khẩu.

Chạy bản production (tắt bản develop trước, dùng tài khoản `student` / `demo123` và endpoint `POST /auth/token` theo lưu ý K5 số 6):

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJ***MASKED***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ***MASKED***"}

# Decode phần payload của token (chỉ base64, không cần secret)
{'sub': 'student', 'role': 'user', 'iat': 1795679886, 'exp': 1795683486}      ← exp − iat = 3600 s = 60 phút

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ TOKEN="eyJ***MASKED***"
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** **Sliding Window Log** (docstring gọi là "Sliding Window Counter"). Mỗi user có một `deque` lưu timestamp các request. Mỗi lần check, bỏ các timestamp cũ hơn `now − 60 s`; nếu còn ≥ `max_requests` timestamp thì trả 429, ngược lại thêm `now` vào deque. Không phải token bucket: không có "token" hồi dần, chỉ đếm request trong 60 giây gần nhất.
- **Limit:** user thường **10 request / 60 giây** (`rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)`); admin **100 request / 60 giây** (`rate_limiter_admin`).
- **Bypass limit cho admin:** trong `app.py`, `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`. Role lấy từ JWT (do server ký, client không sửa được). Đăng nhập `teacher` / `teach456` (role `admin`) thì dùng limiter 100/phút: thử 15 request liên tiếp đều 200. Muốn bỏ hẳn limit cho admin thì bỏ qua `limiter.check()` khi `role == "admin"`, nhưng vẫn nên giữ một giới hạn cao để phòng token admin bị lộ.
- **Hạn chế:** state nằm trong RAM của process, nên chạy nhiều instance thì mỗi instance đếm riêng (limit thực tế nhân lên theo số instance), restart là mất. Part 6 phải lưu trong Redis.

Vòng lặp 20 lần bằng token của `student` (request đầu tiên đã dùng ở Exercise 4.2, nên vòng lặp bắt đầu với 9 lượt còn lại):

```text
$ for i in $(seq 1 20); do printf "Request %2d: " "$i"; curl -s -w ' [HTTP %{http_code}]' -X POST http://localhost:8000/ask \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; echo; done
Request  1: {"question":"Test 1","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":8,"budget_remaining_usd":3.5e-05}} [HTTP 200]
Request  2: {"question":"Test 2","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":7,"budget_remaining_usd":5.6e-05}} [HTTP 200]
Request  3: {... "requests_remaining":6 ...} [HTTP 200]
Request  4: {... "requests_remaining":5 ...} [HTTP 200]
Request  5: {... "requests_remaining":4 ...} [HTTP 200]
Request  6: {... "requests_remaining":3 ...} [HTTP 200]
Request  7: {... "requests_remaining":2 ...} [HTTP 200]
Request  8: {... "requests_remaining":1 ...} [HTTP 200]
Request  9: {"question":"Test 9","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":0,"budget_remaining_usd":0.000198}} [HTTP 200]
Request 10: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":61}} [HTTP 429]
Request 11: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":61}} [HTTP 429]
...
Request 20: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":61}} [HTTP 429]
```

Tổng cộng 10 request thành công (1 ở 4.2 + 9 trong vòng lặp), từ request thứ 11 bị **429**. Chi tiết một response 429:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "again"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795679946
retry-after: 61
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":61}}
```

Các kiểm tra thêm:

```text
# Admin (teacher): 15 request liên tiếp, limit 100/phút
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200

# Phân quyền theo role trong JWT
GET /admin/stats (token student)  → {"detail":"Admin only"} [HTTP 403]
GET /admin/stats (token teacher)  → {"total_users":"N/A (in-memory demo)","global_cost_usd":0.0004749,"global_budget_usd":10.0} [HTTP 200]

# Input validation (pydantic min_length=1)
POST /ask {"question": ""}        → string_too_short [HTTP 422]
```

### Exercise 4.4: Cost guard implementation

**Bản có sẵn trong `04-api-gateway/production/cost_guard.py`:**
- Ước tính token (mock: `số từ × 2`), tính tiền theo giá GPT-4o-mini ($0.15 / 1M input, $0.60 / 1M output).
- `check_budget()` chạy **trước** khi gọi LLM: tổng toàn hệ thống vượt $10/ngày → 503; user vượt $1/ngày → **402 Payment Required**; dùng ≥ 80 % → log warning.
- `record_usage()` chạy **sau** khi gọi LLM để cộng chi phí thật.
- Hạn chế: lưu trong dict ở RAM (mất khi restart, mỗi instance đếm riêng); response `/ask` có trường `budget_remaining_usd` nhưng thực ra trả `usage.total_cost_usd` (số **đã dùng**, không phải số còn lại): đúng ra `/me/usage` mới cho `budget_remaining_usd: 0.999802`.

**Cách tôi implement theo đề (budget $10/tháng mỗi user, lưu trong Redis, reset đầu tháng):**

```python
MONTHLY_BUDGET_USD = 10.0

# Lua chạy nguyên khối trong Redis: đọc + so sánh + cộng không bị race giữa nhiều instance
CHECK_AND_ADD = r.register_script("""
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])
if current + cost > budget then
  return {0, tostring(current)}
end
local new = redis.call('INCRBYFLOAT', KEYS[1], cost)
redis.call('EXPIRE', KEYS[1], 32 * 24 * 3600)
return {1, new}
""")

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    ok, _total = CHECK_AND_ADD(keys=[key], args=[estimated_cost, MONTHLY_BUDGET_USD])
    return bool(ok)
```

Cách hoạt động:
1. **Key theo user và theo tháng** `budget:<user_id>:YYYY-MM`. Sang tháng mới thì key mới bắt đầu từ 0, nên **tự reset đầu tháng** mà không cần cron. `EXPIRE` 32 ngày để Redis tự xoá key tháng cũ.
2. Nếu `đã dùng + chi phí ước tính > $10` → trả `False`, endpoint trả **402**; ngược lại cộng chi phí bằng `INCRBYFLOAT` và trả `True`.
3. Khác lời giải mẫu trong `CODE_LAB.md` (`GET` rồi mới `INCRBYFLOAT` ở 2 lệnh riêng): khi chạy nhiều instance, hai request đồng thời có thể cùng đọc một giá trị cũ rồi cùng được cho qua, làm vượt budget. Gói "đọc + so sánh + cộng" vào **một Lua script** thì Redis chạy nguyên khối, không bị race.
4. Dùng giờ **UTC** để mọi instance (có thể ở múi giờ khác nhau) đổi tháng cùng lúc.
5. Trong app thật: gọi `check_budget` với chi phí **ước tính** trước khi gọi LLM, sau khi có số token thật thì điều chỉnh chênh lệch (`INCRBYFLOAT` phần thừa/thiếu).

Kiểm thử với Redis thật (container `redis:7-alpine` tạm thời), mỗi request ước tính $1.8:

```text
request 1: cost $1.8 -> OK (200)  tổng đã dùng = $1.80
request 2: cost $1.8 -> OK (200)  tổng đã dùng = $3.60
request 3: cost $1.8 -> OK (200)  tổng đã dùng = $5.40
request 4: cost $1.8 -> OK (200)  tổng đã dùng = $7.20
request 5: cost $1.8 -> OK (200)  tổng đã dùng = $9.00
request 6: cost $1.8 -> VƯỢT BUDGET (402)  tổng đã dùng = $9.00
request 7: cost $1.8 -> VƯỢT BUDGET (402)  tổng đã dùng = $9.00
key: budget:student:2026-11 | TTL (giây): 2764800        ← 32 ngày
user khác không bị ảnh hưởng: True

$ redis-cli KEYS 'budget:*'
budget:student:2026-11
budget:teacher:2026-11
```

Request bị từ chối **không bị cộng tiền** (tổng giữ ở $9.00).

### Checkpoint 3 — Tự kiểm tra

- **Rate limit vs cost guard, vì sao cần cả hai:**
  - Rate limit bảo vệ **tốc độ**: chặn một client gửi quá nhiều request trong thời gian ngắn (spam, bot, vòng lặp lỗi), giữ cho server không quá tải và chia đều tài nguyên. Nhưng nó không biết request đắt hay rẻ.
  - Cost guard bảo vệ **tiền**: cộng dồn chi phí LLM thật theo ngày/tháng. Một user gửi đều 10 request/phút (không bao giờ dính 429) với prompt dài vẫn có thể đốt hết ngân sách sau vài ngày; chỉ cost guard mới chặn được (402).
  - Ngược lại cost guard không chặn được spam request rẻ làm nghẽn server. Hai lớp bổ sung cho nhau, thứ tự: auth (401) → rate limit (429) → validate (422) → cost (402) → LLM.
- **Thấy được 429 bằng vòng lặp curl của chính mình:** có, từ request thứ 11 trong 60 giây (output ở Exercise 4.3).

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

Bản develop đã có sẵn 2 endpoint, tôi đọc và chạy thử:

- `GET /health` (**liveness**, L104-144): luôn trả 200 khi process còn chạy. Kèm `uptime_seconds`, `version`, `environment` và check memory bằng `psutil` (`degraded` nếu dùng > 90 % RAM).
- `GET /ready` (**readiness**, L147-168): trả 503 khi `_is_ready = False` (chưa startup xong hoặc **đang shutdown**), ngược lại 200 kèm `in_flight_requests`.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:02:12.160331+00:00","checks":{"memory":{"status":"ok","used_percent":16.0}}} [HTTP 200]

$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1} [HTTP 200]      ← đếm cả chính request /ready đang chạy

$ curl -X POST "http://localhost:8000/ask?question=hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} [HTTP 200] time=2.843026s
```

Bản production (`production/app.py`) thì `/ready` thực sự ping Redis: `_redis.ping()` lỗi → **503** `Redis not available`. Đây là đúng mẫu cần làm ở Part 6 (`/ready` 503 khi mất Redis, `/health` vẫn 200).

### Exercise 5.2: Graceful shutdown

Cơ chế trong `develop/app.py`:
1. Middleware `track_requests` (L72-81) tăng/giảm `_in_flight_requests` cho mỗi request.
2. Uvicorn nhận SIGTERM → **đóng socket, ngừng nhận request mới**, chờ request đang chạy xong (`timeout_graceful_shutdown=30`).
3. Sau đó chạy phần shutdown của `lifespan` (L54-66): đặt `_is_ready = False` (`/ready` trả 503 để load balancer ngừng gửi traffic), chờ `_in_flight_requests == 0` tối đa 30 giây, rồi log `Shutdown complete`.
4. `handle_sigterm` (L175-183) chỉ log; uvicorn xử lý phần còn lại.

Test: gửi 2 request `/ask` song song (mock LLM mất ~3 s mỗi cái), 0.5 giây sau gửi `kill -TERM`, rồi 0.3 giây sau gửi thêm request thứ 3:

```text
-> kill -TERM 3500
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."} [req2 HTTP 200] time=5.695005s
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."} [req1 HTTP 200] time=5.695389s
 [req3 HTTP 000]  ← request mới sau SIGTERM không được nhận (curl exit 56, kết nối bị đóng)
process exit code: 0
```

Log server:

```text
INFO:     127.0.0.1:53920 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     127.0.0.1:53922 - "POST /ask?question=Long%20task%202 HTTP/1.1" 200 OK
INFO:     127.0.0.1:53932 - "POST /ask?question=Long%20task%201 HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 08:02:19,550 INFO 🔄 Graceful shutdown initiated...
2026-11-26 08:02:19,550 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [3500]
2026-11-26 08:02:19,550 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** request đang xử lý **hoàn thành** (cả 2 trả 200) dù SIGTERM đến giữa chừng; request mới bị từ chối; process thoát với **exit code 0**.

**Quan sát thêm:** mỗi request chỉ mất ~3 s nhưng cả hai đều mất 5.7 s. Nguyên nhân: `ask_agent` là `async def` nhưng gọi `ask()` có `time.sleep(3)` (hàm đồng bộ), làm **chặn event loop**, nên 2 request chạy nối tiếp thay vì song song. Sửa bằng cách khai báo endpoint là `def` thường (FastAPI tự chạy trong threadpool) hoặc dùng `await asyncio.sleep` / `run_in_threadpool`.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

Bản production đã stateless: toàn bộ session và history lưu trong Redis, không có biến toàn cục giữ state.
- `save_session()` → `SETEX session:<id> 3600 <json>` (TTL 1 giờ).
- `load_session()` → `GET session:<id>`.
- `append_to_history()` đọc session, thêm message, giữ tối đa 20 message, lưu lại.
- Instance nào nhận request cũng đọc/ghi cùng một Redis, nên **instance nào cũng phục vụ được user nào**.

**Tại sao state trong RAM hỏng khi chạy nhiều instance:** mỗi instance là một process riêng với bộ nhớ riêng. Load balancer chia request vòng tròn, nên request thứ 2 của cùng một user thường rơi vào instance khác, nơi không có dữ liệu của request 1. Ngoài ra state trong RAM mất khi instance restart, redeploy hoặc scale down.

Thí nghiệm chứng minh: chạy 2 instance của `production/app.py` trỏ `REDIS_URL` tới cổng không có Redis, nên app rơi về chế độ in-memory (`_memory_store`). Tạo session ở instance A (cổng 8001), đọc history ở instance B (cổng 8002):

```text
history trên instance A (8001):
{"session_id":"955d2bfc-38bc-4504-8c0a-3830f86bf148","messages":[{"role":"user","content":"What is Docker?", ...  [HTTP 200]
history trên instance B (8002):
{"detail":"Session 955d2bfc-38bc-4504-8c0a-3830f86bf148 not found or expired"} [HTTP 404]
```

Hạn chế còn lại của bản production: `append_to_history` là đọc rồi ghi đè (read-modify-write) nên 2 request đồng thời cùng session có thể ghi đè mất message của nhau. Dùng `RPUSH` + `LTRIM` (Redis list) sẽ an toàn hơn. Ngoài ra khi không có Redis, app âm thầm rơi về in-memory thay vì báo lỗi.

### Exercise 5.4: Load balancing

Theo lưu ý K5 số 7: stack mở cổng **8080**, endpoint **`POST /chat`**, chạy với `-p` riêng.

```bash
cd 05-scaling-reliability/production
touch .env.local                 # bị .gitignore chặn
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

```text
$ docker compose -p k5-day14-scaling ps
NAME                       IMAGE                    SERVICE   STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 9 seconds (healthy)    8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 9 seconds              0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 19 seconds (healthy)   6379/tcp
```

**3 agent instance được start.** Nginx phân tán request: header `X-Served-By` (Nginx thêm vào) và trường `served_by` (app trả về) cho thấy **round-robin** đều đặn:

```text
req 1: X-Served-By: 172.21.0.3:8000 served_by=instance-6f2e3e
req 2: X-Served-By: 172.21.0.4:8000 served_by=instance-b23b86
req 3: X-Served-By: 172.21.0.5:8000 served_by=instance-6e2188
req 4: X-Served-By: 172.21.0.3:8000 served_by=instance-6f2e3e
req 5: X-Served-By: 172.21.0.4:8000 served_by=instance-b23b86
req 6: X-Served-By: 172.21.0.5:8000 served_by=instance-6e2188
```

Gửi 10 request rồi đếm trong `docker compose -p k5-day14-scaling logs agent`:

```text
      3 agent-1
      4 agent-2
      3 agent-3
```

**Nếu 1 instance die, traffic chuyển sang instance khác** (thí nghiệm ở Exercise 5.5): `docker stop` agent-2 giữa một cuộc hội thoại, các request sau đó vẫn 200 và chỉ còn agent-1, agent-3 phục vụ. Nhờ `proxy_next_upstream error timeout http_503` trong `nginx.conf`, request gửi vào instance chết được Nginx thử lại ở instance khác, client không thấy lỗi.

### Exercise 5.5: Test stateless

Theo lưu ý K5 số 7, `test_stateless.py` gửi 5 câu trong cùng một session rồi đọc history, **không tự tắt instance nào**:

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: b8207037-8b4c-4eda-9282-8179c60bb8ed

Request 1: [instance-6f2e3e]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-b23b86]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-6e2188]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-6f2e3e]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 5: [instance-b23b86]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b23b86', 'instance-6f2e3e', 'instance-6e2188'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 request của cùng một session được **cả 3 instance** phục vụ luân phiên (6f2e3e → b23b86 → 6e2188 → 6f2e3e → b23b86). Không instance nào có đủ 5 câu trong bộ nhớ, nhưng history đọc lại có đủ **10 message** (5 câu hỏi + 5 câu trả lời) đúng thứ tự. Vì mỗi instance đọc history từ Redis trước khi xử lý và ghi lại vào Redis sau khi trả lời, state không nằm trong instance nào cả.

**Thí nghiệm thêm: tắt 1 instance giữa cuộc hội thoại** (bước "kill random instance" mà script không làm):

```text
turn1: served_by=instance-6f2e3e session=ae7d1a66-5bbf-4bd8-b3c1-cc551a8ea417
== docker stop agent-2
k5-day14-scaling-agent-1 Up 56 seconds (healthy)
k5-day14-scaling-agent-3 Up 55 seconds (healthy)
turn2: session=ae7d1a66-... turn=3 served_by=instance-6e2188 HTTP 200
turn3: session=ae7d1a66-... turn=4 served_by=instance-6f2e3e HTTP 200
turn4: session=ae7d1a66-... turn=5 served_by=instance-6e2188 HTTP 200
turn5: session=ae7d1a66-... turn=6 served_by=instance-6f2e3e HTTP 200
turn6: session=ae7d1a66-... turn=7 served_by=instance-6e2188 HTTP 200
turn7: session=ae7d1a66-... turn=8 served_by=instance-6f2e3e HTTP 200
== history
count = 14
['turn 1', 'turn 2', 'turn 3', 'turn 4', 'turn 5', 'turn 6', 'turn 7']
== redis key
3599          ← TTL của session:<id>, được làm mới mỗi lần ghi
== start agent-2 lại, chờ > 10 s, gửi 6 request
3 instance-6e2188, 2 instance-6f2e3e, 1 instance-5f18d3   ← agent-2 quay lại với ID mới
```

- Tắt agent-2: **không request nào lỗi**, conversation **không mất** (đủ 7 câu, 14 message).
- Bật lại agent-2: process mới sinh `INSTANCE_ID` mới (`instance-5f18d3`) và không có gì trong RAM, nhưng vẫn phục vụ được ngay vì state nằm ở Redis. Nginx đưa nó trở lại vòng chia sau khi hết `fail_timeout` mặc định (10 s); request gửi ngay trong 5 s đầu chưa vào agent-2.
- **Bug nhỏ thấy được:** trường `turn` trong response lệch +1 (câu thứ 2 báo `turn=3`), vì `app.py` đếm số câu `user` trong history **sau khi** đã thêm câu hiện tại, rồi lại `+ 1`.

Dọn stack: `docker compose -p k5-day14-scaling down`.

### Checkpoint 4 — Tự kiểm tra

- **Liveness (`/health`) khác readiness (`/ready`):**
  - `/health` trả lời "process còn sống không". Nếu fail, platform **restart** container. Vì vậy `/health` không nên phụ thuộc Redis/DB: Redis chết mà `/health` fail thì platform restart agent liên tục, không giải quyết được gì.
  - `/ready` trả lời "có nhận traffic được không" (đã khởi động xong, kết nối được Redis, không đang shutdown). Nếu fail, load balancer **ngừng gửi request** tới instance đó nhưng không restart; khi Redis trở lại thì `/ready` lại 200 và instance tự nhận traffic.
- **Vì sao state trong RAM hỏng khi nhiều instance:** mỗi instance có bộ nhớ riêng, load balancer gửi các request của cùng một user tới các instance khác nhau → instance sau không thấy dữ liệu của instance trước (thí nghiệm ở 5.3: instance B trả **404** cho session tạo ở instance A). State trong RAM cũng mất khi restart/scale down. Đưa state ra Redis thì mọi instance dùng chung một nguồn.

## Part 6: Final Project — output `check_production_ready.py`

Chạy **bản đầy đủ có Docker** trong WSL2 (`os.name` = `posix`), thư mục `06-lab-complete/`, không sửa `check_production_ready.py`:

```text
$ python check_production_ready.py
...
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
EXIT CODE: 0
```

Một số dòng chi tiết trong output: image **63 MB** (`docker image inspect`), `429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)`, `restart agent vẫn bị 429`, `Redis mất kết nối → /ready 503 (còn /health vẫn 200)`, `15 dòng JSON`, `SIGTERM lúc đang có request → request vẫn 200 ... exit code 0`, `docker stop ... exit code 0, 1.3s`.

### Cách tôi làm từng phần

| File | Làm gì |
|---|---|
| `app/config.py` | Đọc `PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD` từ env. `AGENT_API_KEY` không có giá trị mặc định; `ENVIRONMENT=production` mà thiếu key thì dừng ngay lúc khởi động (fail fast). Có `load_dotenv(override=False)` để chạy local, env thật luôn được ưu tiên |
| `app/redis_client.py` | `redis.from_url(..., socket_connect_timeout=2, socket_timeout=2)`: không mở kết nối lúc import, nên container khởi động được khi chưa có Redis. `redis_healthy()` ping, lỗi thì `False` |
| `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)`; thiếu **hoặc sai** key → **401** (không phải 403 như Part 4, không phải 422). So sánh bằng `hmac.compare_digest` (thời gian hằng). Chưa cấu hình key → từ chối tất cả |
| `app/rate_limiter.py` | Sliding window 60 s bằng Redis **sorted set**, key `ratelimit:<sha256(api_key)>` (không lưu key gốc). Một transaction `ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE` để 2 worker không đếm sai; vượt limit thì xoá phần tử vừa thêm và trả **429** kèm `Retry-After` tính theo request cũ nhất |
| `app/cost_guard.py` | `check_budget()` đọc `cost:day:YYYY-MM-DD` và `cost:month:YYYY-MM` (UTC), vượt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` → **402**. `record_cost()` tính tiền theo token rồi `INCRBYFLOAT` cả 2 key trong một transaction, có TTL. Sang ngày/tháng mới tự reset |
| `app/main.py` | `JsonFormatter` tự viết bằng `json.dumps` cho cả dòng (bài học Part 2) và `basicConfig(force=True)` (bài học Part 1). Middleware log mỗi request (`method`, `path`, `status`, `ms`, `request_id`). `/health` không đụng Redis; `/ready` 503 khi đang tắt hoặc mất Redis. `/ask`: `Depends(verify_api_key)` → `check_rate_limit` → `check_budget` → LLM → `record_cost`. Exception handler: lỗi Redis → **503**, lỗi khác → **500** chung chung, không lộ stack trace. Endpoint `/ask` là `def` thường để `time.sleep` của mock LLM không chặn event loop (bài học Part 5). Graceful shutdown bằng `lifespan`, **không** tự đăng ký handler SIGTERM để khỏi chặn handler của uvicorn |
| `Dockerfile` | 2 stage `python:3.11-slim`: builder tạo venv `/opt/venv` và cài requirements; runtime chỉ copy venv + `app/` + `utils/`, user `app` (uid 999), `HEALTHCHECK` gọi `/health` theo `PORT`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]`: `exec` để uvicorn là PID 1 |
| `.dockerignore` | Loại `.env`, `.env.*` (giữ `.env.example`), `__pycache__/`, `*.pyc`, `venv/`, `.venv/`, `.git/`, `*.md`, `benchmark-observability/`, script chấm, file deploy |
| `docker-compose.yml` | `agent` (build `.`, port 8000, `env_file: .env` với `required: false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: redis: service_healthy`, `stop_grace_period: 10s`) + `redis:7-alpine` (healthcheck `redis-cli ping`, AOF, volume) |
| `.env.example` | Liệt kê đủ biến, `AGENT_API_KEY=` để trống, có lệnh sinh key |
| `railway.toml` | `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart `ON_FAILURE` |
| `render.yaml` | `type: web`, `runtime: docker`, `healthCheckPath: /health`, `AGENT_API_KEY` dùng `generateValue: true`, `REDIS_URL` lấy `fromService` của một service `keyvalue` (Redis) khai báo cùng file |

### Kiểm tra thêm bằng tay qua `docker compose` (ngoài script chấm)

```bash
docker compose -p k5-day14-final up -d --build    # .env tạm chứa AGENT_API_KEY ngẫu nhiên, đã xoá sau khi test
```

```text
== /health                 {"status":"ok","version":"1.0.0","uptime_seconds":0.7,...}                [HTTP 200]
== /ready                  {"ready":true,"redis":"ok"}                                               [HTTP 200]
== /ask không key          {"detail":"Missing API key. Send header X-API-Key."}                      [HTTP 401]
== /ask sai key            {"detail":"Invalid API key."}                                             [HTTP 401]
== /ask đúng key           {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."} [HTTP 200]
== question rỗng           {"detail":[{"type":"string_too_short","loc":["body","question"],...}]}    [HTTP 422]
== thiếu question          {"detail":[{"type":"missing","loc":["body","question"],...}]}             [HTTP 422]
== JSON hỏng               {"detail":[{"type":"json_invalid","loc":["body",12],"msg":"JSON decode error",...}]} [HTTP 422]
== question 2001 ký tự     [HTTP 422]
== rate limit (limit 10, đã dùng 1)   200 200 200 200 200 200 200 200 200 429 429 429
== chi tiết 429
HTTP/1.1 429 Too Many Requests
retry-after: 59
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
== key trong Redis         cost:day:2026-11-26 · cost:month:2026-11 · ratelimit:f3dfd270d2272f0b154627b1 (đã dùng $0.00011655)
== restart agent → vẫn 429 {"detail":{"error":"Rate limit exceeded",...,"retry_after_seconds":55}}  [HTTP 429]
== dừng Redis
   /health                 {"status":"ok",...}                                                       [HTTP 200]
   /ready                  {"detail":"Redis not reachable"}                                          [HTTP 503]
   /ask                    {"detail":"Service temporarily unavailable (state store)."}               [HTTP 503]
== bật lại Redis → /ready  {"ready":true,"redis":"ok"}                                               [HTTP 200]
== trong container         uid=999(app) gid=999(app); PID 1 = /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 ...
== số dòng log chứa API key: 0
== docker stop agent       1.34 s, exit code 0
```

Mẫu log JSON của app (mỗi dòng là 1 JSON object):

```json
{"ts": "2026-11-26T08:14:25.301+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "method": "POST", "path": "/ask", "status": 429, "ms": 11.5, "request_id": "e0ee0fac37ad4934"}
{"ts": "2026-11-26T08:14:39.985+00:00", "lvl": "ERROR", "logger": "agent", "msg": "redis_error", "event": "redis_error", "path": "/ask", "error": "ConnectionError"}
{"ts": "2026-11-26T08:14:45.082+00:00", "lvl": "INFO", "logger": "agent", "msg": "shutdown", "event": "shutdown", "in_flight": 0, "uptime_s": 20.4}
```

**Vì sao `/health` phải 200 khi Redis chết còn `/ready` phải 503:** `/health` là liveness; nếu nó fail theo Redis thì platform sẽ restart agent liên tục trong khi lỗi nằm ở Redis, restart không sửa được gì. `/ready` là readiness: trả 503 để load balancer tạm ngừng gửi traffic (request vào cũng chỉ nhận 503), và khi Redis sống lại thì `/ready` tự về 200 mà không cần restart (đã thử ở trên).

**Điểm còn có thể cải thiện:** khi Redis bị dừng, `/ask` mất ~8 s mới trả 503 (log `"ms": 8038.4`) vì phải chờ timeout kết nối/DNS tới host `redis`. Có thể giảm bằng cách kiểm tra nhanh tình trạng Redis (circuit breaker) trước khi gọi lệnh.

## Part 7: Benchmark & Observability

Số liệu và phân tích đầy đủ (load test, tail latency, eval, quality gate) nằm trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md); file JSON trong [reports/](reports/). Mục này trả lời các câu hỏi của Exercise 7.1, mà mẫu báo cáo không có chỗ.

### Exercise 7.1: Đọc metrics của agent

Chạy `AGENT_VERSION=v1 PORT=8001 python app.py` và `AGENT_VERSION=v2 PORT=8002 python app.py` trong `06-lab-complete/benchmark-observability/develop/`, gọi 1 câu rồi đọc `/metrics`:

```text
$ curl -s -X POST http://localhost:8002/ask -H "Content-Type: application/json" -d '{"question": "Prometheus thu thập metrics như thế nào?"}'
{"answer":"Prometheus pull metrics bằng cách scrape endpoint /metrics theo chu kỳ. ...","model":"mock-llm-small","agent_version":"v2",
 "usage":{"input_tokens":91,"output_tokens":55,"cost_usd":4.665e-05},"llm_latency_ms":152.2,"request_id":"62c500d902a1"}

$ curl -s http://localhost:8002/metrics | grep -v "^#"
http_requests_total{method="POST",route="/ask",status="200"} 1.0
http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0
http_request_duration_seconds_count{method="POST",route="/ask"} 1.0
http_request_duration_seconds_sum{method="POST",route="/ask"} 0.18162324900004023
agent_in_flight_requests 0.0
llm_requests_total{model="mock-llm-small",status="ok"} 1.0
llm_tokens_total{model="mock-llm-small",type="input"} 91.0
llm_tokens_total{model="mock-llm-small",type="output"} 55.0
llm_cost_usd_total{model="mock-llm-small"} 4.6649999999999996e-05
agent_info{model="mock-llm-small",version="v2"} 1.0
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
```

**1. Ví dụ cho mỗi loại metric:**
- **Counter** (chỉ tăng, dùng với `rate()`): `http_requests_total{method="POST",route="/ask",status="200"} 1.0`; tương tự `llm_tokens_total`, `llm_cost_usd_total`, `llm_requests_total`.
- **Gauge** (lên xuống được): `agent_in_flight_requests 0.0` (số request đang xử lý); `agent_info{...} 1.0` (gauge hằng số để gắn label version/model).
- **Histogram** (đếm giá trị theo bucket, kèm `_sum`, `_count`, dùng `histogram_quantile()` để tính percentile): `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0`, cùng `_sum` = 0.1816 s và `_count` = 1.

**2. Nếu dùng URL thật (`request.url.path`) làm label `route`:** mỗi URL khác nhau tạo ra **một time series mới** cho cả `http_requests_total` lẫn **mọi bucket** của `http_request_duration_seconds` (11 bucket + `_sum` + `_count`, nhân thêm số giá trị `status`, `method`). Bot quét hàng nghìn URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`...) sẽ sinh hàng chục nghìn series chỉ trong vài phút. Prometheus giữ mọi series trong RAM và index, nên tốn bộ nhớ, query chậm, có thể OOM. Đây là **cardinality explosion**, và kẻ tấn công điều khiển được nó bằng URL tuỳ ý. Dùng route template thì mọi URL lạ gộp vào một giá trị `unmatched`. Đã thử: gọi `/wp-admin`, `/.env`, `/a1b2c3` thì `/metrics` chỉ có thêm **đúng 1 series** `http_requests_total{method="GET",route="unmatched",status="404"} 3.0`.

**Nhiệm vụ: thêm metric `agent_question_length_chars`.** Đã thêm vào `develop/app.py`:

```python
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Độ dài câu hỏi gửi tới /ask (ký tự)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)
# trong endpoint ask(), trước khi gọi LLM:
QUESTION_LENGTH.observe(len(body.question))
```

Kết quả sau 1 câu hỏi 40 ký tự: `agent_question_length_chars_count 1.0`, `agent_question_length_chars_sum 40.0`. Dùng Histogram chứ không dùng label `length=...`, vì độ dài có vô số giá trị, làm label sẽ bùng nổ cardinality đúng như câu 2.

## AI log

| # | Phần | Hỏi AI gì | Nhận được gì | Tôi tự sửa / tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | CP0 | Dùng Claude Code đọc toàn bộ tài liệu lab và kiểm tra môi trường | Danh sách việc cần làm ở CP0; phát hiện Python Windows là `nt`, WSL thiếu `pip`/`venv` | Tự mở terminal Ubuntu, tự chạy `sudo apt install python3.12-venv python3-pip`, tạo venv `~/venvs/day14`; kiểm `os.name` = `posix`, `docker run --rm hello-world` chạy được |
| 2 | CP1 | Dùng Claude Code chạy bản develop và production của Part 1 trong WSL, gợi ý anti-pattern và bảng so sánh | Output curl thật, log server, bảng so sánh; phát hiện log JSON của bản production không hiện và `.env` không được nạp | Đối chiếu từng anti-pattern với số dòng trong `develop/app.py`; xem lại log server để xác nhận key bị in ra; đọc `config.py` để hiểu vì sao `basicConfig` không có tác dụng |
| 3 | CP2 | Dùng Claude Code build 2 image, chạy container, bật stack Compose, giải thích multi-stage và vẽ sơ đồ | Lệnh build/run, số đo `docker images` (1.67 GB vs 240 MB), output test qua Nginx, sơ đồ service | Tự xem `docker images`, `docker history`, `docker exec ... whoami`; tính lại % chênh lệch; đối chiếu sơ đồ với `docker-compose.yml` và `nginx.conf` |
| 4 | CP3 | Dùng Claude Code chạy Part 4 (API key, JWT, vòng lặp rate limit), giải thích thuật toán, viết cost guard Redis bằng Lua script | Output `curl -i` 401/403/200/429 (token đã che), phân tích sliding window, đoạn code cost guard và kết quả chạy với Redis thật | Đếm lại số request 200 trước khi gặp 429 (10 = limit); decode payload JWT để kiểm `exp − iat` = 60 phút; xem key `budget:*` trong Redis bằng `redis-cli`; kiểm request bị từ chối không bị cộng tiền |
| 5 | CP4 | Dùng Claude Code chạy health check, test SIGTERM giữa request, bật stack 3 instance, chạy `test_stateless.py`, thử tắt 1 instance và thử chế độ không Redis | Output health/ready, log graceful shutdown, phân bố request theo instance, history sau khi tắt instance, giải thích liveness vs readiness | Tự đếm phân bố request trong `docker compose logs`; kiểm history đủ 7 câu sau khi `docker stop` agent-2; đọc `app.py` để tìm nguyên nhân request chạy nối tiếp (sleep đồng bộ trong `async def`) và trường `turn` lệch +1 |
| 6 | CP5 | Dùng Claude Code đọc `check_production_ready.py` và README Part 6, viết code cho mọi `TODO` trong `06-lab-complete/` (config, auth, rate limiter Redis sorted set, cost guard Redis, log JSON, health/ready, Dockerfile multi-stage, compose, deploy config) | Toàn bộ code Part 6; script chấm báo `PASS 12/12`, 43/43 checks | Chạy `--static-only` (0/12) → `--skip-docker` (10/12) → bản đầy đủ (12/12); tự test thêm bằng `docker compose`: 401/422/429/402, restart vẫn 429, dừng Redis → `/ready` 503 + `/ask` 503 không lộ stack trace, log không chứa API key, `docker stop` 1.3 s exit 0; đọc lại từng file để giải thích được luồng `/ask` và lý do `/health` không phụ thuộc Redis |
| 7 | CP6 | Dùng Claude Code cài Railway CLI, tạo project + Redis + service agent, đặt biến môi trường, deploy, chạy 4 lệnh tự kiểm, so sánh `railway.toml`/`render.yaml`, tóm tắt pipeline Cloud Run | URL public, output 200/200/401/200, rate limit trên cloud, script chấm `--public-url` 44/44, bảng so sánh, mô tả 4 bước Cloud Build | Tự `railway login`; kiểm `REDIS_URL` trên Railway đã được resolve (không còn chuỗi `${{...}}`); key sinh ngẫu nhiên lưu trong `.env.deploy` (gitignore), đặt qua `--stdin`; tự chụp ảnh dashboard / running / test |
| 8 | CP7 | Dùng Claude Code chạy agent v1/v2, load test 4 mức concurrency + 3 mức `MOCK_SLOW_RATE`, eval v1/v2, thêm metric `agent_question_length_chars`, sửa `KNOWLEDGE_BASE` cho 2 câu sai, viết job CI, điền mục 1–3 của `BENCHMARK_REPORT.md` | 10 file JSON trong `reports/`, phân tích RPS/percentile, 2 entry KB mới, `.github/workflows/eval.yml` | Số trong báo cáo lấy từ JSON bằng script, kiểm lại phép tính (tỉ lệ, cost / câu đúng); thấy p95 lúc PASS lúc FAIL ở `MOCK_SLOW_RATE=0.03` nên chạy thêm 3 lần, đếm tỉ lệ request chậm từ `/metrics` (4.4 % / 3.0 % / 5.4 %) để giải thích; kiểm 0 regression; chạy thử lệnh của job CI (v2 exit 0, v1 exit 1); không sửa `golden_dataset.jsonl` |
