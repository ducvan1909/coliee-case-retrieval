# Kiểm tra phương pháp trước khi chọn model

## Phạm vi

Dùng workload32 TARGET/34 receipt của kế hoạch22 và kết quả semantic_review_v1.
Giữ model Qwen3.5-9B, revision, source/hash, TARGET, atom catalog, output cap800,
taxonomy/schema/grammar và synthetic few-shots. Không sửa lịch sử để chạy PASS.
Không thêm planner/repair hoặc dùng KOS/reviewer làm input. Chưa mở corpus.

## 1. Audit đủ nguồn — offline

Với từng TARGET và từng packet có khác context, đọc raw source và ghi:
primary proposition thuộc TARGET; điều kiện/exception/limit/speaker cần giữ;
required missing spans nằm ngoài union atom; đủ/thiếu/chưa rõ/không áp dụng.
Không coi rule CONTEXT-only của AU sai là nội dung phải bổ sung cho TARGET.
Evidence ngoài packet chỉ là thiếu khi cần cho proposition TARGET hợp lệ.

Phân biệt sai vì packet thiếu, sai ranh giới, đọc/presentation sai dù đủ thông tin,
và tiêu chí AU chưa chốt. Có thể có nhiều nguyên nhân; không ép mỗi lỗi một nhãn.
Nhãn từ review chỉ dùng đánh giá, không đưa vào renderer hoặc ranker.

## 2. Audit TARGET — offline

Kiểm pure heading/marker/editorial, quotation hoặc legal point bị cắt, mixed voices,
proposition nhiều hơn cap3. SourceBlock là địa chỉ, không tự là AU hay legal unit.
Mixed voice không tự là ranh giới sai nếu các cue rõ; không gọi mọi block dài là lỗi.
Marker vẫn là signal citation nhưng không tự sở hữu proposition. Ghi evidence cụ thể.

## 3. Đối chứng presentation cùng nguồn

- P0: renderer hiện tại theo source order.
- P1: nhóm TARGET trước, CONTEXT sau; giữ source order trong mỗi nhóm, offsets và
  ID không đổi. Đánh dấu reporting cue xuất hiện thực trong source bằng luật cố định,
  không gán speaker/endorsement pháp lý. Dấu quotation chỉ đánh dấu literal delimiter,
  không tự kết luận scope lời trích khi delimiter thiếu.
- Hai arm dùng cùng prompt instructions/few-shots và contract. Legend nếu cần phải
  giống nhau cho cả P0/P1; chỉ body presentation khác. Source xuất hiện đúng một lần
  mỗi atom như P0; không lặp quote thành metadata. Giữ TARGET_BODY/CONTEXT_PADDING.
- Host kiểm round-trip nguyên văn toàn atom, cùng role của từng source character,
  cùng target/atom IDs, không thêm source ngoài packet, không đọc decisions trong build.
- Không thử boundary mới đồng thời: đó là ablation riêng, tránh quy lợi ích cho layout.
- Chọn packet G cho tất cả TARGET để tách khỏi selective-context policy. Hai request
  mới mỗi TARGET, counterbalanced, không trộn cache output cũ vào đối chứng chính.

Chọn trước 8 TARGET đại diện/16 request hoặc đủ32/64 request theo workload người
dùng chọn. Tập nhỏ là diagnostic đã xem output, không held-out. Khóa IDs và lý do
sampling trước output mới. Bao ownership, citation quote/current court, qualification,
negative có holding, negative sạch, heading/marker, mixed voices và target nhiều AU.

## 4. Đánh giá và quyết định

Blind review cùng source checklist; report theo receipt và AU, không dùng số AU
làm chất lượng. Ưu tiên ownership/attribution/qualification/omission; negative reason
sai nhưng quyết định đúng báo riêng. Không ép các AU-eligibility chưa chốt.

Ledger tính mọi prompt/output/reasoning, warmup/probe/retry, local preparation time,
source/context lặp, latency và cache. Provider usage chưa có giữ unknown; local
UTF-8 bytes là reservation, không token chính xác. Chi phí Codex review báo riêng
unavailable khi không có usage; không coi model/local hoặc review là miễn phí.

Nếu packet thiếu hoặc TARGET không phù hợp: sửa đúng nguồn/routing/boundary rồi
đo lại, không đổi model cùng lúc. Nếu P1 cải thiện: đo lợi ích trên tập án mới trước
chọn mặc định. Nếu packet đủ, ownership rõ và P1 vẫn sai: có cơ sở thử model khác,
nhưng chưa chứng minh nguyên nhân chỉ là model. Không ép tiết kiệm khi mất evidence.

## Bàn giao

Audit per-target JSON, missing spans, boundary findings; P0/P1 frozen payloads và
local round-trip invariants; kế hoạch sampling/caps; comparison semantic/cost sau
inference. Audit local không đồng nghĩa đối chứng extraction đã được chạy.

Đầu vào cho Codex: AGENTS.md; kế hoạch22; au_context_paired/{build,review,compare};
au_compact/{core,runner,prompting,decoding}; source_store_v1/plan04_sentence_atoms_v1;
pilot_20261014_084923_recovered_v1/{workload,reference_checklist,live/run}.json;
semantic_review_v1/{blind_review_packet,decisions,comparison,RESULT}.json/md.

## Kết quả thực hiện

2026-10-14: đã audit32TARGET/34packet, không xác nhận missing span thiết yếu;
ghi hai seam kéo heading kế tiếp vào cuối TARGET. Đã prepare và chạy full32TARGET/
64request P0/P1 cùngQwen9B;64/64protocol verified,0retry,167356provider tokens.
Review đủ64receipt/84AU bằng Main và hai reviewer source-first/blind, không human gold.
P1 ownership errors12→3 nhưng attribution6→8,omission7→8; tổng token84439 soP0
82917(+1,84%). Chưa promote P1 hoặc đổi model/mở corpus. Đề xuất tách cue-only và
grouping-only ở phép thử tiếp theo, đồng thời chốt eligibility/reporting voice.
Chi tiết: `knowledge_base/pipeline_v1/outputs/au_method_audit_20261014/RESULT.md`.
Module thử riêng `au_presentation_paired`,14focused tests PASS;Spec04/05 không sửa.
