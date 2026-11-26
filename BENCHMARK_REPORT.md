# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [`reports/`](reports/) (sinh bởi `load_test.py --out` và `run_eval.py --out`), CSV trong [`benchmark-results/`](benchmark-results/) và screenshot thật, không ước lượng.

**Họ tên:** Trương Anh Đức
**Ngày chạy:** 2026-11-26
**Môi trường:** Laptop Intel Core i7-12700H, 16 GB RAM, Windows 11 + WSL2 Ubuntu (Python 3.12.3); Docker Desktop 28.1.1 (WSL2 backend, 20 CPU / 7.6 GB RAM cấp cho Docker). Load test và agent chạy trên cùng một máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | LLM mock mất ~150–220 ms/call ở điều kiện bình thường (p50 ≈ 190–200 ms trong mọi lần đo), nên 500 ms còn dư hơn 2 lần cho jitter và retrieval mà người dùng vẫn thấy "nhanh". Đặt theo p95 chứ không theo avg để bắt được tail latency (mục 2.2) |
| Error rate `/ask` | < 2 % | Mock có 1 % lỗi upstream ngẫu nhiên (`MOCK_ERROR_RATE=0.01`); 2 % cho phép lỗi nền đó và một chút dao động, nhưng vượt 2 % nghĩa là có sự cố thật. Error budget = 2 % số request |
| Accuracy trên golden dataset | ≥ 85 % (CI), mục tiêu 100 % khi release | 85 % là ngưỡng chặn merge trong job CI (`--min-accuracy 0.85`), và **không được có regression** so với baseline. Bản release phải đạt 23/23 (`--min-accuracy 1.0`) như `eval_v2_fixed.json` |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (v2, `MOCK_SLOW_RATE` mặc định 0.03).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.54 | 194.9 | 1669.3 | 1702.6 | 0.00 % | ❌ FAIL (p95) |
| 10 | 35.28 | 191.0 | 223.2 | 1693.5 | 1.00 % | ✅ PASS |
| 50 | 110.90 | 201.3 | 265.3 | 1700.5 | 1.67 % | ✅ PASS |
| 100 | 62.85 | 390.3 | 3178.9 | 3445.7 | 1.67 % | ❌ FAIL (p95) |

Nguồn: [`reports/load_v2_c1.json`](reports/load_v2_c1.json), [`c10`](reports/load_v2_c10.json), [`c50`](reports/load_v2_c50.json), [`c100`](reports/load_v2_c100.json).

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency.

- **1 → 10 → 50: tăng gần tuyến tính nhưng chậm dần** (3.54 → 35.28 → 110.90 req/s). Load test là *closed-loop*: mỗi worker chờ response rồi mới gửi tiếp, nên RPS ≈ concurrency / latency. Ở c=1 đúng bằng 1 / 0.282 s (avg) ≈ 3.5 req/s; ở c=10, 10 / 0.242 s ≈ 41 req/s (đo được 35.28). Ở c=50 lẽ ra ~226 req/s nhưng chỉ đo được 110.90, vì 300 request chia cho 50 worker chỉ còn ~6 vòng: tổng thời gian 2.71 s bị kéo dài bởi vài request chậm 1.7 s ở cuối (tail latency chiếm phần lớn thời gian chạy).
- **50 → 100: RPS giảm** (110.90 → 62.85) và **p50 tăng gấp đôi** (201 → 390 ms), p95 lên 3178.9 ms. Agent chỉ là **1 process uvicorn, 1 event loop**: ngoài thời gian chờ LLM (async, không tốn CPU), mỗi request còn tốn CPU cho parse JSON, Pydantic, log JSON, cập nhật metrics, mà đều chạy tuần tự trên 1 core. Ở 100 request đồng thời, các phần CPU này xếp hàng, nên request phải chờ trong hàng đợi của server. Trên cùng máy, client load test cũng tranh CPU với agent. Đây là điểm **bão hoà (saturation)**: thêm concurrency chỉ làm tăng latency, không tăng throughput.
- **c=1 FAIL p95 dù tải nhẹ nhất:** không phải do tải mà do **tail latency + kích thước mẫu**. Với `MOCK_SLOW_RATE=0.03`, khoảng 3 % request chậm thêm 1.5 s. p95 nằm ngay sát ngưỡng đó: chỉ cần **hơn 5 %** request rơi vào nhóm chậm là p95 nhảy từ ~220 ms lên ~1.7 s. Lần chạy c=1 có p90 = 223 ms nhưng p95 = 1669 ms, tức hơn 5 % trong 300 request là request chậm. Kiểm chứng thêm: chạy lại 3 lần cùng cấu hình (c=20, không lưu file), tỉ lệ request chậm đếm từ `/metrics` lần lượt là 4.4 %, 3.0 %, 5.4 %, và p95 lần lượt 232.0 / 224.6 / 1659.6 ms. Kết luận: **300 request là quá ít để đo p95 ổn định khi tỉ lệ chậm gần 5 %**; cần chạy lâu hơn (`--duration`) hoặc nhiều request hơn trước khi kết luận.
- Muốn tăng throughput thật sự thì phải **scale ngang** (nhiều worker/instance sau load balancer, mục 5), không phải tăng concurrency trên 1 process.

