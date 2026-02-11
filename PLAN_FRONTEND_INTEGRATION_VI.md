# Plan tích hợp Frontend <-> Backend (ưu tiên tiếng Việt + multi-user)

## 1) Mục tiêu
- Người dùng nhập tiếng Việt (có dấu), phản hồi ưu tiên tiếng Việt, dễ đọc.
- Frontend gửi được cả `accessToken` và `userId` để sẵn sàng multi-user.
- Giữ tương thích ngược: client cũ chỉ gửi `prompt` vẫn chạy.
- Có hiệu ứng chờ/streaming rõ ràng, không gây cảm giác treo.

## 2) Hiện trạng đã kiểm tra
- Frontend đang gọi `POST /chat/stream` với body `{ "prompt": "..." }` tại `frontend/app/chat/page.tsx`.
- Frontend hiện chỉ có input `accessToken`, chưa có `userId`.
- Backend `ChatRequest` hiện chỉ nhận `prompt` tại `backend/app/routes/chat.py`.
- Backend đang lấy `user_id` từ JWT `sub` (qua `current_user`), chưa nhận `user_id` từ payload.
- `NEXT_PUBLIC_API_BASE_URL` trong `frontend/.env.local` đã là `http://localhost:8010`, nhưng `frontend/.env.example` còn `8000`.
- Docs có tham chiếu script smoke không còn tồn tại (`backend/scripts/run_chat_stream_smoke.ps1`).

## 3) Phạm vi phase này
- Tập trung tích hợp frontend với backend local (backend vẫn local như yêu cầu).
- Chuẩn bị contract để sau này push public gateway/App Runner mượt.
- Không thay đổi logic nghiệp vụ tài chính trong tools/MCP.

## 4) Thiết kế contract đề xuất
### Request `POST /chat/stream`
```json
{
  "prompt": "Tháng này tôi thấy có giao dịch lạ, bạn kiểm tra giúp.",
  "user_id": "64481438-5011-7008-00f8-03e42cc06593",
  "locale": "vi-VN"
}
```

### Rule xử lý `user_id` (quan trọng để tránh lộ dữ liệu)
- Nếu có JWT hợp lệ:
  - Mặc định dùng `sub` từ token.
  - Nếu payload có `user_id`:
    - Chỉ cho phép khi `user_id == sub`, hoặc có cờ override dev/admin rõ ràng.
    - Nếu không khớp: trả `403` (không silently override).
- Nếu `DEV_BYPASS_AUTH=true`:
  - Cho phép nhận `user_id` từ payload (fallback `demo-user` nếu rỗng).
- Nếu client cũ không gửi `user_id`: vẫn chạy bình thường (backward compatibility).

### Rule xử lý `locale`
- Nếu `locale=vi-VN`: agent ưu tiên trả lời tiếng Việt.
- Nếu không truyền `locale`: giữ behavior hiện tại (dựa vào prompt language detection).

## 5) Plan triển khai chi tiết
## Phase A - Backend contract + an toàn truy cập user
- [ ] Mở rộng `ChatRequest` trong `backend/app/routes/chat.py`:
  - `prompt: str` (giữ nguyên)
  - `user_id: Optional[str] = None`
  - `locale: Optional[str] = None`
- [ ] Thêm hàm resolve `effective_user_id`:
  - Ưu tiên JWT `sub` khi auth bật.
  - Cho phép payload override chỉ khi đúng rule bảo mật.
- [ ] Forward `user_id`, `locale`, `authorization` xuống runtime payload.
- [ ] Thêm log chẩn đoán tối thiểu: trace + source user_id (token/payload/dev).
- [ ] Giữ tương thích ngược cho mọi client cũ.

Tiêu chí pass Phase A:
- [ ] Gửi chỉ `prompt` vẫn 200.
- [ ] Gửi `prompt + user_id` hợp lệ vẫn 200.
- [ ] `user_id` không khớp token bị 403.

## Phase B - Frontend form + UX tiếng Việt
- [ ] Cập nhật `frontend/app/chat/page.tsx`:
  - Thêm input `userId` cạnh `accessToken`.
  - Lưu `jars_user_id` vào localStorage.
  - Request body gửi `{ prompt, user_id, locale: "vi-VN" }`.
