# M1 Revision 2 — Marker độc lập và ownership theo evidence

Revision này thay parser M1 v1 sau review cấu trúc. Nguồn, M0, bundle M1 v1 và báo cáo lịch sử được giữ nguyên. Runtime hiện hành dùng schema/profile v2; validator/reader mới từ chối bundle v1 do version/fingerprint khác, không phải vì raw nguồn bị hỏng.

## Quy tắc hiện hành

- Mỗi `[số]` đầu dòng (cho phép thụt lề, không bắt buộc khoảng trắng sau `]`) có paragraph unit riêng. Giá trị và thứ tự số không quyết định ownership, grouping hay ngôn ngữ. Không có `last_outer`, `expected`, reset theo `[1]` hoặc quote state kéo dài.
- Citation như `[2012] FC 9` được tách bằng reporter cùng dòng; `[2012]` đứng riêng vẫn là marker. Marker text nguyên bản, kể cả leading zeros, được giữ.
- Mọi paragraph có `paragraph_role=current_case|quoted|unknown`, evidence refs và `attribution_unit_id/null`. Unknown giữ nguyên địa chỉ, không gộp vào đoạn trước.
- Bộ heuristic hiện chỉ gán `quoted` khi có câu dẫn cục bộ kết thúc bằng colon và explicit quote verb, hoặc authority frame cộng attribution verb. Từ `following`/`paragraph N` một mình chưa đủ.
- `I find`, `THIS COURT` là voice observations, không chứng minh người nói thuộc án hiện tại. Do đó R2 bảo thủ chưa gán `current_case` chỉ từ các cue này; chúng vẫn là `unknown`. R2 không chứng nhận ownership accuracy.
- Không kéo nhãn quoted qua các marker tiếp theo chỉ vì câu dẫn trước đó. Phạm vi quotation không rõ => unknown. Không đoán hierarchy bằng số.
- Sidecar `quotation_relation` nối `quoted_unit_id` tới attribution unit có chứa toàn bộ cue; không chứa được thì giữ null. Quan hệ không khẳng định containment vật lý, không khẳng định danh tính án nguồn.
- Vùng bản dịch chỉ đổi khi có tag/cue/frame thực tế, độc lập với marker số. Thiếu cue giữ unknown; marker mới vẫn mở riêng được. Scope language còn là heuristic quan sát, không phải language gold.
- Chỉ nhận heading literal đã khai báo (gồm ORDER, INTRODUCTION, ARGUMENTS, DECISION); bỏ đoán broad title-case. Header heading không trở thành section refs của body. Section refs vẫn chỉ heading gần nhất, chưa phải cây mục pháp lý.
- Reader trả thêm `unit_metadata` cùng nguyên văn/offsets/hash để bước sau nhận role, uncertainty và evidence. Map UTF-8, raw source và kiểm hash M0 giữ nguyên.

## Gate độc lập

Ngoài reproducibility bằng parser, `validate_marker_coverage` quét numeric line markers trực tiếp từ raw bytes. Mỗi marker phải có unit riêng hoặc citation observation có reporter evidence; paragraph không được nuốt marker khác. Gate này chứng minh giữ ranh giới quan sát được, không chứng minh ownership semantics.

Các fixture đã exposed chạy trước build: 061295, 067620, 062436, 000758, 050936, 000432, 014069, 046028. Không dùng labels, holdout gold hoặc nguồn ngoài. Không lặp lại con số 1.632 án lỗi từ review cũ khi chưa có danh sách và phép quét tái lập.

## Lệnh tái hiện

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v
& .venv/Scripts/python.exe -m pipeline_v2.m1 build --repo-root . --m0-bundle pipeline_v2/artifacts/m0_20261105_v2 --output pipeline_v2/artifacts/m1_NEW
& .venv/Scripts/python.exe -m pipeline_v2.m1 validate --repo-root . --bundle pipeline_v2/artifacts/m1_NEW
```

Build write-once, luôn chọn thư mục mới. M1 không chạy M2, index, embedding, model/API hay deploy. Requests/retries/tokens của script bằng 0; model latency/development chat usage không được cung cấp.

## Bundle nghiệm thu Revision 2

Bundle mới: `pipeline_v2/artifacts/m1_20261105_v2/`. Bundle v1 giữ nguyên để đối chiếu lịch sử. Receipt thời gian build chưa thu hồi được sau khi subagent gặp usage limit; không ước lượng latency. Các kết quả kiểm tra cuối được lưu trong [báo cáo Revision 2](M1_REVISION2_TEST_REPORT.md).

Theo summary đã seal: 7.708 nguồn, 225.398.607 bytes; 356.973 paragraph-marker units, 48.990 headings, 25.370 vùng unnumbered và 514.659 whitespace units. Có 1.237 units được gán `quoted` theo cue cục bộ, 355.736 units `unknown`, 0 units `current_case`. Không coi số lượng gán nhãn hoặc cờ uncertainty là accuracy.

Nghiệm thu local cuối: **31/31 tests PASS**, quét raw-byte độc lập **PASS** trên 356.999 marker (356.973 paragraph units + 26 citation observations), không marker thiếu/trùng hoặc paragraph nuốt marker kế tiếp. Full validator **PASS** trên 7.708 nguồn, 153,591 giây. Script quét độc lập nằm trong `pipeline_v2/reviews/m1_revision2_validation/scripts/scan_marker_coverage.py`; không import parser production làm oracle.

Đã giữ riêng các marker vốn bị nuốt trong các ca regression cũ. Việc phân loại ownership và vùng ngôn ngữ vẫn cần review ngữ cảnh; sửa ranh giới không tự chứng minh quotation được nhận đúng toàn corpus.

## Giao AG review lại

Đọc và thực hiện [prompt review Revision 2](AG_REVIEW_M1_REVISION2_PROMPT.md). Lượt review độc lập này chưa được coi là hoàn thành chỉ vì local tests hoặc validator PASS.