### 2.2 Tail latency

Lệnh: bật lại v2 với từng giá trị `MOCK_SLOW_RATE`, rồi `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<rate>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 191.1 | 219.7 | 229.2 |
| 0.03 (mặc định) | 280.1 | 1662.2 | 1701.7 |
| 0.1 | 366.7 | 1688.8 | 1721.0 |

Nguồn: [`reports/load_v2_slow_0.json`](reports/load_v2_slow_0.json), [`slow_0.03`](reports/load_v2_slow_0.03.json), [`slow_0.1`](reports/load_v2_slow_0.1.json). p50 gần như không đổi (192.5 / 196.6 / 194.9 ms); RPS giảm 101.61 → 56.80 → 46.24 req/s.

**Nhận xét:** Chỉ số nhạy nhất với request chậm là **p95/p99**. Từ 0 lên 0.03, avg chỉ tăng 1.47 lần (191 → 280 ms), trong khi p99 tăng **7.4 lần** (229 → 1702 ms) và p95 tăng 7.6 lần (220 → 1662 ms, ở lần đo này p95 rơi vào nhóm chậm như phân tích ở 2.1). p50 thì gần như không nhúc nhích. Lý do: avg chia đều vài request 1.7 s cho cả 300 request nên bị "pha loãng"; percentile thì chỉ ra thẳng trải nghiệm của nhóm người dùng tệ nhất. Nhìn avg = 280 ms tưởng vẫn ổn, nhưng thực tế cứ 100 người thì vài người chờ gần 2 giây.

SLO không nên đặt theo average vì:
1. Average che giấu tail latency: hệ thống có thể "đạt" SLO avg trong khi 3–10 % người dùng chờ gần 2 s.
2. Average bị kéo bởi vài giá trị cực lớn, không cho biết bao nhiêu người bị ảnh hưởng. "p95 < 500 ms" thì có nghĩa rõ ràng: 95 % request nhanh hơn 500 ms.
3. Người dùng nhớ lần chậm nhất, và một trang gọi nhiều request thì khả năng dính ít nhất 1 request chậm cao hơn nhiều so với 1 request đơn lẻ.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Lệnh:

```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sửa KNOWLEDGE_BASE, tắt rồi bật lại v2
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35 % (1/23) | 91.30 % (21/23) | **100 % (23/23)** |
| Avg tokens / câu | 57.2 | 108.7 | 116.1 |
| Tổng cost (USD) | 0.000405 | 0.000756 | 0.000812 |
| Cost / câu đúng (USD) | 0.00040515 | 0.00003599 | 0.00003530 |
| Quality gate | FAIL (accuracy < 80 %) | PASS (≥ 80 %, 0 regression so với v1) | PASS (≥ 100 %, 0 regression so với v2) |

