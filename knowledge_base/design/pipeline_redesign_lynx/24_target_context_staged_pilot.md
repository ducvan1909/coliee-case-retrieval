# Pilot tách TARGET và CONTEXT

## Mục tiêu và giới hạn

Giảm lỗi ownership bằng cách tách quyền tạo proposition chính khỏi quyền bổ sung context. Đây là phương án thử nghiệm, chưa thay mặc định của pipeline. Giữ cùng Qwen 9B, nguồn và 32 TARGET của đợt đối chứng kế hoạch 23; không đổi model, reranker hoặc AU–NN matching. Đợt triển khai này chỉ kiểm thử local; chưa gọi inference/deploy mới.

Đầu vào tham khảo:

- `23_input_target_presentation_audit_plan.md`.
- `knowledge_base/pipeline_v1/outputs/au_method_audit_20261014/RESULT.md`.
- Manifest presentation đã khóa và workload G của `au_context_paired`.
- Module `au_presentation_paired`, `au_context_paired` và nguồn/atom store hiện có.

## Luồng thực hiện

1. Host kiểm source hash, offsets và binding; lấy đúng phần TARGET trong từng atom. Atom giao ranh giới phải được cắt theo span TARGET, không đưa `CONTEXT_PADDING` vào lượt đầu. Các đoạn cắt giữ tham chiếu atom gốc và offset do host xác định.
2. Lượt TARGET-only chọn nhiều neo AU từ tập ID host cung cấp, `kind`, claim dự kiến ngắn và nhu cầu context. Không ép negative khi thiếu thông tin; có thể `needs_context` mà chưa chọn được neo. Claim dự kiến chưa phải kết luận pháp lý đã xác minh.
3. Với AU đủ thông tin, host lưu kết quả dự kiến mà không phát sinh lượt context. Với AU cần context, host lấy context trong packet nguồn đã khóa cho pilot. Lượt bổ sung nhận neo/proposition đã khóa và nguồn bổ sung; không nhận quyền tạo AU chính mới.
4. Lượt bổ sung chỉ giữ, loại, giữ unresolved hoặc bổ sung condition/exception/speaker/scope kèm evidence. Không thay primary claim/primary span. Nếu thấy proposition mới trong context, ghi đề nghị lịch đọc riêng; không materialize thành AU của TARGET hiện tại.
5. Nếu chưa có neo ở lượt đầu và quyết định là needs_context/unresolved, đưa thẳng vào revisit queue, không gọi lượt context. Context không có quyền tạo primary nên lượt này không giúp giải quyết thiếu neo. Không lấy context làm primary, không ép negative và không tự mở request xem lại. Tách loại này trong báo cáo coverage để tránh coi unresolved là tiết kiệm hoặc negative đúng.
6. Host tạo record AU gồm primary evidence thuộc TARGET, contextual evidence với vai trò riêng, source/hash/offset, draft claim và supplements, trạng thái ngữ nghĩa chưa xác minh. Grammar/ID/offset PASS không chứng minh ownership về ngữ nghĩa.

## Batch và vận hành

- Batch ở cấp job: mỗi request một TARGET, không ghép nhiều TARGET trong prompt.
- Tối đa C4 job độc lập đang xử lý; lượt bổ sung chỉ xuất hiện khi lượt đầu yêu cầu. Không tăng replica hoặc thay cấu hình endpoint trong đợt local này.
- Mỗi TARGET tối đa hai lượt ngữ nghĩa. Retry transport được tính riêng trong trần request/token, không reset khi resume.
- Cache theo source hash, chính xác span/context, model/config, prompt/contract và code version. Receipt hợp lệ không gọi lại; thay binding chặn dùng kết quả cũ.
- Ghi checkpoint trước dispatch, job ID ổn định, lưu response và usage kể cả lỗi. Request chưa rõ đã được nhận không được gửi lại mù; dùng cơ chế retrieve/idempotency hiện có.
- Lỗi một TARGET không xóa AU hợp lệ của TARGET khác; unknown usage không ghi thành 0.
- Dùng `.env` hiện có trong `knowledge_base`; không ghi credential vào manifest/report.

## Kiểm thử và đối chứng

Local phải kiểm: không leak context vào lượt đầu; atom giao ranh giới; nhiều AU; neo/ID không hợp lệ; cấm đổi primary và cấm tạo AU từ context; thiếu neo không bị ép negative; evidence có nguồn chính xác; cache/resume; binding/invalidation; giới hạn batch; lỗi cục bộ; checkpoint trước POST; accounting cả lỗi/retry.

Remote là đợt riêng sau kiểm local. So packet hiện tại và staged trên cùng TARGET/model; tính tất cả lượt, source lặp, output, retry và context request. Không thay negative controls hoặc loại TARGET khó. Đánh giá ownership, attribution, qualification, omission và coverage, đồng thời tổng token/request/latency. Trạng thái chạy complete chỉ chứng minh các job đã có kết quả cuối, không chứng minh AU đúng.

Không khẳng định tiết kiệm: nếu đa số TARGET cần lượt hai, chi phí có thể tăng. Phải báo tỷ lệ cần context và tỷ lệ unresolved không neo. Không promote kiến trúc trước khi so chất lượng và chi phí tương ứng.

## Chỉ số bắt buộc khi chạy thử sau này

