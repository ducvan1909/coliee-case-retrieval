# M2 Preview Revision 2

Revision này sửa cách chọn preview sau review AG. Không sửa raw corpus, M0/M1, unit IDs, handles, neighbor/parent/context mapping, heading observations hoặc danh mục anchors/source quote cues. Bundle navigation v1 giữ nguyên để đối chiếu lịch sử; code/profile mới yêu cầu bundle mới, không reseal bundle cũ.

## Quy tắc mới

- Opening là cửa sổ nội dung có giới hạn tối đa 240 Unicode codepoints; không dừng ngay tại dấu chấm đầu tiên. `Pinard, J.`, `Mr.`, `s.`, chữ cái đầu và `1.` không còn tự kết thúc preview.
- Chọn biên whitespace và biên tag nguyên vẹn khi vẫn vừa cap và giữ được anchor cần hiển thị. Từ/tag đơn lẻ quá dài có thể phải cắt; các cờ `word_boundary_clipped` và `tag_boundary_clipped` ghi rõ. Không thay đổi hoặc viết lại raw text.
- Dòng mở đầu sau khi bỏ placeholder chỉ còn dấu câu/ngoặc/whitespace được bỏ qua khi chọn opening. Phải còn chữ/số để chọn dòng làm nội dung. Việc bỏ qua này chỉ đổi view; anchors và raw vẫn giữ nguyên.
- `partial_sentence=null` và `boundary_status=content_window_not_sentence_verified`: không dùng dấu chấm để chứng nhận câu đã đầy đủ. `start_clipped`, `end_clipped`, `truncated` mô tả phần nội dung bị lược; đây không phải phán quyết về ranh giới câu ngữ nghĩa.
- Window anchor trong vùng nội dung không lùi qua marker hoặc các dòng đã bỏ để làm bẩn opening. Anchors trước phần nội dung vẫn có catalog và refs để mở; không buộc chiếm slot đọc thứ hai nếu chỉ lặp lại vùng bị che.
- Containment được kiểm hai chiều và gộp overlap khi union vừa cap. Không giữ hai preview khi một window đã chứa toàn bộ window kia. Slot bổ sung chọn theo lượng anchor evidence mới được thể hiện, ưu tiên bổ sung anchor đầy đủ rồi phần cue mới, tie-break theo source order; không đếm đây là retrieval relevance hoặc semantic score.
- Cue dài hơn cap có candidate phần đầu và phần cuối để slot còn lại có thể thêm evidence mới. Mọi anchor vẫn được lưu dù không được chọn vào tối đa hai snippet hiển thị. Visibility full/partial và full source-cue refs tiếp tục giữ nguyên nghĩa provenance.

Nav record/reader API giữ nguyên. Profile tăng thành `pipeline-v2-m2-profile-2`, preview selection method `bounded_content_window_novel_anchor_coverage_v3`; consumer phải dùng profile mới để hiểu `partial_sentence=null` và các clipping flags. Reader hiện hành từ chối bundle v1 do fingerprint/profile cũ, không có nghĩa raw v1 bị hỏng.