Nguồn: [`reports/eval_v1.json`](reports/eval_v1.json), [`reports/eval_v2.json`](reports/eval_v2.json), [`reports/eval_v2_fixed.json`](reports/eval_v2_fixed.json). Lệnh cuối in `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`, `Câu được cải thiện : 2`, `Câu bị regression : 0`.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Câu hỏi không khớp từ khoá nào trong `KNOWLEDGE_BASE` nên retrieval trả rỗng và agent trả câu chung chung. Thêm entry kích hoạt bởi `["hpa", "kubernetes", "autoscal"]`, nội dung: HPA tự tăng/giảm số pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi từ Prometheus) |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Tương tự, không có tài liệu về JWT. Thêm entry kích hoạt bởi `["jwt", "api key"]`, nội dung: API key là chuỗi bí mật cố định, không tự hết hạn; JWT là token có chữ ký số, chứa user, role, thời điểm hết hạn, server chỉ cần kiểm chữ ký |

Chỉ sửa `KNOWLEDGE_BASE` trong `06-lab-complete/benchmark-observability/develop/utils/mock_llm.py` (và chép sang bản `production/utils/mock_llm.py` cho stack Docker), **không** sửa `golden_dataset.jsonl`. Từ khoá kích hoạt mới không xuất hiện trong các câu hỏi khác nên không làm đổi tài liệu được chọn cho 21 câu đang đúng (0 regression).

**Job CI (quality gate):** [`.github/workflows/eval.yml`](.github/workflows/eval.yml). Trên mỗi pull request đụng tới `develop/`, job bật agent v2 (`MOCK_ERROR_RATE=0` để tránh fail ngẫu nhiên) rồi chạy `python eval/run_eval.py --min-accuracy 0.85`. `run_eval.py` trả **exit code 1** khi accuracy < ngưỡng hoặc có regression so với `--baseline`, nên step fail, job fail, và nếu bật *Require status checks to pass* cho nhánh `main` thì PR không merge được. Đã chạy thử đúng các lệnh của job trên máy: agent v2 → exit code **0** (PASS); agent v1 → exit code **1** (FAIL). Thêm: chạy eval v1 với `--baseline reports/eval_v2.json` → exit code **1**, báo 20 câu regression.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 có retrieval (RAG) tăng accuracy từ 4.35 % lên 91.30 % (100 % sau khi bổ sung KB). v1 chỉ trả lời đúng câu "Deploy nghĩa là gì?".
- **Chi phí:** v2 tốn gần gấp đôi token mỗi câu (57.2 → 108.7, +90 %) vì prompt có thêm tài liệu, tổng cost tăng 0.000405 → 0.000756 USD (+87 %). Nhưng **cost / câu đúng giảm ~11 lần** (0.00040515 → 0.00003599 USD), vì v1 tốn tiền cho 22 câu trả lời sai vô dụng. Đây là lý do so sánh theo "cost / câu đúng" chứ không theo "cost / câu". Bổ sung KB làm avg tokens tăng nhẹ (108.7 → 116.1) nhưng cost / câu đúng còn giảm thêm (0.00003530).
- **Latency:** v2 chậm hơn một chút cho mỗi request: thêm bước retrieval ~20 ms và prompt dài hơn (`input_tokens × 0.2 ms`). p50 eval 159.8 ms (v1) so với 197.8 ms (v2). (p95 của eval không dùng để so latency: 23 mẫu quá ít, 1–2 request chậm là p95 nhảy lên 1546 ms như `eval_v2.json`; latency phải đo bằng load test ở mục 2.)
- **Kết luận:** đổi ~40 ms latency và ~2 lần token để có chất lượng tăng từ gần 0 lên 100 % là rất đáng. Chi phí cần theo dõi là cost / câu đúng và tổng cost theo thời gian (alert ngân sách).