- Số TARGET đủ ngay / có neo cần context / thiếu neo / negative / lỗi giao thức.
- Số AU và số TARGET gặp ownership, attribution, qualification, omission; kiểm từ nguyên văn, không chỉ từ ID hợp lệ.
- Source character và input/output token của từng lượt; context lặp; usage không xác định; retry và run không hoàn tất.
- Thời gian preparation local, readiness, inference, polling và tổng elapsed; concurrency thực, cache hit và resume.
- So với P0 trên cùng 32 TARGET: không loại trường hợp unresolved khỏi mẫu. Receipt cũ chỉ dùng làm đối chiếu khám phá; nếu cần kết luận công bằng về phiên bản prompt mới, chạy baseline mới trong một đợt được cho phép riêng.
- Không ghi benefit ownership là chứng minh giảm attribution: một proposition đúng TARGET vẫn có thể là lời được trích dẫn hoặc lời đương sự.

Stage 2 chỉ chạy cho TARGET đã có neo cần context; lấy nguồn từ context packet G đã khóa, không phải agent tự tìm trên toàn bản án. Điều này kiểm tra sự tách vai trò trước; hiệu quả tìm context xa hoặc navigation cần phép thử riêng. Primary claim được khóa có thể vẫn sai từ lượt đầu; stage 2 có thể loại/giữ unresolved, nhưng không tự sửa claim để tránh che lỗi. Cần báo tỷ lệ này và đánh giá có nên thêm quyền revisiting trong bước sau.

## Sửa contract v2 sau smoke — 2026-10-14

Smoke `staged_eval_20261014_170122` có reason dài 538 ký tự (host giới hạn 300), JSON và finish_reason hợp lệ. Model cũng bỏ holding cụ thể vì đòi có rule tổng quát; lượt context không có neo chỉ trả unresolved. Đây là hai vấn đề khác nhau: ràng buộc output và ngữ nghĩa extraction.

- Giữ field `reason`, nhưng dùng enum hữu hạn ở `contracts.py`, grammar khóa mã theo decision, validator kiểm lại. Host dựng `reason_text` tiếng Việt từ mapping; model không viết đoạn lý do tự do.
- Stage1: `none`, `no_legal_proposition`, `insufficient_target`, `unclear_attribution`, `missing_qualification`, `coverage_incomplete`, `uncertain_eligibility`.
- Stage2: `none`, `context_insufficient`, `primary_not_supported`, `unclear_attribution`, `qualification_unresolved`, `revisit_target_required`.
- Mã không bảo đảm lý do đúng ngữ nghĩa; claim/supplement vẫn cần review từ nguồn. Không nới validator để nhận reason cũ dài.
- Few-shot ngắn, tổng hợp: holding cụ thể không cần rule tổng quát; đối chứng lời đương sự, fact/editorial và người nói chưa rõ. Không đưa đáp án KOS, output reviewer hoặc nguyên văn calibration vào ví dụ.
- Không neo + needs_context/unresolved: revisit queue, 0 lượt context, chưa tự dispatch. Giữ raw source khả dụng, không coi đây là negative hoặc extraction đạt.
- VERSION/STAGE1/STAGE2 lên v2; prepare và output root mới. Không resume v2 bằng workload/ledger v1 hoặc sửa artifact cũ.
- Kiểm thử local trước smoke endpoint mới; giữ 9B, TARGET, cap800, C1–4 và không gọi inference trong đợt sửa code này.
- Nghiệm thu v2: `tests/test_au_target_context.py` **35 test PASS**; report `outputs/au_target_context_reason_v2_test_report.md`. Main mock đủ32 TARGET có32 stage1 +7 stage2 =39 job verified,20 revisit queue, provider requests0. Đây là fixture tổng hợp, không phải số AU hoặc nhu cầu context của model thật.
- Artifact v2 tại `knowledge_base/pipeline_v1/outputs/au_target_context_reason_v2_20261014/`, có workload/preflight, first_execution_report và resume_check (0GET/POST thêm, ledger bất biến). Ngữ nghĩa và grammar trên endpoint chưa đánh giá.

## Triển khai local — 2026-10-14

- Module: `knowledge_base/pipeline_v1/au_target_context/`; contract và grammar mới nằm riêng, không sửa contract cũ hay đường chạy P0/P1.
- CLI: `prepare`, `preflight`, `run` (dry-run mặc định), `run --mock` và remote opt-in `run --execute`; lựa chọn TARGET bằng `--target-id`, concurrency C1–4.
- Bản được Main nghiệm thu: `outputs/au_target_context_20261014/verified_prepare_v2/workload.json`; mock đầy đủ tại `verified_mock_v2/first_execution_report.json`.
- Mock 32 TARGET: 32 lượt đầu, 19 lượt bổ sung, 51/51 job qua protocol, C4 thực tế. Đây là output tổng hợp, không phải extraction ngữ nghĩa và không dự báo tỷ lệ mở context của model thật.
- `verified_mock_v2/resume_check.json`: resume không thêm GET/POST, ledger bất biến; không inference/deploy.
- Lượt mock trước phát hiện đồng hồ `time.monotonic()` trên Windows có độ phân giải không đủ cho backoff 1ms. Module dùng `time.perf_counter()`, không nới guard recovery. Lỗi budget/policy host được giữ pending, không bị client gán nhầm thành provider JSON failure.
- Grammar mới chưa được compile bằng XGrammar hoặc chạy trên endpoint. Cần smoke nhỏ trước full32 và kiểm ngữ nghĩa theo tiêu chí bên trên; không có tuyên bố cải thiện ownership hoặc tiết kiệm từ mock.
- Tester độc lập: `tests/test_au_target_context.py`, **27/27 PASS** trên bản cuối; báo cáo tại `outputs/au_target_context_test_report.md`. Bao gồm ba gate resume trước HTTP, host budget/policy pending, malformed JSON, full32 mock và các kiểm tra đã liệt kê.
