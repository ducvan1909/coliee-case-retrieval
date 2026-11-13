# Lịch tìm và đọc nguồn cố định của M5

`run_fixed_baseline` xử lý một query bằng các công cụ local của M4. Nó trả các chỗ cần truy nguồn, ứng viên và hồ sơ A→B để bước đánh giá bằng chứng dùng sau khi M4 đủ điều kiện. [Kế hoạch agent và đánh giá](plan/AGENT_AND_EVALUATION.md)

```python
from pathlib import Path

from pipeline_v2.full_search.source_tools import SourceToolsSession
from pipeline_v2.m4 import M3Tools
from pipeline_v2.m5 import FixedSchedule, run_fixed_baseline
from pipeline_v2.sparse_bm25.index import SparseSession

root = Path.cwd()
lexical = SparseSession(root)
sources = None
try:
    sources = SourceToolsSession(root, snapshot=lexical)
    tools = M3Tools(sources, lexical, "017984.txt", byte_budget=4096, map_limit=20)
    result = run_fixed_baseline(tools, schedule=FixedSchedule())
finally:
    if sources is not None:
        sources.close()
    lexical.close()
```

Lịch xét tối đa hai trang bản đồ A theo mặc định. Nó lấy preview từ tối đa hai đơn vị có anchor quan sát được, như placeholder hoặc dấu hiệu dẫn lời, và hai paragraph không có anchor. Đây là quy tắc chọn chỗ để đọc. Mỗi chỗ tạo hai lượt tìm, BM25 cấp án và BM25 cấp passage. Kết quả giữ tối đa năm hit mỗi kênh. Các hit trùng B được gom về một hồ sơ A→B, giữ lý do mỗi lượt đưa B vào tập ứng viên.

Lịch mở A theo thứ tự nguồn, ưu tiên vùng byte chứa preview, và mở tối đa năm ứng viên B. Thứ tự ưu tiên B dựa trên hạng tốt nhất trong các lượt tìm, dùng case ID để phân xử đồng hạng. Với ứng viên chỉ có hit cấp án, một lượt tìm passage trong án có thể cung cấp vị trí để mở. Kết quả giữ refs, source hash, UTF-8 byte spans và phần còn chờ sau khi mở trang đầu. Các ứng viên còn lại vẫn có hồ sơ với trạng thái `unknown`.

Các đoạn được mở ở đây là dữ liệu local để chuẩn bị đánh giá. Bước assessment giao raw excerpts qua payload của M4 và kiểm lại refs, source hash và provenance. Bộ chọn cần tiêu chí đã chốt trên discovery. Các giới hạn mặc định hiện phục vụ kiểm tra lịch và độ phủ, chưa được hiệu chỉnh theo chất lượng truy hồi.

Kiểm local trên `017984.txt` với cấu hình trên trả cùng kết quả qua hai lượt dùng chung session, sau khi bỏ thời gian đo. Mỗi lượt chọn bốn chỗ truy nguồn, thực hiện tám lượt tìm, lập 31 hồ sơ và mở năm án ứng viên. Chín đoạn đã mở khớp raw bytes, source hash và excerpt hash. Mỗi lịch chạy khoảng 2,4–2,5 giây sau khi mở session và phát sinh 0 request model.

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m5_baseline pipeline_v2.tests.test_m4_harness pipeline_v2.tests.test_m4_tools pipeline_v2.tests.test_m3_source_tools
```

## Nối hồ sơ cố định vào assessment M4

`pipeline_v2.m5_assessment.assess_fixed_baseline` nhận basket từ lịch M5 cùng transport, token counter và source verifier. Mỗi context đủ điều kiện dùng đúng các đoạn A của `source_need_id` đã định vị B và các đoạn B đã mở. Các need khác của cùng B vẫn giữ trạng thái chờ để thể hiện phần bằng chứng chưa được thu thập cho need đó. Cặp chỉ có retrieval giữ quan hệ `unknown` và trạng thái chờ.

Host giao raw A/B qua harness M4 trước request đánh giá, kiểm response theo schema rồi kiểm refs/provenance. Model trả hai nhãn và lý do tối đa 120 ký tự. ID, refs và speaker `unknown` do host điền trong profile kỹ thuật này. Từng context có admission, usage và ledger riêng. Ngân sách assessment toàn basket được khóa cùng model/prompt/tokenizer. Tiếp tục cùng run giữ caps và các request đã thực hiện.

Hook `initial_candidate_excerpts` cho phép host nạp B đã mở vào harness cùng A. Fingerprint validator theo mã M4 thay đổi khi bổ sung hook. Run M4 lịch sử tiếp tục giữ artifact theo fingerprint cũ. Lượt mới dùng namespace mới. Run M5 tiếp tục với cùng mã, profile và evidence đã khóa.

Runner `pipeline_v2.m5_live` có hai bước. Bước `prepare` chạy local, lưu basket và fingerprints để kiểm trước khi gọi model.

```powershell
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$run = "pipeline_v2/reviews/m5_live_$stamp"
& .venv/Scripts/python.exe -m pipeline_v2.m5_live prepare --run-dir $run --query-id '017984.txt'
```

Sau khi kiểm basket hợp lệ, AG chạy assessment trên app Modal đã nghiệm thu. Profile mặc định giới hạn tối đa 5 request toàn basket, 256 token đầu ra/request, 4.096 token prompt/request và 0 retry. Cặp không vừa payload tiếp tục chờ, giữ coverage rõ trong báo cáo.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m5_live assess --run-dir $run --tokenizer-dir 'cache/tokenizers/qwen36_27b_fp8'
```

Giữ `evidence.json`, các ledger của context và `assessment_report_*.json`. Kiểm refs của mỗi assessment thuộc đúng A/B và need, cap/retry, usage của lượt lỗi, cùng danh sách context còn chờ. Khi receipt chưa rõ thì dừng và đối chiếu call ID. Đầu ra giữ `selection_status=pending_selection` để bước chọn án dùng policy được khóa trên discovery.
