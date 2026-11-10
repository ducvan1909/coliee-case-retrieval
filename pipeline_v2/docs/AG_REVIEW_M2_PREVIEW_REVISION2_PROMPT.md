# Prompt AG — Review bản sửa preview M2 Revision 2

Review độc lập tại `E:/Git/coliee-case-retrieval`, không sửa production hoặc tự triển khai bước tiếp.

## Đầu vào và phạm vi

Đọc AGENTS.md; contract hiện hành `pipeline_v2/docs/plan/SOURCE_CHUNK_INDEX.md` Section 3.5; `docs/M2_PREVIEW_REVISION2.md`; `docs/M2_PREVIEW_REVISION2_TEST_REPORT.md`; code `navigation/`, `m2.py`, profile `configs/m2.json` và tests M2. Bundle mới lấy đúng path nghiệm thu trong tài liệu revision; đối chứng cũ `pipeline_v2/artifacts/m2_navigation_20261105_v1/`. Báo cáo AG cũ ở `pipeline_v2/reviews/m2_navigation_ag_review_v1/` chỉ là nguồn findings để kiểm lại, không mặc định mọi số liệu/lệnh của nó đúng.

Tất cả production/config/raw/M0/M1/bundles/báo cáo lịch sử READ-ONLY. Chỉ ghi scripts, evidence và báo cáo mới dưới `pipeline_v2/reviews/m2_preview_revision2_ag_review_v1/`; nếu đã tồn tại dùng phiên bản mới, không ghi đè. Chỉ đọc train corpus, không labels/gold/test/credential/nguồn ngoài. Không model/API, tải tokenizer/weights, embedding, index hoặc deploy. Dùng `.venv/Scripts/python.exe`; tamper tests chỉ trên bản sao fixture.

Model Qwen3-Embedding-4B tự host Modal đã được chọn, nhưng token/chunk preflight không thuộc lượt sửa preview này. Không coi chưa có token-valid chunks là lỗi preview, cũng không kết luận toàn M2 hoặc live agent ready.

## Sáu phép phân xử chính

1. Opening là cửa sổ nội dung đủ dài trong cap 240 codepoints, không dừng ở dấu chấm đầu tiên của `Pinard, J.`, `Mr.`, `s.`, `1.`. Không dùng danh sách viết tắt khổng lồ để che cơ chế cắt sai.
2. `truncated/start_clipped/end_clipped` mô tả phần meaningful content bị lược; `partial_sentence=null`/boundary chưa xác minh không khẳng định đủ câu từ dấu chấm hoặc lấy hết một unit.
3. Opening/anchor containment được xử lý hai chiều, gộp khi union vừa cap; marker/skipped prefix không làm tạo hai view trùng thừa. Không đòi mọi overlap đều bằng 0: hai cửa sổ bổ sung thông tin có thể overlap nhưng không được containment trùng lặp vô ích.
4. Slot thứ hai ưu tiên anchors chưa được thể hiện; tie-break deterministic. All anchors/source cues vẫn truy cập được, kể cả anchors trước content-start hoặc không được hiển thị. Không gọi anchor chưa nằm trong preview là mất khỏi nguồn/catalog.
5. Dòng chỉ còn placeholder và ngoặc/dấu câu không thành opening. Còn chữ/số có nội dung thì không bị xóa nhầm. Raw và mapping bất biến.
6. Biên word/tag được ưu tiên trong cap; không cắt tag ngắn một cách tránh được. Với từ/tag dài hơn cap hoặc không có biên phù hợp, clipping/visibility trung thực, giữ full evidence refs và exact raw slice; không rewrite hoặc nối chuỗi giả.

## Kiểm tự động toàn corpus và đối chứng

Chạy suite + validator mới một lần, ghi command/output/exit code/elapsed/lỗi/retry. Quét độc lập toàn 7.708 source, không lấy chính builder làm oracle duy nhất:

- Raw/M0/M1 hash, units, heading text và provenance nguyên vẹn.
- Handles, source/unit IDs, parent/neighbors, anchors/source anchors và source-order mapping cũ/mới giữ nguyên; cho phép thay preview refs/absence, preview data và profile fingerprints theo revision đã khai báo.
- Mọi preview khớp raw bytes/UTF-8 spans/hash, <=240 codepoints, tối đa hai/unit; clipping/visibility/evidence refs nhất quán; pagination đầy đủ và drift/tamper bị từ chối.
- Đo trước/sau: short openings còn substantial text phía sau, duplicate/containment views, novel anchor coverage, placeholder+punctuation-only openings, avoidable word/tag cuts. Lưu định nghĩa, numerator/denominator và danh sách case/span có thể tái hiện.
- Phân biệt regex risk count với lỗi semantic đã xác nhận. Không tái sử dụng con số 22,37% cũ như error rate chứng nhận, không coi mọi overlap là defect hoặc đòi display đủ mọi anchor trong hai snippet.
- Dùng API thật `NavigationReader` và các lệnh được `python -m pipeline_v2.m2 --help` công bố. Không ghi test `M2NavigationStore`, `dedup_hits()` hoặc tham số không tồn tại. Tự đếm file seal thực tế và tính hash từ raw, không copy provenance/số liệu cũ.

Regression nguyên văn cần đọc: `011922/p000005`, `051807/u000030`, `080359/u000002`, `068193/p000025`, `014101/p000008`, `048208/p000015`, `081945/u000001`, `015740/u000001`. Tự lấy offsets thực tế từ bundle, vì một số offsets/literal trong report cũ không khớp. Ghi rõ preview cũ, raw continuation, preview mới, cue nào hiện thêm/bị bỏ khỏi display và còn truy cập qua catalog không.

## Review chất lượng trên mẫu

Khóa seed `20261106`, 20 án ngẫu nhiên đều + tối đa 20 án rủi ro khử trùng bằng selected-set chung trước khi đọc raw. Dùng cohort M0 chỉ để loại discovery/holdout IDs khỏi mẫu đọc thủ công; regression đã exposed báo riêng. Không đọc labels. Mẫu rủi ro dựa vào metadata: nhiều anchors, long/cross-unit cues, clipped word/tag fallback, units không preview, context nhiều marker lặp hoặc unnumbered. Chọn tối đa ba vùng/án theo quy tắc khóa trước.

Xem map trước, ghi nó cung cấp gì để agent chọn đọc, rồi mở raw parent/neighbor context. Phân biệt usefulness, ambiguity và integrity; giữ unresolved khi thiếu bằng chứng. Không tự gán tất cả PASS bằng script chỉ kiểm spans/counts. Không suy error rate toàn corpus từ mẫu AI-assisted.

## Bàn giao

Lưu sampling manifest, findings, reviewed regions kể cả vùng sạch/unresolved, raw evidence, scripts và commands/results. Mỗi finding có case/hash/IDs/offsets, nguyên văn, lệnh tái hiện và tác động tới việc agent chọn đọc. Không sửa code trong review.

Kết luận `ready_with_documented_limits`, `fixes_required_before_next_stage` hoặc `insufficient_evidence`: sáu lỗi đã giải quyết tới đâu, còn gì phải sửa, phần nào chỉ là giới hạn snippet. Nêu actual unique cases/regions và phạm vi đã kiểm. Chưa tự mở token chunking hoặc Modal workload.