---

## 4. Observability stack (production)

Stack: `06-lab-complete/benchmark-observability/production/`, bật bằng `docker compose -p k5-day14-observability up -d --build` (2 instance agent + Nginx + Prometheus + Grafana + Jaeger + Locust). Tải nền: Locust headless **30 user, ramp 5** chạy liên tục trong suốt mục 4.

Trước khi chạy được phải sửa 1 lỗi có sẵn trong `production/Dockerfile`: user `agent` được tạo với home `/app` (`useradd -d /app`) nên Python tìm package `pip install --user` ở `/app/.local`, trong khi package nằm ở `/home/agent/.local`, khiến container crash với `ModuleNotFoundError: No module named 'uvicorn'`. Sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`, cùng lưu ý với CODE_LAB Part 6 Step 8. Unit test alert rule: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

**Exercise 7.4: đọc dashboard khi có tải** (30 user, 2 instance, đo bằng các câu PromQL của dashboard lúc 10:14:43 UTC):

1. **p95 = 296 ms, avg = 247 ms** (p50 = 181 ms, p99 = 1865 ms). p95 và avg chênh ít vì chỉ ~3 % request chậm (dưới ngưỡng 5 % của p95), nhưng **p99 gấp 7.5 lần avg**: phần đuôi (tail latency) do LLM thỉnh thoảng chậm 1.5 s. Avg không cho thấy điều đó; khoảng cách avg ↔ p99 càng lớn thì nhóm người dùng xui càng chịu thiệt.
2. **Nginx chia đều:** panel "Requests/s theo instance" cho 6.62 và 6.42 req/s (lúc 10:14:43), rồi 9.96 và 9.97 req/s (10:16:17). Ở benchmark 3 instance mục 5, 3 instance nhận 2419 / 2403 / 2433 request trong 2 phút (round-robin).
3. **Input tokens/s lớn hơn output tokens/s** (1012 so với 537 tokens/s; trung bình 78.7 input so với 41.8 output mỗi call): input = system prompt + **tài liệu retrieval (RAG)** + câu hỏi, còn output chỉ là câu trả lời ngắn. RAG làm prompt dài, vì vậy input chiếm phần lớn token (dù giá output đắt hơn 4 lần mỗi token).
4. **`curl http://localhost:8080/metrics` → `404`.** `nginx.conf` có `location = /metrics { return 404; }`: `/metrics` chỉ dành cho Prometheus scrape trực tiếp từng container trong mạng nội bộ `obs_net`, không public ra ngoài vì metric lộ thông tin hệ thống (route, lưu lượng, version, chi phí). Qua Nginx cũng vô nghĩa: mỗi lần gọi chỉ trúng 1 instance theo round-robin.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png). Khung 30 phút gồm 2 lần benchmark 100 user, giai đoạn 30 user bình thường, rồi lúc thí nghiệm A + B đang chạy (Error rate 20.31 %, p95 1.90 s chuyển đỏ).
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png), trace `f4d74e9…`, 2.0 s, span `chat mock-llm-small` 1.7 s.
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png), trace `d9e1bbd…`, event `exception` với `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`.
- [x] Trang Alerts của Prometheus với **2 alert cùng firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png), `AgentHighErrorRate` (value 0.196) và `AgentHighLatencyP95` (value 1.899 s).

### 4.2 Thí nghiệm "phá hệ thống"

