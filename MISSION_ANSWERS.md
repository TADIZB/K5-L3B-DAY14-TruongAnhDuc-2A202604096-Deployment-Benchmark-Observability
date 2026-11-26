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

_(CP6 — chưa làm)_

## Part 4: API Security

_(CP3 — chưa làm)_

## Part 5: Scaling & Reliability

_(CP4 — chưa làm)_

## Part 6: Final Project — output `check_production_ready.py`

_(CP5 — chưa làm)_

## AI log

| # | Phần | Hỏi AI gì | Nhận được gì | Tôi tự sửa / tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | CP0 | Dùng Claude Code đọc toàn bộ tài liệu lab và kiểm tra môi trường | Danh sách việc cần làm ở CP0; phát hiện Python Windows là `nt`, WSL thiếu `pip`/`venv` | Tự mở terminal Ubuntu, tự chạy `sudo apt install python3.12-venv python3-pip`, tạo venv `~/venvs/day14`; kiểm `os.name` = `posix`, `docker run --rm hello-world` chạy được |
| 2 | CP1 | Dùng Claude Code chạy bản develop và production của Part 1 trong WSL, gợi ý anti-pattern và bảng so sánh | Output curl thật, log server, bảng so sánh; phát hiện log JSON của bản production không hiện và `.env` không được nạp | Đối chiếu từng anti-pattern với số dòng trong `develop/app.py`; xem lại log server để xác nhận key bị in ra; đọc `config.py` để hiểu vì sao `basicConfig` không có tác dụng |
| 3 | CP2 | Dùng Claude Code build 2 image, chạy container, bật stack Compose, giải thích multi-stage và vẽ sơ đồ | Lệnh build/run, số đo `docker images` (1.67 GB vs 240 MB), output test qua Nginx, sơ đồ service | Tự xem `docker images`, `docker history`, `docker exec ... whoami`; tính lại % chênh lệch; đối chiếu sơ đồ với `docker-compose.yml` và `nginx.conf` |
