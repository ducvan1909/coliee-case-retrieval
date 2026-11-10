# Kiểm thử M2 token passages

## Code và kiểm độc lập

Implementer đóng băng `passages/`, `m2_passages.py`, `configs/m2_passages.json` và hai file `test_m2_passages_core.py`, `test_m2_passages_store.py` trước full build. Full unittest discover sau freeze: **65/65 PASS, 10,467s**. Tester độc lập chạy targeted core/store: **9/9 PASS, 6,623s**. Count lấy theo runner hiện tại: M0=6, M1 core/store=21/4, navigation core/store=13/4, preview=8, passages core/store=5/4; không cộng số tests của các báo cáo lịch sử để suy count hiện tại.

Tester chạy property checks với tokenizer thật, seed738: **48 đầu vào, 448 passages, PASS, 3,656s**, tối đa389 full-input tokens. Gồm Unicode/BOM U+FEFF, CRLF, emoji/CJK, special-token literals, whitespace và từ dài; kiểm exact re-encoding, no gap, advancing end/start, whole parent<=448 và overlap content-only<=128. Đây là kiểm cơ học, không phải đánh giá usefulness hay nguồn viện dẫn.

Tester phát hiện nguy cơ reader tin upstream profile đã cache; implementer đã sửa bằng fresh NavigationReader khi đọc tương tác, kiểm đầu/cuối build/validate. Tests sửa raw/M1/M2 profile/tokenizer asset sau khi mở cùng reader hiện PASS. Kiểm reseal thay token count bị từ chối. Unknown/quoted/unnumbered/French được giữ nguyên metadata, không coi đó là ownership đã đúng.

## Commands tái hiện

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v
& .venv/Scripts/python.exe -m pipeline_v2.m2_passages build --repo-root . --navigation-bundle pipeline_v2/artifacts/m2_navigation_20261106_v3 --output pipeline_v2/artifacts/THU_MUC_MOI
& .venv/Scripts/python.exe -m pipeline_v2.m2_passages validate --repo-root . --bundle pipeline_v2/artifacts/m2_passages_20261106_v1
& .venv/Scripts/python.exe pipeline_v2/reviews/m2_passages_validation_v1/audit.py --bundle pipeline_v2/artifacts/m2_passages_20261106_v1 --output pipeline_v2/reviews/m2_passages_validation_v1/RESULT_MOI.json
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m2_passages_validation_v1.check_middle_child
```

Output build và audit write-once; chọn tên mới khi tái chạy. Script middle-child cũng ghi result write-once; cần đổi tên output nếu tái kiểm. Corpus audit không import passage builder/reader: đọc raw bytes, JSON và encode bằng backend pinned độc lập. Context regression dùng reader để kiểm hành vi mở thực tế, không lấy chỉ mapping làm bằng chứng đã mở.

## Attempts và giới hạn

- Metadata HTTP đầu tiên bị sandbox proxy từ chối; retry read công khai được phép thành công. Download sáu file tokenizer/config đều HTTP200. Gate đầu dừng khi thấy postprocessor không null; sau đọc processor chính thức, finalize local kiểm hash receipt và chốt một token cuối. Không bỏ processor để làm PASS.
- Một lần fullsuite Main69tests/2errors9,849s và targeted tester13tests/3errors chạy khi implementer vẫn thay code: fingerprints thay giữa fixture build/read. Các attempt không hợp lệ để nghiệm thu, được giữ trong accounting. Sau freeze runner65tests và targeted9tests PASS. Không kết luận production sai từ code bị đổi giữa hai bước kiểm.
- Audit draft đã sửa overlap count từ `add_special_tokens=True` sang `False`: full-input vẫn True. Đây là lỗi của checker trước khi chạy audit final, không sửa production vì lỗi checker.
- Parent lớn nhất được kiểm cơ học: `041666.txt/p000417`,84.205bytes,21.133fulltokens; số child final và kết quả mở middle child phải lấy từ result sau seal, không tái dùng số109 của phép thử trước khi thống nhất overlap content-only.
- Heading/whitespace riêng không tạo embedding standalone; tokenizer agent, endpoint cap, payload ledger và retrieval quality chưa được kiểm. Whitespace fallback chưa được nhận là biên câu/ngữ nghĩa. Retokenize tail có chi phí tăng với parent rất dài.
- Không có inference requests/retries/tokens, tải weights hoặc deploy Modal. Các lượt encode tokenizer local là phép đo input, không phải inference token consumption. Token của chat phát triển không được đo.

## Nghiệm thu toàn corpus

Full build đã exit0:7.708nguồn,382.343parents,415.693passages,9.856splitparents,55.346.360full-inputtokens,max448;921,598s local, wrapper921,792s. Receipt `artifacts/m2_passages_20261106_v1.build-receipt.json`.

Middle-child regression **PASS,16,510s**: largest parent `041666/p000417` final110children,84.205bytes. Mở child giữa trả toàn parent+previousp000416; không có next đúng source boundary. Thử thêm middlechild trong parentp000153 trả previousp000151 và nextp000155 theo source order, raw envelope đúng. Result `reviews/m2_passages_validation_v1/middle_child_result.json`. Attempt đầu script giả định next tồn tại nên KeyError; sửa checker xử lý null boundary và thêm interiorcase, không đổi production hoặc rebuild bundle.

Audit độc lập **PASS trên7.708nguồn,0lỗi,450,474s**. Xác minh lại415.693passages/382.343parents/9.856splitparents/55.346.360fulltokens/4.244.972overlapcontenttokens/max448. GlobalIDs không trùng, raw slices/char-byte/hash/token count/parent coverage/siblings/reading refs/metadata đều đạt. Source headings48.990units481.721bytes và whitespace514.659units1.540.929bytes được đếm là unindexed standalone, không mất khỏi raw. File `reviews/m2_passages_validation_v1/full_corpus_audit.json`.

Validator tái dựng **PASS toàn bộ7.708nguồn,947,305s local** (wrapper947,560s), exit0; summary khớp build và audit. Receipt `reviews/m2_passages_validation_v1/validator_receipt.json`. Không sửa production/profile sau freeze. Tester đã đọc lại summary/build receipt/audit/middle-child result và không thấy sai lệch trọng yếu.

**Kết luận:** nghiệm thu M2 passages local với các giới hạn đã ghi; không chứng nhận semantic ownership/retrieval/endpoint/M4. Bundle cuối `artifacts/m2_passages_20261106_v1/`,7.712files gồm seal,938.891.921bytes. Full build1lần thành công, full validator1lần thành công, full raw/token audit1lần thành công; các lỗi trước đó thuộc acquisition gate/checker/concurrent fixture đã ghi ở trên, không bị xóa khỏi accounting.