## Lệnh tái hiện

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v
& .venv/Scripts/python.exe -m pipeline_v2.m2 build --repo-root . --m1-bundle pipeline_v2/artifacts/m1_20261105_v2 --output pipeline_v2/artifacts/m2_navigation_NEW
& .venv/Scripts/python.exe -m pipeline_v2.m2 validate --repo-root . --bundle pipeline_v2/artifacts/m2_navigation_NEW
```

Output write-once; chọn thư mục mới. Bundle nghiệm thu cuối dự kiến: `pipeline_v2/artifacts/m2_navigation_20261106_v3/`; receipt build lưu ngoài sealed bundle. Regression raw-source gồm 011922, 051807, 080359, 068193, 014101, 048208, 081945, 015740; dùng offsets thực từ artifact, không sao chép offsets sai trong báo cáo AG.

## Phạm vi chưa thay đổi

Qwen3-Embedding-4B tự host Modal đã được người dùng chọn ở `configs/embedding_selection.json`. Stage navigation không pin tokenizer assets hoặc sinh token-valid chunks; token counts vẫn null, runtime/token preflight chưa ready. Không inference, tải weights, deploy, embedding corpus hoặc mở M3/M4. Script model requests/retries/tokens bằng 0; development-chat usage không được cung cấp.

Preview dài hơn và ít lặp hơn là điều kiện vận hành tốt hơn, chưa chứng minh agent chọn nguồn đúng hoặc cải thiện retrieval. Các phép quét viết tắt/overlap chỉ là diagnostics, không tự trở thành error rate toàn corpus.

## Kết quả build và kiểm tra

Checkpoint đã build: `pipeline_v2/artifacts/m2_navigation_20261106_v2/` (giữ nguyên, chưa phải bundle cuối). Một full build hoàn thành exit 0 trong **281,737 giây local**; receipt lưu tại `pipeline_v2/artifacts/m2_navigation_20261106_v2.build-receipt.json`. Production code/profile được freeze trước build và không sửa sau đó.

- 7.708 nguồn, 382.343 navigation units, 48.990 heading observations.
- 454.275 previews, giảm từ 481.926 ở v1 do chọn window/khử trùng lại; đây không phải phép đo chất lượng retrieval.
- 216.946 unit anchors và 1.237 full source quote cues giữ nguyên về số lượng; audit độc lập phải đối chiếu toàn bộ nội dung/refs, không chỉ counts.
- 267 units không có preview, so với 55 ở v1: các unit bị loại opening không còn chữ/số có nội dung vẫn giữ handle, raw spans và khả năng mở nguyên văn. Không có thao tác xóa source/unit.
- Tester đã báo **53/53 tests PASS** trên candidate cuối trước full build. Smoke 8 raw-source cases cũng giữ đúng nguyên văn/mapping; `011922/p000005` tăng từ `Pinard, J.` 10 ký tự thành window 237 ký tự, `051807/u000030` tăng từ `1.` 2 ký tự thành 233 ký tự. `014101/p000008` có thêm window hiển thị anchor thứ ba thay vì hai window chứa nhau.

Kết quả full validator và before/after audit được ghi riêng trong [báo cáo kiểm thử Revision 2](M2_PREVIEW_REVISION2_TEST_REPORT.md) sau khi tester chạy thật. Chỉ số token trong bundle vẫn null; đó là trạng thái của navigation runtime profile, không phủ nhận lựa chọn Qwen/Modal đã được ghi riêng.


## Sửa edge case sau audit checkpoint v2

Audit raw độc lập phát hiện 9 window cắt giữa tag `FRAGMENT_SUPPRESSED` ngắn 21 ký tự, không phải tag quá dài bắt buộc cắt. Nguyên nhân: candidate phần đuôi của cue dài truyền focus đã thu hẹp thành độ dài cap, nên điều kiện giữ toàn bộ focus chặn việc dịch biên trái tới cuối word/tag. Không được coi cờ clipping trung thực là lý do bỏ qua lỗi có thể sửa này.

Bản cuối truyền full cue gốc vào tail window; với focus dài hơn cap, cho phép biên trái dịch tới word/tag boundary khi vẫn giữ một phần cue. Focus vừa cap vẫn phải giữ toàn bộ anchor. Thêm guard biên phải giữ tối thiểu một phần focus thật. Marker/anchors/source/context mapping không đổi. Cờ word/tag clipping vẫn được giữ cho token/tag đơn lẻ thực sự quá dài.

Chín ca raw 004301, 006063, 008545, 013122, 031088, 059397, 071931, 093363, 095618 đã qua smoke không còn tag clipping sau sửa. Tester báo synthetic tag/word tail regression và full suite **54/54 PASS** trước build cuối. Checkpoint v2 giữ seal riêng; bundle cuối được build write-once vào `pipeline_v2/artifacts/m2_navigation_20261106_v3/`, receipt ngoài bundle. Validator và audit cuối chỉ chạy trên v3. Kết quả mới được bổ sung khi process hoàn thành.

## Bundle cuối v3

**Bundle nghiệm thu hiện hành: `pipeline_v2/artifacts/m2_navigation_20261106_v3/`.** Full build hoàn thành exit 0 trong **289,514 giây local**; receipt: `pipeline_v2/artifacts/m2_navigation_20261106_v3.build-receipt.json`. Code/profile không sửa sau freeze. V2 là checkpoint bất biến trước edge fix, không dùng thay v3.

V3 có 7.708 nguồn, 382.343 navigation units, 454.275 previews, 216.946 unit anchors, 1.237 full source cues và 48.990 headings; 267 units không preview vẫn có mapping/raw refs. Đây là cùng aggregate counts với checkpoint v2; thay đổi nằm ở biên window của long-cue tail, không phải counts hoặc danh mục nguồn.

Tester bổ sung automated regression cho cả 9 raw tag cases, nâng full suite lên **55/55 PASS** (3,105 giây). Full validator/audit v3 được chạy độc lập sau khi receipt/seal hoàn tất; xem báo cáo kiểm thử để biết kết quả cuối. Không có model/API requests hoặc retry inference. Có hai full builds local trong revision này: v2 checkpoint 281,737 giây và v3 final 289,514 giây; không giấu checkpoint trong accounting.

## Nghiệm thu cuối trên v3

Full validator **PASS** trên 7.708 nguồn, 288,921 giây local. Audit raw/M1 độc lập **PASS**, 58,171 giây, không lỗi coverage/provenance; mapping/nav/anchors/headings cũ–mới giữ nguyên. Trong corpus đã kiểm: không có cặp preview containment trùng thừa; toàn bộ 454.275 preview <=240 codepoints, `partial_sentence=null`; các cờ word/tag clipping được đối chiếu raw và không còn trường hợp cắt biên word/tag trong output v3. Cả 9 ca tag ngắn của checkpoint v2 đã hết lỗi. Đây là kết quả của corpus này, không phủ nhận fallback cho từ/tag đơn lẻ quá dài trong nguồn khác.

Audit cuối: `pipeline_v2/reviews/m2_preview_revision2_validation/m2_navigation_20261106_v3_full_corpus_audit.json`; không nhầm với `full_corpus_audit.json`/checkpoint v2. Các attempt và chẩn đoán đã sửa được giữ riêng; xem báo cáo tester. AG có thể dùng [prompt review bản sửa](AG_REVIEW_M2_PREVIEW_REVISION2_PROMPT.md) trước phần tiếp theo; lưu prompt không có nghĩa AG đã chạy. Không thay các phép kiểm này bằng tuyên bố ownership/semantic accuracy toàn corpus.