Mỗi thí nghiệm: sửa `production/.env` (copy từ `.env.example`), chạy `docker compose -p k5-day14-observability up -d --scale agent=2`, ghi thời điểm, rồi poll API `/api/v1/rules` của Prometheus mỗi ~10 s tới khi alert `firing` (sai số ±10 s). Thời gian = lúc thấy `firing` − lúc lệnh `up -d` xong.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (value 0.179–0.204) | **~94 s** (đổi 10:16:39 → pending 10:17:07 → firing 10:18:13) | **Error rate** (stat đỏ 20 %), "Requests/s theo status code" (vạch 503), "LLM calls theo kết quả" (error) |
| B | `MOCK_SLOW_RATE=0.3` (giữ A) | `AgentHighLatencyP95` (value 1.89 s) | **~146 s** (đổi 10:18:35 → pending 10:18:57 → firing ~10:21:01) | **Latency p95** (stat 1.90 s đỏ), "Latency /ask p50/p95/p99": p95/p99 lên ~1.9 s trong khi p50 vẫn 193 ms, avg 551 ms; "LLM latency p95" |
| C | `LLM_MODEL=mock-llm-large` (trả A, B về mặc định) | `LLMCostBurnRateHigh` (value 17.1 $/giờ) | **~143 s** (đổi 10:31:36 → pending 10:31:52 → firing 10:33:59) | **Cost burn rate (USD/giờ)**: 1.72 → 17.75 $/giờ; "LLM cost (1h)"; latency p50 181 → 414 ms, LLM p95 199 → 496 ms (không đủ để `AgentHighLatencyP95` firing) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`up{instance="172.21.0.7:8000"} == 0`) | **~49 s** (pause 10:34:19 → pending 10:34:27 → firing 10:35:07) | **Instances up** (2 → 1); "Requests/s theo instance" (toàn bộ ~15 req/s dồn sang instance còn lại). **Error rate vẫn xanh** (0.97 %) |
| E | `AGENT_VERSION=v1` | **Không có** alert nào do E gây ra | — | Tokens/s giảm (input 78 → 36 tokens/call, output 42 → 20); bảng version đổi `v2 → v1`; "Retrieval hit ratio" mất dữ liệu (v1 không gọi retrieval); latency còn *tốt hơn* (p50 152 ms, p95 199 ms) |

Ghi chú từ thí nghiệm:
- **A:** trạng thái `pending` xuất hiện sau ~28 s (cần ~2 lần scrape 5 s + cửa sổ `rate[1m]` đủ dữ liệu để vượt 5 %), sau đó phải giữ nguyên `for: 1m`.
- **B:** đúng như bài tail latency: avg chỉ lên 551 ms (dưới SLO 1 s) nhưng p95 1.89 s. `for: 2m` nên chậm hơn A.
- **C:** alert chi phí dùng `rate[5m]` + `for: 2m`, nên giá trị tăng dần (3.07 → 17.09 $/giờ trong lúc pending). **Phát hiện thêm:** ngưỡng 2 $/giờ **quá thấp so với lưu lượng**: ngay ở trạng thái bình thường, 30 user (~20 req/s, mock-llm-small) đã đốt ~2.2–4.3 $/giờ, và `LLMCostBurnRateHigh` **đã firing từ 10:04:57** trong lúc benchmark 100 user. Alert chi phí nên tính theo chi phí trên mỗi request hoặc theo ngân sách ngày (burn rate so với budget), không chỉ một con số tuyệt đối.
- **D:** Nginx log trong lúc pause có **504** (`upstream timed out ... while reading response header`) khoảng 10–20 s một lần: Nginx gửi request vào instance bị pause, chờ hết `proxy_read_timeout 10s`, đánh dấu instance lỗi trong 10 s rồi thử lại. Lỗi này **không hiện trên dashboard** vì request chưa bao giờ được agent xử lý xong, nên metric của agent không đếm. Cần giám sát ở tầng load balancer (metric/log của Nginx) hoặc synthetic check từ bên ngoài.
- **Phát hiện thêm:** mỗi lần `docker compose up -d` để đổi cấu hình, Compose tạo lại **cả 2 agent cùng lúc**. Nginx log cho thấy **285 request 502** (`no live upstreams`) + vài 503 trong ~20 s (10:34:10–10:34:29). Đây là deploy không có rolling update: production cần thay từng instance một và chờ `/ready` trước khi chuyển traffic.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 làm agent **trả lời sai** nhưng mọi metric hạ tầng đều "đẹp hơn": nhanh hơn, ít token hơn, rẻ hơn, không lỗi HTTP. Metric hạ tầng chỉ đo *có trả lời được không, nhanh không*, không đo *trả lời đúng không*. Cách phát hiện:
1. **Chặn trước khi deploy:** quality gate eval trên golden dataset trong CI (`run_eval.py --min-accuracy 0.85 --baseline ...`, mục 3). v1 so với baseline v2 trả exit 1 với 20 câu regression, nên không merge/deploy được.
2. **Giám sát chất lượng khi chạy (online eval):** định kỳ chạy golden dataset vào production (synthetic probe) và đẩy accuracy thành metric để alert khi giảm; hoặc lấy mẫu vài % request thật cho LLM-as-judge chấm điểm.
3. **Metric gián tiếp về chất lượng:** retrieval hit ratio (panel đã mất dữ liệu ở E), tỉ lệ câu trả lời "chung chung"/fallback, độ dài câu trả lời, phản hồi 👍/👎 của người dùng; alert khi các chỉ số này lệch khỏi baseline.
4. **Theo dõi version:** panel/bảng `agent_info{version}` và annotation deploy trên Grafana để liên hệ thay đổi chất lượng với lần deploy.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (Jaeger → Service `observable-agent`, lọc span ≥ 1 s, sắp xếp Longest First; trong 893 trace có span ≥ 1 s):