- [ ] Toàn bộ label/hint chính trong trang chat dùng tiếng Việt rõ ràng.
- [ ] Thêm validate nhẹ trước khi gửi:
  - Nếu có token nhưng thiếu userId: cảnh báo mềm (vẫn cho gửi nếu muốn).
  - Nếu userId có khoảng trắng/ký tự lạ: highlight input.

Tiêu chí pass Phase B:
- [ ] Có thể đổi userId trực tiếp trên UI mà không sửa code.
- [ ] Refresh trang vẫn giữ token/userId.
- [ ] Prompt tiếng Việt có dấu hiển thị đúng, không vỡ UTF-8.

## Phase C - UI dễ nhìn + animation lúc chờ
- [ ] Thêm trạng thái loading rõ:
  - Typing indicator 3 chấm (CSS keyframes).
  - Skeleton bubble cho assistant khi chưa có token stream đầu tiên.
  - Nút `Gửi` chuyển sang `Đang phản hồi...` + disabled.
- [ ] Tách block metadata (trace/tools/citations/mode/fallback) thành card dễ quét.
- [ ] Giữ layout mobile-first (input không tràn trên màn nhỏ).

Tiêu chí pass Phase C:
- [ ] Người dùng luôn thấy trạng thái chờ, không cảm giác đơ.
- [ ] UI đọc dễ trên desktop và mobile.

## Phase D - Test + checklist kết nối
- [ ] Backend unit/integration:
  - Contract parse (`prompt`, `user_id`, `locale`).
  - Rule auth `user_id` (match/mismatch).
- [ ] Frontend manual smoke:
  - Prompt VI có dấu: anomaly/planning/summary.
  - Kiểm tra metadata SSE hiển thị đúng.
- [ ] E2E local:
  - Frontend local (`:3000`) -> Backend local (`:8010`) -> runtime.
  - Case bắt buộc: anomaly phải gọi `anomaly_signals_v1`, không `suitability_refusal`.
- [ ] Ghi kết quả vào file test (`test_results_runtime_stream.txt` hoặc file mới riêng frontend).

## Phase E - Chuẩn bị push public gateway/App Runner
- [ ] Đồng bộ env:
  - Frontend: `NEXT_PUBLIC_API_BASE_URL=<public-backend-url>`
  - Backend: `DEV_BYPASS_AUTH=false` ở môi trường public.
- [ ] Cập nhật docs:
  - Sửa `frontend/.env.example` port chuẩn `8010` cho local.
  - Bỏ/đổi tham chiếu script smoke không còn tồn tại.
  - Thêm mục “khuyến nghị luôn gửi `authorization` khi invoke trực tiếp runtime”.
- [ ] Rollout theo bước:
  1. Deploy backend trước (hỗ trợ `user_id`, `locale`).
  2. Deploy frontend sau (gửi field mới).
  3. Smoke 3 case tiếng Việt trên môi trường public.

## 6) Danh sách thiếu cần xử lý trước khi connect trơn tru
- [ ] Thiếu contract `user_id` ở backend `/chat/stream`.
- [ ] Thiếu input `userId` ở frontend chat.
- [ ] Chưa có ràng buộc bảo mật khi client truyền `user_id`.
- [ ] `frontend/.env.example` đang lệch port mặc định.
- [ ] Docs còn trỏ tới script smoke đã mất.

## 7) Risk và phương án giảm thiểu
- Risk: Cho phép override `user_id` bừa bãi gây đọc nhầm dữ liệu user khác.
  - Mitigation: enforce match `user_id == sub` (trừ dev/admin mode).
- Risk: Prompt tiếng Việt có dấu bị lỗi encoding ở shell/tooling.
  - Mitigation: test qua frontend browser + JSON UTF-8, tránh copy/paste qua terminal khi verify.
- Risk: Gateway public dùng backend cũ không nhận field mới.
  - Mitigation: giữ backward-compatible, deploy backend trước frontend.

## 8) Definition of Done (DoD)
- [ ] Frontend chat có 2 field: `AccessToken` và `UserId`.
- [ ] `POST /chat/stream` nhận `prompt + user_id + locale` (không phá client cũ).
- [ ] Prompt tiếng Việt có dấu trả lời tiếng Việt ổn định trong các case chính.
- [ ] Có loading animation rõ ràng trong lúc chờ stream.
- [ ] Có test evidence local + ghi file kết quả.
- [ ] Docs/env được cập nhật để dev khác chạy lại không vướng.
