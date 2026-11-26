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

> CP8, làm sau giờ lab.

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
