# Phản biện đọc chọn lọc — 2026-10-13

Trạng thái: review đề xuất, chưa sửa kiến trúc hiện hành hoặc runtime. Hai agent tester_advanced đọc độc lập, mỗi bên nộp tám phản biện và thiết kế tối thiểu, sau đó kiểm tra chéo một vòng. Không chạy test, inference hoặc deploy trong review. Main xác minh lại ví dụ nguồn 000031 [27]–[28] và [59]. Đồng thuận agent không phải validation.

## Hồ sơ

- [Agent A: thông tin, AU và coverage](agent_a_initial.md)
- [Agent B: token, công cụ và vận hành](agent_b_initial.md)
- [A kiểm tra phương án B](agent_a_crosscheck.md)
- [B kiểm tra phương án A](agent_b_crosscheck.md)

Đề xuất gốc: host tạo source/map/local cues và overview; agent chọn vùng qua tool rồi đọc/trích AU/mở context; nguồn chưa đánh giá giữ not_assessed; có priority/discovery và checkpoint; không bắt LLM đọc mọi block; query-trigger extraction chỉ là giao diện tương lai. SourceBlock/AnalysisRegion vẫn giữ nguyên, không LegalUnit partition hoặc heading giả. Phần gốc nằm trong cuộc trò chuyện; tài liệu này lưu review, không thay spec04.

## Phân xử của Main ở mức đề xuất

| Chi tiết | Kết luận | Lý do và phép thử |
|---|---|---|
| Local source map, raw preview, pagination | Giữ, bổ sung cap | Không LLM-summary toàn án; preview có source/version/selector; cap mỗi trang, tổng trang/search. Thử AU giữa block, thiếu heading, không citation |
| Agent chọn từng vùng rồi planning sau mỗi vùng | Không làm mặc định | Có nguy cơ nhân prompt/catalog/history và lượt gọi; batch-plan trước, replan hữu hạn theo trigger |
| Shortlist của host | Sửa | Không trở thành hard filter. Discovery độc lập và quyền điều hướng ra ngoài shortlist trong cap; đo recall lựa chọn ngoài shortlist |
| Priority + discovery | Giữ nhưng không chứng nhận coverage | Discovery cả vùng trong block dài theo địa chỉ SentenceAtom; không đổi canonical SourceBlock, không tự biến fragment thành AU. Dedup spans và so chi phí với wide-read |
| Mở context chỉ lân cận | Sửa | Cho tìm antecedent/response/qualification xa. Thử batch context-resolution so expansion tuần tự; search hit chỉ điều hướng |
| Bốn state semantic cấp block | Sửa | Ledger canonical theo exact intervals, tách exposure/delivery, assessment và run termination. Block state chỉ projection partial/mixed |
| ID/tool selection từ Plan12 | Reuse cơ chế, không reuse nguyên contract | Navigation IDs chọn nguồn chưa đọc; evidence IDs chỉ thuộc read catalog snapshot. Thử stale ID, overflow và context promotion |
| Assessment + next action | Cần chốt transaction trước implement | Receipt/proposal/ledger/obligation/cost commit trước next intent; không redispatch unknown. Không bắt buộc ghép wire phức tạp trong pilot đầu |
| Host-valid AU tự thành accepted | Bác bỏ | Source/offset/schema đúng không chứng minh support. Giữ host_valid, model assessment và publication policy/provenance riêng; không thêm verifier mặc định hoặc hạ gate semantic |
| Thêm năm bộ status/witness cho mọi AU | Cần đối chứng trước chốt schema | Giúp biểu đạt bất định nhưng có thể phình output hoặc model chọn not_applicable giả; phải đo dưới cap, không sửa AU wire ngay trong review |
| Stop khi đủ discovery hoặc hết budget | Sửa | Quota chỉ thỏa policy; hết budget là trạng thái riêng, không complete assessment. Liệt kê unread và unresolved |
| Query về sau chắc chắn cứu AU bỏ sót | Bác bỏ như bằng chứng hiện tại | Source-selection tương lai chưa chốt; không cộng khả năng giả định vào coverage. Raw block vẫn không là citation candidate |
| 25/50/75% token của ~70k hiện có | Chỉ áp dụng workload30 tương ứng | 30 target không phải exhaustive toàn năm án; cần denominator nguồn/workload đúng, tính mọi planning/source/catalog/output/error/repair/resume |

## Hướng thử khuyến nghị, chưa triển khai

1. H: host đề xuất vùng từ cues và discovery; extraction model hiện tại đọc vùng đó. Đây là baseline chi phí thấp, không có quyền kết luận no-AU cho vùng bị bỏ qua.
2. P: agent nhận overview và gói lựa chọn bounded, chọn một nhóm vùng trong một lượt; có quyền đề nghị điều hướng ngoài shortlist. Host dispatch các vùng độc lập bằng AU extraction hiện tại. Replan chỉ khi có obligation, discovery mới hoặc kế hoạch cạn mà policy chưa thỏa.
3. I: full interactive loop là arm nghiên cứu sau; chỉ giữ nếu lợi ích selection/context bù toàn overhead và lỗi mới.

Với mục tiêu cho model lựa chọn, P là prototype cần đánh giá cạnh H; không mặc định H hoặc P đủ tốt. Chưa chọn model mới: 9B là ứng viên thử planner, extraction PASS không chứng minh planning tốt. Giữ C4 cho các vùng độc lập, không đồng nghĩa bốn lượt phụ thuộc của một án có thể chạy song song.

## Những quyết định còn cần trước triển khai

- Preview/page/search caps và quyền điều hướng ngoài shortlist.
- Interval ledger; source delivered khác assessed; policy dừng.
- Navigation/evidence identity và catalog invalidation.
- Budget reservation và assessment/next-intent transaction/recovery.
- Publication policy AU: không đánh đồng host-valid hoặc model-only assessment với xác minh độc lập.
- Workload/baseline tương ứng và tiêu chí giữ/bỏ planner. Không mở inference hoặc bổ sung human annotation tự động.

Mục tiêu pilot: đo khả năng lựa chọn, omission so reference, preservation của condition/attribution, total token/request/latency/setup/error/reuse. Khi chỉ có model-silver/reference output, báo agreement/retention và phản ví dụ; không báo true AU recall hay chứng nhận chất lượng tương đương. Nguồn exhaustive cũng không bảo đảm baseline model đúng.

Điểm chưa giải quyết bằng review: một AU hiếm nằm ngoài preview/cues có thể không được chọn; nghĩa vụ ngữ nghĩa chưa phát hiện không hiện trong ledger; tự review cùng model có lỗi tương quan. Vì vậy đây là hướng chọn đọc có rủi ro được đo, không phải bảo đảm đủ AU toàn corpus.
