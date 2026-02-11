# Plan Fix Runtime Stream (Post-Redeploy)

## 1) Mục tiêu
- Sửa lỗi route/policy khiến tool bị gọi sai ở các case `anomaly` và `planning`.
- Giữ đúng policy deny cho prompt đầu tư buy/sell.
- Nâng chất lượng câu chữ và tính grounded của khuyến nghị dịch vụ.
- Không hardcode số liệu nghiệp vụ, không thêm cơ chế retry nặng.

## 2) Hiện trạng từ `test_results_runtime_stream.txt`
- Runtime ổn định: `12/12` case `HTTP 200`, `runtime=aws_runtime`, `mode=llm_enforce`.
- Sai intent quan trọng:
  - `CASE 06` (giao dịch lạ) bị `suitability_refusal`, chỉ gọi `suitability_guard_v1`.
  - `CASE 09` (mua nhà 1.5 tỷ trong 5 năm) bị `suitability_refusal`.
- Tool selection chưa tối ưu:
  - `CASE 05` (chi cố định) chưa gọi `recurring_cashflow_detect_v1`.
  - Một số case gọi `goal_feasibility_v1` nhưng trả `insufficient_input`.
- Chưa có case nào gọi `anomaly_signals_v1` trong bộ test hiện tại, nên chưa ra ngày bất thường.
- `citations` đang trống trong toàn bộ 12 case.

## 3) Root cause chính
1. `agent/graph.py` (`_requested_action`):
- Regex `\bban\b` bắt nhầm từ đại từ “bạn” => map sai thành hành động `sell`.

2. `src/aws-finance-mcp-server/app/finance/suitability.py`:
- `invest_like` đang quá nhạy với action `buy/sell` mà thiếu ngữ cảnh tài sản đầu tư.

3. `agent/router/policy.py`:
- Override anomaly chưa phủ đủ khi extractor trả sai sang `invest`.
- Một số prompt planning-home-goal chưa được force về `planning`.

4. `agent/graph.py` (`retrieve_kb`):
- Đang lọc KB cứng theo `doc_type=policy`, làm yếu grounding cho service suggestion.

## 4) Kế hoạch triển khai

### Phase 1 - Sửa lỗi routing/policy critical
1. Sửa `_requested_action` trong `agent/graph.py`:
- Bỏ regex đơn `\bban\b`.
- Chỉ map `sell` khi có ngữ cảnh đầu tư rõ (ví dụ: `ban co phieu`, `sell stock`, `ban crypto`).
- Không map `mua nha/mua xe/muc tieu tiet kiem` thành execution action đầu tư.

2. Unit tests bắt buộc:
- `ban kiem tra giup` không thành `sell`.
- `co nen mua co phieu` vẫn thành `recommend_buy`.
- `mua nha 1.5 ty` không thành buy/sell investment action.

### Phase 2 - Siết logic invest-like đúng ngữ cảnh
1. Sửa `suitability_guard` trong `src/aws-finance-mcp-server/app/finance/suitability.py`:
- `invest_like` cần thêm điều kiện tài sản đầu tư (stock/crypto/etf/portfolio...).
- Không deny các prompt planning đời sống (mua nhà, kế hoạch tiết kiệm).

2. Tests:
- Prompt anomaly -> `allow`.
- Prompt planning-home-goal -> `allow`.
- Prompt khuyến nghị mua cổ phiếu -> `deny_recommendation`.

### Phase 3 - Cải thiện router + tool bundle
1. Sửa `suggest_intent_override` trong `agent/router/policy.py`:
- Nếu có anomaly terms và không có invest terms -> override sang `risk`.
- Nếu có planning-home-goal terms -> override sang `planning`.
- Nếu prompt nói về chi cố định định kỳ -> đảm bảo có `recurring_cashflow_detect_v1`.

2. Integration tests:
- `CASE 06` phải gọi `anomaly_signals_v1`.
- `CASE 09` phải route `planning` + gọi goal/planning tools.
- `CASE 05` có recurring tool.

### Phase 4 - Tăng grounding cho service suggestion
1. Sửa `retrieve_kb` trong `agent/graph.py`:
- Không khóa cứng `doc_type=policy`.
- Chuyển filter theo intent hoặc để matcher local tự chọn tài liệu service phù hợp.

2. Acceptance:
- Cases planning/risk/scenario có `citations` non-empty.
- Gợi ý service có chứng cứ từ fact/citation thay vì generic.

### Phase 5 - Làm sạch câu chữ (không hard-protect nặng)
1. Sửa nhẹ post-processing ở `agent/response/synthesizer_bedrock.py`:
- Loại bỏ lặp cụm liên tiếp (ví dụ `chưa khả thi chưa khả thi`).
- Chuẩn hóa diễn đạt số liệu trong một câu, tránh lặp chữ + số.
- Giữ tiếng Việt nhất quán cho prompt tiếng Việt.

2. Không thêm retry vòng mới.

## 5) Bộ test sau fix
1. Chạy lại 12 prompt qua `backend /chat/stream` với runtime.
2. Xuất `test_results_runtime_stream.txt` + `results.txt`.
3. Checklist pass:
- `CASE 06`: route risk, gọi `anomaly_signals_v1`, có anomaly metrics; nếu có change point thì hiển thị ngày.
- `CASE 09`: route planning, không `suitability_refusal`.
- `CASE 08`: vẫn deny recommendation.
- `CASE 05`: có recurring detection.
- Citations xuất hiện ở case cần service.

## 6) Tiêu chí nghiệm thu
- Không còn false-positive deny ở anomaly/planning-home-goal.
- Policy đầu tư vẫn chặn đúng 100% các yêu cầu buy/sell recommendation.
- Tool selection khớp intent ở các case chuẩn.
- Output rõ ràng, không lặp, hạn chế jargon.
- Không hardcode số liệu nghiệp vụ, vẫn grounded theo tool outputs.
