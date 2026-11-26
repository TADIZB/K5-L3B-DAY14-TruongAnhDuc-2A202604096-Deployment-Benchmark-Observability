# Deployment Information

## Public URL

https://agent-production-7dc48df9.up.railway.app

## Platform

**Railway**: project `day14-agent`, environment `production`, region `sfo`. Gồm 2 service:

| Service | Nguồn | Vai trò |
|---|---|---|
| `agent` | `railway up` từ thư mục `06-lab-complete/` (builder `DOCKERFILE`, theo `railway.toml`) | Agent Part 6, domain public ở trên |
| `Redis` | Template database Redis của Railway (`redis:8.2`, volume `/data`) | Lưu state rate limit + cost guard; chỉ truy cập qua private network `redis.railway.internal` |

Cách deploy (chạy trong `06-lab-complete/`):

```bash
npm i -g @railway/cli
railway login
railway init --name day14-agent
railway add --database redis
railway add --service agent
railway variable set ENVIRONMENT=production RATE_LIMIT_PER_MINUTE=10 DAILY_BUDGET_USD=1.0 \
  MONTHLY_BUDGET_USD=10.0 LOG_LEVEL=INFO 'REDIS_URL=${{Redis.REDIS_URL}}' --service agent --skip-deploys
python -c "import secrets; print(secrets.token_urlsafe(32))" | railway variable set AGENT_API_KEY --stdin --service agent --skip-deploys
railway up --service agent --ci
railway domain --service agent
```

`AGENT_API_KEY` được sinh ngẫu nhiên và đặt qua stdin, nên không xuất hiện trong lệnh, code hay repo.

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên Railway (key không ghi trong repo). Mỗi lệnh chỉ in mã HTTP:

```bash
BASE=https://agent-production-7dc48df9.up.railway.app

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy ngày 2026-11-26:

```text
200
200
401
200
```

### Health check

```text
$ curl https://agent-production-7dc48df9.up.railway.app/health
{"status":"ok","version":"1.0.0","uptime_seconds":33.3,"timestamp":"2026-11-26T09:03:22.377697+00:00"}

$ curl https://agent-production-7dc48df9.up.railway.app/ready
{"ready":true,"redis":"ok"}
```

### API test (with authentication)

```text
$ curl -X POST https://agent-production-7dc48df9.up.railway.app/ask \
    -H "X-API-Key: $AGENT_API_KEY" -H "Content-Type: application/json" \
    -d '{"question": "What is deployment?"}'
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."}

$ curl -X POST .../ask -H "X-API-Key: wrong" -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"detail":"Invalid API key."}                                   ← HTTP 401
```

### Rate limit (10 request / phút, state trong Redis trên Railway)

```text
$ for i in $(seq 1 12); do curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" \
    -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"hi"}'; done
200 200 200 200 200 200 200 200 429 429 429 429        ← 2 request trước đó + 8 = 10, request thứ 11 bị chặn

HTTP/1.1 429 Too Many Requests
retry-after: 42
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":42}}
```

### Script chấm kèm URL public

```text
$ python check_production_ready.py --public-url https://agent-production-7dc48df9.up.railway.app
     ✅ Public URL: GET https://agent-production-7dc48df9.up.railway.app/health → 200
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

## Environment Variables Set

Đặt trên Railway (service `agent` → Variables), **không** ghi trong code hay repo:

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | *(secret, sinh ngẫu nhiên 32 byte)* | Không ghi ở đây |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Reference variable của Railway, trỏ tới `redis://...@redis.railway.internal:6379` |
| `ENVIRONMENT` | `production` | Bật fail-fast khi thiếu key, tắt `/docs` |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` | `1.0` | |
| `MONTHLY_BUDGET_USD` | `10.0` | |
| `LOG_LEVEL` | `INFO` | |
| `PORT` | *(Railway tự cấp)* | Dockerfile nghe theo `${PORT:-8000}` |

## Logs

```bash
railway logs --service agent
```

Railway tự đọc log JSON của app thành log có cấu trúc:

```text
[INFO] request ts="2026-11-26T09:03:37.810+00:00" logger="agent" event="request" method="POST" path="/ask" status=200 ms=132.1 request_id="4f00cef477094a97"
[INFO] llm_call ts="2026-11-26T09:03:38.244+00:00" logger="agent" event="llm_call" llm_ms=106.3 question_chars=2 cost_usd=0.00001035
```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
