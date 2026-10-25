# Pilot triển khai đọc chọn lọc và so bản cũ

Ngày: 2026-10-13. Phạm vi người dùng cho phép: triển khai và chạy pilot để so sánh, không deploy mới, không toàn corpus hoặc NN–AU joining. Spec04 exhaustive là baseline hiện hành; pilot này là mode thử riêng, không tự thay accepted-AU policy.

## Workload và đối chứng

Khóa đúng 30 target (sáu/án) của `outputs/bulk_trial30_20261013/manifest.json`, cùng source/atom/context và model 9B hiện có. Reference cũ là `bulk/run.json`; `corpus/run.json` dùng kiểm tra độ biến động, không làm gold. Reference hoàn tất 30 target, không phải toàn bộ nội dung năm án.

- H: host xếp priority từ tín hiệu local, chọn hai vùng và thêm một vùng discovery độc lập mỗi án.
- P: planner chọn hai vùng từ sáu lựa chọn bounded mỗi án; host thêm discovery độc lập ngoài lựa chọn. Model được thấy toàn bộ sáu lựa chọn của pilot, không bị giới hạn bởi shortlist priority.
- Mỗi arm ban đầu tối đa 15 extraction. Không gộp nhiều target trong một prompt AU; đây là batch kế hoạch đọc, không phải B2 multi-target extraction.
- P tối đa một replan/án khi có trigger. Mỗi arm tối đa một context expansion/án, 1.200 ký tự bổ sung, tìm vùng xa trong cùng source khi cần. Phần ngoài universe30 chỉ là CONTEXT, chưa đánh giá thành target mới.
- Nguồn không citation/heading không bị loại khỏi discovery. Preview trong block dài chỉ điều hướng; không tạo LegalUnit partition hoặc accepted AU từ fragment.

## Model và vận hành

Qwen/Qwen3.5-9B hiện tại, thinking false, app bulk C4 đã deploy. Planner dùng finite lựa chọn ID và reason enum, host kiểm tra; extraction giữ prompt/schema/EBNF/normalizer AU hiện tại, output800, cho phép nhiều AU. Không thêm model, train, verifier hoặc bộ field assessment phình output.

Host chuẩn bị navigation, raw previews tối đa ba đoạn120 ký tự/vùng, source refs/hash và catalog. Preview/search hit không thành evidence. Navigation ID và request-scoped evidence ID khác domain; source refs bất biến.

Pipeline thử: khóa nguồn → overview/options → H hoặc P batch plan → vùng nguyên văn → AU proposal → context/replan theo trigger → assessment ledger và checkpoint. Các region độc lập được dispatch C4; không coi chuỗi phụ thuộc trong một án là bốn lượt độc lập.

## State, publication và cache

Ledger tách exposure/delivery, assessment exact TARGET intervals và kết thúc run. Chưa chọn = not_assessed, không no-AU. Protocol-fail hoặc obligation chưa giải quyết = unresolved. Context delivery không tự thành target assessment. AU host-valid vẫn semantic_review_pending; không tự materialize accepted citation view.

Reservation/group ID và request fingerprint khóa source/map/render/prompt/schema/model/policy/seed/catalog. Receipt bền vững trước assessment/ledger/cost commit; next intent sau commit. Resume lấy cùng group/request ID, không inference lại kết quả hợp lệ; unknown chặn dispatch tự động. Cache/resume được báo riêng, không dùng làm fresh speedup.

## Giới hạn pilot

Không có USD/request giả định. Manifest đặt trần request H30/P35 (planning/replan/extraction/expansion); warmup báo riêng. Mỗi request input bảo thủ11488 UTF-8 bytes, output800. Tổng input estimate200000 bytes/arm, actualinput100000 tokens và output30000 tokens. Estimate không phải provider token; reserve và actual phải được ghi riêng. Hết cap lưu partial, không tính là tiết kiệm thành công. Các trần này là giới hạn vận hành, không khẳng định đã đạt mục tiêu25/50/75% cost.

## Kiểm tra và so sánh

Local trước: hash/offset, ID, finite selection, duplicate/invalid planner, source preview vs evidence, exact intervals/partial negative, context/replan caps, budget trước dispatch, cost có planner/errors/unknown, receipt/assessment/recovery, selection không đọc reference output.

Sau local PASS, chạy H rồi P trên endpoint hiện tại; ghi mọi lỗi/usage/setup. Không đọc gold/KOS hoặc output cũ khi selection. So target đã assessed, positive reference chưa chọn, positive đổi decision, AU evidence/content matches và các khác biệt cần review nguồn. Exact signature không nhận diện paraphrase semantic và không phải true AU recall. Không nghiệm thu equivalent quality chỉ vì protocolPASS hoặc AU counts.

So tổng token có planning/context/repair/error và warmup đã báo; không trừ input theo prefix cache. Thời gian khác lượt/cold-start không là bằng chứng nhân quả. Nếu read ít nhưng bỏ nhiều positive reference/qualification, hoặc planning overhead không có lợi, không nâng selective mode thành default.

Không mở query-time rescue hoặc reranker trong pilot. Những AU ngoài universe30 hay chưa assessed vẫn giữ nguyên trạng thái, không tính vào coverage.

## Sửa từ live smoke

Run đầu tại `outputs/selective_trial30_20261013/H` xử lý4 request, 3 hợp contract và một target bị host từ chối do claim301/353 ký tự vượt max300. Ghi nhận9.923 token source requests và18 token warmup; run chưa hoàn tất, không phải tiết kiệm thành công. Artifact giữ nguyên.

Runner đã sửa: known host/schema failure chỉ giữ target đó unresolved, tiếp tục các target độc lập; unknown provider outcome/usage/budget vẫn chặn admission toàn cục. Invalid planner không fallback chọn vùng, chỉ để case đó chưa có kế hoạch hợp lệ. Không nới maxLength hoặc cắt claim. Ba regression bổ sung kiểm tra các nhánh này.

Pilot đo tiếp dùng manifest mới `outputs/selective_trial30_fix1_20261013/manifest.json`, cùng universe/seed nhưng request ID mới để không tính receipt cũ là throughput mới. Báo riêng overhead run đầu; không bỏ chi phí thất bại khỏi tổng đợt thử.

P đã lưu24 request (15 extraction, 9 planning/replan), 62.719 token, rồi dừng trước4 vùng replan vì tổng estimate byte chạm200000, dù trần token thực còn đủ. Resume có cờ `--resume-input-estimate-bytes 260000` dành riêng checkpoint budget-stop đã có đủ receipt/usage, không pending/unknown. Một migration fingerprint hẹp chỉ chấp nhận version runtime đã biết, và mọi source/model/prompt/schema/policy/catalog khác phải giống hệt. Manifest caps gốc được giữ, guard thực tế và migration ghi riêng; actualinput100000/output30000/request35 không tăng. 24 receipt được reuse, không gọi lại. P là run resumed nên không dùng wall để tuyên bố fresh speedup.

## Kết quả live và quyết định

H complete15 target,36884 token, giữ6/16 positive targets của reference; P complete19 target,76755 token (9planner/replan27970 +20extraction/context48785), giữ11/16 referencepositive. H giảm token nhưng omission lớn; P cao hơn reference9,2% token. Reference không phải gold; P resumed không là fresh latency evidence. Không thay exhaustive default hoặc mở rộng corpus. Hướng tiếp là nén planner metadata, cải thiện objective/selection và đối chứng budget, chưa implement thêm trong đợt này. Báo cáo: `pipeline_v1/outputs/selective_trial30_fix1_20261013/RESULT.md` và `FINAL_REVIEW.json`.