- `trace_id`: `f4d74e984a9653e20dcc3bcaa8ffe3f7` (10:10:54 UTC, trong lúc benchmark 100 user, 1 instance)
- Tổng thời gian: **2043.2 ms** (span gốc `POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` (1669.8 ms, 81.7 %)**. Cây span:

```text
POST /ask                    2043.2 ms (100.0%)
└── agent.run                1775.2 ms ( 86.9%)  agent.version=v2, agent.question.length=23
    ├── agent.retrieve_context  105.0 ms (  5.1%)  retrieval.documents=1
    └── chat mock-llm-small    1669.8 ms ( 81.7%)  gen_ai.request.model=mock-llm-small,
                                                   gen_ai.usage.input_tokens=72, output_tokens=40
```

  Nút thắt là **LLM upstream** (request rơi vào nhóm "slow" của mock: ~1.5 s cộng thêm), không phải code của agent. Chi tiết đáng chú ý: ~268 ms nằm *ngoài* `agent.run` (2043 − 1775) và `retrieve_context` mất 105 ms thay vì ~20 ms như bình thường. Trace này nằm trong lần benchmark 100 user dồn vào **1 instance bị giới hạn 0.5 CPU**, nên request phải xếp hàng chờ CPU, dấu hiệu instance đang bão hoà.
- Dòng log tương ứng (grep theo `trace_id`: `docker compose -p k5-day14-observability logs agent | grep f4d74e984a9653e20dcc3bcaa8ffe3f7`):

```json
{"ts": "2026-11-26T10:10:56.581626+00:00", "level": "INFO", "service": "observable-agent", "instance": "40bac56038fa", "event": "llm_call", "trace_id": "f4d74e984a9653e20dcc3bcaa8ffe3f7", "span_id": "ade89ddc7880d0ce", "request_id": "d650e90d5b16", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 72, "output_tokens": 40, "cost_usd": 3.5e-05, "llm_ms": 1669.4}
{"ts": "2026-11-26T10:10:56.582383+00:00", "level": "INFO", "service": "observable-agent", "instance": "40bac56038fa", "event": "http_request", "trace_id": "f4d74e984a9653e20dcc3bcaa8ffe3f7", "span_id": "ade89ddc7880d0ce", "request_id": "d650e90d5b16", "method": "POST", "route": "/ask", "status": 200, "ms": 2042.1}
```

Trace lỗi (ảnh `jaeger-error-trace.png`), `trace_id` = `d9e1bbd454fef1fc9a6f3fb5565cf282`, 115.8 ms, span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception`. Log cùng `trace_id`:

```json
{"ts": "2026-11-26T10:15:42.291994+00:00", "level": "INFO", "service": "observable-agent", "instance": "40bac56038fa", "event": "llm_error", "trace_id": "d9e1bbd454fef1fc9a6f3fb5565cf282", "span_id": "ab5c529090d566a0", "request_id": "8cd845c51bba", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T10:15:42.293454+00:00", "level": "INFO", "service": "observable-agent", "instance": "40bac56038fa", "event": "http_request", "trace_id": "d9e1bbd454fef1fc9a6f3fb5565cf282", "span_id": "ab5c529090d566a0", "request_id": "8cd845c51bba", "method": "POST", "route": "/ask", "status": 503, "ms": 114.7}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh (từ `production/`):

```bash
docker compose -p k5-day14-observability up -d --scale agent=1
docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_1
docker compose -p k5-day14-observability up -d --scale agent=3
docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_3
```

Số liệu là dòng `POST /ask` trong [`benchmark-results/scale_1_stats.csv`](benchmark-results/scale_1_stats.csv) và [`benchmark-results/scale_3_stats.csv`](benchmark-results/scale_3_stats.csv):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 64.16 | 200 | 350 | 1700 | 63 / 7111 (0.89 %) |
| 3 | 64.30 | 200 | 240 | 1700 | 69 / 7122 (0.97 %) |

Tất cả lỗi đều là `503 Service Unavailable` từ mock LLM (`scale_*_failures.csv`), đúng tỉ lệ lỗi nền ~1 %.

> ⚠️ **Lỗi trong lệnh của đề (đã tự phát hiện và đo lại):** lệnh gốc `docker compose run --rm locust ...` (không có `--no-deps`) khởi động lại các service phụ thuộc (locust → nginx → agent) và đưa `agent` về `replicas: 2` khai báo trong `docker-compose.yml`. Lần chạy đầu: "scale 1" thực tế bị tạo thêm `agent-2`, "scale 3" thì `agent-3` bị xoá (log Compose: `agent-2 Creating` / `agent-3 Removed`; Prometheus: `172.21.0.9` nhận 0 request). Cả hai lần đều chạy với **2 instance** nên không so sánh được. Đã đo lại với `--no-deps` và kiểm tra trước/sau mỗi lần: scale 1 chỉ có `172.21.0.7` nhận 7356 request; scale 3 có 3 instance nhận 2419 / 2403 / 2433 request. File CSV nộp là của lần đo lại.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **RPS gần như không đổi (64.16 → 64.30)** vì RPS bị giới hạn bởi **chính kịch bản tải**, không phải bởi server. Mỗi user Locust nghỉ `between(0.5, 2)` s (trung bình 1.25 s) giữa các request, cộng ~0.25 s chờ response, nên 100 user chỉ tạo tối đa ~100 / 1.5 s ≈ 67 req/s (tính cả `/health`: tổng 70.2 / 70.3 req/s). Hệ thống đã phục vụ hết tải đưa vào ở cả hai cấu hình; muốn đo throughput tối đa phải tăng số user tới khi RPS ngừng tăng.
- **p95 cải thiện rõ: 350 → 240 ms (−31 %)**, p90 240 → 220 ms. Với 1 instance (giới hạn 0.5 CPU), ~64 req/s làm instance gần bão hoà CPU: request xếp hàng chờ event loop (parse JSON, Pydantic, tạo span, log JSON, metrics), nên phần trên của phân phối bị kéo dài. Đây cũng là lý do trace chậm nhất ở 4.3 có ~268 ms ngoài `agent.run`. 3 instance chia tải còn ~21 req/s mỗi instance, hết xếp hàng, p95 về gần mức "thuần LLM" (LLM p95 ≈ 199 ms).
- **p50 (200 ms) và p99 (1700 ms) không đổi:** p50 chính là latency của LLM mock (~120 ms + jitter + token), p99 là các request "slow" của LLM (+1.5 s). Thêm instance không làm LLM nhanh hơn.
- **Nút thắt chính là LLM upstream:** panel "LLM latency p95" và trace đều cho thấy span `chat ...` chiếm 80–90 % thời gian request. Scale ngang chỉ giải quyết phần xếp hàng CPU ở agent. Muốn giảm p50/p99 phải xử lý phía LLM: model nhanh hơn, cache câu trả lời, streaming, timeout + retry/hedging cho request chậm, hoặc rút ngắn prompt.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối, percentile thì không, nhưng percentile cần đủ mẫu.** Ở `MOCK_SLOW_RATE=0.03`, avg chỉ tăng 1.5 lần trong khi p99 tăng 7.4 lần. Nhưng với 300 request, p95 lúc 224 ms lúc 1660 ms chỉ vì tỉ lệ request chậm dao động 3.0–5.4 % quanh ngưỡng 5 %. Muốn kết luận về p95/p99 phải chạy đủ lâu và nhiều lần, và kiểm tra lại chính công cụ đo (lệnh `docker compose run` của đề làm sai số instance).
  2. **Metric hạ tầng không đo được chất lượng.** Đổi sang v1 (accuracy 91 % → 4 %) làm dashboard *đẹp hơn* (nhanh, rẻ, không lỗi) và không alert nào kêu. Phải có eval trên golden dataset làm quality gate trong CI, và theo dõi "cost / câu đúng" thay vì "cost / câu" (v2 rẻ hơn v1 ~11 lần tính theo câu đúng).
  3. **Mỗi tầng chỉ thấy những gì nó xử lý; 3 trụ cột phải nối với nhau.** Khi pause 1 instance, client nhận 504 nhưng error rate của agent vẫn xanh. Dashboard cho biết *có vấn đề* (p95 tăng), trace cho biết *ở bước nào* (span LLM 81.7 %), log có `trace_id` cho biết *chi tiết*. Ngưỡng alert cũng phải hợp với lưu lượng thật: alert chi phí 2 $/giờ firing ngay ở tải bình thường.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Tầng load balancer / bên ngoài:** metric Nginx (5xx, 502/504 theo upstream, upstream response time) và **synthetic check** từ ngoài gọi `/ask` định kỳ, để bắt các lỗi như thí nghiệm D.
  - **Chất lượng:** online eval định kỳ trên golden dataset, đẩy `agent_eval_accuracy` thành gauge và alert khi giảm; tỉ lệ retrieval miss / câu trả lời fallback; phản hồi 👍/👎.
  - **SLO theo error budget burn rate** (multi-window, ví dụ 1 h và 6 h) thay cho ngưỡng cố định, để vừa bắt sự cố nhanh vừa tránh alert fatigue; alert chi phí theo **% ngân sách ngày đã dùng** và theo **cost / request**, thay vì 2 $/giờ tuyệt đối.
  - **Saturation:** CPU/memory của container (cAdvisor), độ dài hàng đợi / in-flight theo instance, alert khi in-flight cao kéo dài (dấu hiệu cần scale).
  - **LLM upstream:** tỉ lệ 429/timeout của provider, số lần retry, TTFT (time to first token) nếu streaming; alert riêng cho lỗi upstream để phân biệt với lỗi code của agent.
  - **Deploy:** annotation deploy trên Grafana + rolling update có readiness gate, tránh 285 lỗi 502 như khi Compose tạo lại cả 2 instance cùng lúc.
