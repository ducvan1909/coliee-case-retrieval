# BÁO CÁO ĐỘC LẬP RÀ SOÁT CẤU TRÚC VÀ TOÀN VẸN M1
## Pipeline COLIEE Task 1 — Giai đoạn Milestone 1 (M1)

**Ngày đánh giá:** 05/11/2026  
**Môi trường đánh giá:** Repo thực tế `E:/Git/coliee-case-retrieval`, Python 3.12 (`.venv/Scripts/python.exe`)  
**Đối tượng rà soát:**
- Bundle nguồn đã khóa: `pipeline_v2/artifacts/m0_20261105_v2/`
- Bundle M1 cần nghiệm thu: `pipeline_v2/artifacts/m1_20261105_v1/`
- Mã nguồn trích xuất: `pipeline_v2/m1.py`, `pipeline_v2/source/core.py`, `pipeline_v2/source/store.py`
- Cấu hình: `pipeline_v2/configs/m1.json`
- Corpus: `data/task1_train_files_2026/cases/` (7.708 bản án)

---

## TÓM TẮT ĐIỀU HÀNH & KẾT LUẬN CHUYỂN GIAO M2

> [!IMPORTANT]
> **KẾT LUẬN ĐỐI VỚI M2: `fixes_required_before_M2` (BẮT BUỘC SỬA TRƯỚC M2)**  
> Mặc dù M1 đạt **100% tính toàn vẹn địa chỉ và byte nguyên văn** (raw bytes, UTF-8, CRLF, partition không gap/overlap), việc rà soát độc lập phát hiện **lỗi cấu trúc nghiêm trọng mang tính dây chuyền ảnh hưởng trực tiếp tới ít nhất 1.632 bản án (21,17% toàn corpus)**. Nếu đưa sang M2 mà không sửa, M2 sẽ chunk sai ranh giới đoạn văn bản, trộn lẫn tiếng Anh và tiếng Pháp, và mất hàng chục ngàn đoạn văn bản gốc.

### Bảng đối chiếu câu hỏi trọng tâm

| Câu hỏi phân xử | Hiện trạng M1 | Kết luận & Ảnh hưởng |
|---|---|---|
| **1. Toàn vẹn nguồn & địa chỉ?** | **HOÀN TOÀN ĐẠT (PASS)** | 7.708/7.708 file khớp exact SHA-256 M0. Partition bao phủ 100% raw bytes, 0 gap, 0 overlap. Byte offsets chuẩn xác trên UTF-8/CRLF. Tamper detection hoạt động hoàn hảo. |
| **2. Nhận diện cấu trúc sai ở đâu?** | **LỖI HỆ THỐNG NGHIÊM TRỌNG** | Thuật toán dò thứ tự đoạn (`core.py` dòng 123-127) có điều kiện `(number != expected and not reset)` làm đóng băng số đoạn ngoài (`last_outer`). Bất kỳ án nào nhảy số (ví dụ [35] qua [37]) hoặc thiếu [1] đều bị **nuốt toàn bộ phần còn lại của bản án vào một paragraph duy nhất** làm sidecar (ảnh hưởng 1.632 án). |
| **3. Trích dẫn & Song ngữ?** | **LỖI NHẦM ĐOẠN TRÍCH THÀNH RESET** | Đoạn trích dẫn bắt đầu bằng `[1]` trong thân bài (ví dụ `050936.txt`) bị nhận nhầm thành đổi thứ tự toàn án, làm đổi nhãn ngôn ngữ sang `unknown:1` và nuốt luôn phần tiếng Anh lẫn tiếng Pháp tiếp sau. |
| **4. Tiêu đề (Headings)?** | **LỖI CẢ DƯƠNG TÍNH LẪN ÂM TÍNH** | Tên tòa án (`Federal Court`, `Trial Division`) và mục phân loại headnote (`Topic 4405`) bị nhận nhầm thành heading. Ngược lại, các tiêu đề viết hoa chuẩn (`ORDER`, `INTRODUCTION`, `ARGUMENTS`) bị bỏ sót hoàn toàn. |
| **5. Giá trị Metadata?** | **ĐẠT THEO HỢP ĐỒNG (ACCEPTED)** | Trích xuất literal regex khớp exact raw slices; không suy đoán danh tính án, không điền bừa giá trị bị suppressed. |
| **6. Phương pháp kiểm thử cũ?** | **TỰ XÁC NHẬN SAI (TAUTOLOGY)** | Báo cáo PASS 100% trước đó của M1 là do validator chạy lại chính hàm `parse_source` để so sánh `record == fresh`, chỉ chứng minh thuật toán tự tái lập lỗi của chính nó. |

---

## 1. PHƯƠNG PHÁP KHÓA MẪU ĐỘC LẬP (SAMPLING METHODOLOGY)

Tuân thủ nghiêm ngặt quy tắc rà soát độc lập:
1. **Khóa mẫu trước khi đọc nội dung:** Tạo `sampling_manifest.json` với seed cố định `20261105`.
2. **Loại trừ nghiêm ngặt:** Loại bỏ toàn bộ 10 discovery query IDs và 10 holdout query IDs của cohort M0 (để tránh rò rỉ holdout chỉnh parser); loại trừ riêng 3 exposed fixtures (`061295.txt`, `067620.txt`, `062436.txt`). Tổng số án bị loại trừ: 23 án. Bể hợp lệ: 7.685 án.
3. **Mẫu rà soát (24 án, 72 vùng):**
   - **12 án ngẫu nhiên đều:** `008932`, `011913`, `014069`, `015710`, `038761`, `059632`, `060581`, `062793`, `068113`, `080279`, `081898`, `087799`.
   - **12 án rủi ro cấu trúc (3 án/nhóm):**
     - *Nhóm A (Nhiều quote-markers):* `007685` (630 sidecars), `020897` (300 sidecars), `078607` (602 sidecars).
     - *Nhóm B (Reset / Song ngữ):* `038799`, `050936`, `057925`.
     - *Nhóm C (Tỷ lệ unnumbered cao):* `046028` (85,12%), `066595` (81,72%), `068174` (85,46%).
     - *Nhóm D (Heading candidates / Outer quote collision):* `019591`, `042691`, `077071`.
4. **Quy tắc đọc vùng:** Mỗi án đọc tối đa 3 vùng theo quy tắc vị trí/rủi ro đã khóa trước, đọc ngữ cảnh tối thiểu 300-600 ký tự trước/sau ranh giới.
5. **Thống kê phân xử:** 72/72 vùng đã đọc và phân xử dứt điểm (0 vùng chưa phân xử). Tìm thấy lỗi cấu trúc tại 16 vùng, đạt chuẩn tại 56 vùng.

*Lưu ý phương pháp:* Vì không sử dụng nhãn human gold, đây là **AI-assisted structural review**, không phải độ chính xác ngữ nghĩa được chứng nhận.

---

## 2. KẾT QUẢ KIỂM TOÀN BỘ 7.708 NGUỒN BẰNG CODE ĐỘC LẬP

Script kiểm tra độc lập `pipeline_v2/reviews/m1_review_v1/scripts/integrity_check.py` duyệt trực tiếp raw bytes và JSON artifact từ đĩa, **hoàn toàn không gọi `parse_source()` hay reader hiện có**:

- **Thời gian thực thi:** 49,391 giây local (Python 3.12).
- **Kết quả:** **PASS 100%**, 0 lỗi (errors = 0), 0 cảnh báo (warnings = 0).
- **Chi tiết xác minh:**
  1. **Universe & Hash:** 7.708 file khớp SHA-256 M0 inventory, tổng dung lượng 225.398.607 bytes.
  2. **Phân vùng (Partition Coverage):** 798.552 structural units liên tục, bắt đầu từ byte 0, kết thúc tại byte cuối của file. Không hở (0 gap), không chồng lấn (0 overlap). Mọi unit có `start < end`.
  3. **Địa chỉ UTF-8 & CRLF:** 100% ranh giới unit nằm đúng ranh giới codepoint UTF-8. 100% độ dài decoded char slice khớp `span_chars[1] - span_chars[0]`. Định dạng xuống dòng CRLF được bảo toàn.
  4. **Ánh xạ Utf8Map:** Ngoại lệ multibyte `[char_index, byte_offset, width]` khớp hoàn toàn với việc quét codepoint độc lập.
  5. **Định danh Unit:** 100% unit ID tuân thủ regex `{case_prefix}:{hash16}:{start}-{end}:{profile12}`, duy nhất trên toàn corpus.
  6. **Quan hệ Section & Sidecar:** 100% `section_path_refs` trỏ về unit heading đã xuất hiện trước đó; 100% sidecar có `parent_unit_id` nằm trọn trong span của paragraph cha; nếu không có parent thì `route_unknown: true`.
  7. **Metadata exact slices:** 100% trường metadata có giá trị khớp byte-for-byte với lát cắt raw tương ứng.
  8. **Tổng hợp counts:** Khớp 100% với `summary.json` (paragraph: 284.373, heading: 45.074, unnumbered: 28.046, whitespace: 441.059, sidecars: 72.487).
  9. **Kiểm tra chống sửa đổi (Tamper resistance):** Script `scripts/tamper_test.py` trên bản sao fixture xác nhận reader phát hiện và từ chối: (a) file nguồn bị sửa byte, (b) tọa độ unit bị sửa và tự reseal, (c) hash trong registry bị sửa và tự reseal, (d) profile trong manifest bị sửa và tự reseal.

---

## 3. CÁC PHÁT HIỆN LỖI CẤU TRÚC (FINDINGS CHI TIẾT)

Xem chi tiết đầy đủ trong [`findings.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/findings.json). Lệnh tái hiện toàn bộ:
```powershell
& .venv/Scripts/python.exe pipeline_v2/reviews/m1_review_v1/scripts/repro_findings.py
```

### M1-FINDING-001 (CRITICAL — confirmed_defect): Lỗi nuốt dây chuyền đoạn văn bản gốc do điều kiện `number != expected`
- **Vị trí code:** `pipeline_v2/source/core.py`, dòng 123-127.
- **Phạm vi ảnh hưởng:** **1.632 bản án trên toàn corpus (chiếm 21,17%)**.
- **Cơ chế lỗi:**
  ```python
  nested = last_outer is not None and not french_reset and not separator_reset and (
      (quote_active and number != expected) or
      (intro and (not standalone or number != expected or indent > root_indent)) or
      (number != expected and not reset))
  ```
  Nhánh thứ ba `(number != expected and not reset)` quy định: nếu một đoạn có số `number != last_outer + 1` và `number != 1`, nó **mặc định bị coi là trích dẫn lồng (nested quote)**.
  Khi gặp trường hợp văn bản tòa án nhảy số (ví dụ [35] nhảy lên [37] do tòa bỏ qua đoạn 36, hoặc bản án bắt đầu từ [2]), `number != expected` thành `True`:
  1. Đoạn [37] bị coi là quote sidecar.
  2. `quote_active` bị bật thành `True`.
  3. Biến `last_outer` **không được cập nhật** (vẫn giữ nguyên là 35).
  4. Đến đoạn tiếp theo [38], `expected` vẫn là 36, nên [38] lại bị coi là quote sidecar!
  5. **Dẫn đến phản ứng dây chuyền:** Toàn bộ phần còn lại của bản án (hàng chục đoạn, hàng chục ngàn bytes) bị nuốt sạch vào đoạn văn bản trước đó!
- **Bằng chứng thực tế:**
  - Án `000758.txt`: Tòa nhảy từ đoạn `[35]` lên `[37]`. Parser nuốt toàn bộ 37 đoạn văn bản tiếp theo (`[37]` đến `[75]`, hơn 25.000 bytes) vào paragraph 35! Tiêu đề `Summary` bị bỏ qua vì `quote_active=True`.
  - Án `046028.txt`: Tòa nhảy từ `[6]` qua `[8]`. Parser nuốt toàn bộ đoạn `[8]` đến `[34]` (17.979 bytes, 83% bản án) thành một khối `unnumbered` khổng lồ!
  - Án `000432.txt`: Bản dịch tiếng Pháp bắt đầu từ `[2]` (do [1] bị suppressed). Parser nuốt sạch toàn bộ 48 đoạn tiếng Pháp (hơn 37.000 bytes) vào đoạn [48] tiếng Anh!
  - Án `014069.txt` (trong mẫu ngẫu nhiên): Bản tiếng Pháp bắt đầu từ `[2]`. Toàn bộ nửa sau bản án (46.788 bytes) bị biến thành một khối `unnumbered` duy nhất!
- **Tác động tới M2:** **BLOCKER**. M2 không có ranh giới paragraph để chunk. Chunk M2 sẽ gộp hàng chục lập luận pháp lý độc lập vào nhau, hoặc phải cắt mù theo độ dài token.

---

### M1-FINDING-002 (CRITICAL — confirmed_defect): Nhận nhầm đoạn trích dẫn `[1]` thành Reset đánh số toàn bản án
- **Vị trí code:** `pipeline_v2/source/core.py`, dòng 117-127 và dòng 73 (`QUOTE_CUE`).
- **Phạm vi ảnh hưởng:** 62 bản án mang cờ `numbering_reset_language_unknown`.
- **Cơ chế lỗi:**
  Tại dòng 117: `reset = number == 1 and last_outer is not None and last_outer > 1`. Khi trong thân bài có câu trích dẫn mở đầu bằng `[1]` (ví dụ: `As noted by Justice Shore in [case]: [1] The Court is of the opinion...`):
  1. Cụm từ dẫn "noted" không nằm trong regex cứng `QUOTE_CUE`.
  2. Parser thấy `number == 1`, liền khẳng định đây là **RESET ĐÁNH SỐ TOÀN TÀI LIỆU**!
  3. Ngôn ngữ bị đổi sang `unknown:1`.
  4. Khi đoạn văn bản tiếng Anh tiếp theo `[31]` xuất hiện, vì `expected` bị reset về 2, đoạn `[31]` đến `[54]` bị nuốt thành sidecar của đoạn trích `[1]`!
  5. Đến khi bản tiếng Pháp thật xuất hiện ở đoạn `[2]`, nó bị gộp nhầm vào chuỗi `unknown:1` của tiếng Anh!
- **Bằng chứng thực tế:**
  Án `050936.txt`: Paragraph 30 trích dẫn 1 câu từ án của Justice Shore có số `[1]`. Parser tạo unit `paragraph 1 [13042, 24976]` với nhãn `unknown:1`, nuốt trọn các đoạn [31] đến [54] của tiếng Anh. Sau đó các đoạn [2] đến [30] tiếng Pháp bị gán nhãn `unknown:1` thay vì `fr`.
- **Tác động tới M2:** **BLOCKER**. Trộn lẫn ngôn ngữ Anh-Pháp trong cùng một chuỗi ngữ cảnh, mất đoạn văn bản tiếng Anh trong retrieval chunking.

---

### M1-FINDING-003 (MAJOR — confirmed_defect): Dương tính giả tiêu đề từ Header tòa án và Headnotes
- **Vị trí code:** `pipeline_v2/source/core.py`, dòng 152-156 (`title_candidate`).
- **Phạm vi ảnh hưởng:** Phần lớn trong số 4.246 `heading_candidate`.
- **Cơ chế lỗi:**
  Điều kiện `title_candidate` chỉ kiểm tra: dòng trước trống, độ dài <= 100, >= 2 từ, `clean.istitle()`, không kết thúc bằng dấu câu.
  Do đó, các dòng tên tòa án ở header như `Federal Court`, `Trial Division` hay dòng phân loại chủ đề headnote như `Aliens - Topic 2`, `Copyright - Topic 4405`, thậm chí cụm từ cắt dở `Defences - Consent - [See` đều thỏa mãn và trở thành structural `heading`!
- **Bằng chứng thực tế:**
  - Án `019591.txt`: `Federal Court`, `Aliens - Topic 2`, `Aliens - Topic 3.2` bị coi là heading. Toàn bộ đoạn thân bài đều mang `section_path_refs` trỏ về `Federal Court`.
  - Án `077071.txt`: `Trial Division`, `Civil Rights - Topic 1001` bị coi là heading.
  - Án `042691.txt`: `Defences - Consent - [See` bị coi là heading.
- **Tác động tới M2:** **TRUNG BÌNH/CAO**. Chunk retrieval của M2 khi gắn prefix heading sẽ bị gắn nhãn sai (ví dụ đoạn phân tích pháp lý lại mang heading "Federal Court" hoặc "Topic 4405"), làm sai lệch biểu diễn embedding và trọng số BM25.

---

### M1-FINDING-004 (MAJOR — confirmed_defect): Bỏ sót toàn bộ tiêu đề viết hoa chuẩn (ORDER, INTRODUCTION, ARGUMENTS)
- **Vị trí code:** `pipeline_v2/source/core.py`, dòng 70 (`KNOWN_HEADING`) và dòng 153 (`title_candidate`).
- **Phạm vi ảnh hưởng:** Trong mẫu khảo sát 500 án, `ORDER` bị sót ở 78 án (15,6%), `INTRODUCTION` ở 23 án, `ARGUMENTS` ở 12 án, `DECISION` ở 6 án.
- **Cơ chế lỗi:**
  `KNOWN_HEADING` chỉ chứa 18 từ khóa cố định. Các tiêu đề khác phải dựa vào `title_candidate`. Tuy nhiên, trong Python, `str.istitle()` trả về `False` đối với chuỗi viết hoa toàn bộ (ALL CAPS)! Ngoài ra `len(clean.split()) >= 2` loại bỏ hoàn toàn các từ đơn như `ORDER`, `ARGUMENTS`, `LEGISLATION`.
- **Bằng chứng thực tế:**
  Án `000758.txt`: Dòng `Summary` trước đoạn [38] bị bỏ qua. Các án có `ORDER`, `INTRODUCTION`, `ARGUMENTS` đứng riêng thành một dòng đều không được ghi nhận là heading.
- **Tác động tới M2:** **TRUNG BÌNH**. M2 không nhận biết được ranh giới phần "Phán quyết" (Order) hoặc "Mở đầu" (Introduction) để áp dụng chính sách chunking phù hợp.

---

### M1-FINDING-005 (HIGH — confirmed_defect / methodology): Validator tự xác nhận sai do cùng dùng một thuật toán
- **Vị trí code:** `pipeline_v2/source/store.py`, dòng 229:
  ```python
  if record != parse_source(ident, raw, self.manifest["profile"]):
      raise M1Error("Structure/map/metadata differs from source and parser")
  ```
- **Phạm vi ảnh hưởng:** Toàn bộ harness kiểm thử của M1 (21/21 tests PASS, 7.708/7.708 sources validated).
- **Cơ chế lỗi:**
  Validator kiểm tra bundle bằng cách gọi lại hàm `parse_source()` trên raw text và so sánh `record == fresh`. Khi `parse_source()` mắc lỗi thuật toán (như nuốt 37 đoạn ở `000758.txt`), lượt chạy lại sinh ra **chính xác lỗi y hệt**, dẫn đến phép so sánh luôn trả về `True`!
- **Tác động tới M2:** Đây là lý do khiến M1 trước đó tự tin báo cáo "PASS 100% không có lỗi", tạo ra cảm giác an toàn giả tạo về độ chính xác cấu trúc.

---

### CÁC GIỚI HẠN ĐƯỢC CHẤP NHẬN (ACCEPTED LIMITATIONS)

1. **M1-FINDING-006 (Metadata quan sát nhiều citation):**
   Regex tìm neutral citation quét toàn bộ header. Nếu header có phần tóm tắt trích dẫn án lệ khác (ví dụ `042691.txt`), M1 thu thập cả 2 citation và gắn nhãn `observed_not_identity_verified`.  
   *Đánh giá:* **Hợp lệ theo hợp đồng M1**. M1 tuyên bố rõ metadata chỉ là quan sát ký tự thô, không xác minh danh tính duy nhất của bản án. M2 dùng `case_id` từ M0 nên không bị ảnh hưởng.
2. **M1-FINDING-007 (5,70% unnumbered bytes trên các án chuẩn):**
   Trên các án có cấu trúc chuẩn (`008932`, `011913`, `015710`), vùng unnumbered chiếm 0,5% - 2,5% dung lượng, đại diện cho tiêu đề vụ án, danh sách luật sư, thẩm phán trước đoạn [1].  
   *Đánh giá:* **Hợp lệ theo hợp đồng M1**. Vùng này được gắn cờ `structure_unknown` chính xác, M2 có thể xử lý an toàn theo policy bỏ qua hoặc xem như non-core context.

---

## 4. CHI TIẾT KẾT QUẢ RÀ SOÁT TRÊN 24 ÁN MẪU

Tất cả 72 vùng đã được lưu đầy đủ tại [`reviewed_regions.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/reviewed_regions.json):

1. **Mẫu ngẫu nhiên đều (12 án, 36 vùng):**
   - 11 án (`008932`, `011913`, `015710`, `038761`, `059632`, `060581`, `062793`, `068113`, `080279`, `081898`, `087799`): Đạt chuẩn sạch (clean pass). Ranh giới metadata -> đoạn [1], đoạn giữa và đoạn cuối chuẩn xác.
   - 1 án (`014069`): Bị lỗi M1-FINDING-001 (nuốt 46.788 bytes tiếng Pháp vào khối unnumbered do bản tiếng Pháp bắt đầu từ [2]).
2. **Mẫu rủi ro A — Nhiều quote-markers (3 án, 9 vùng):**
   - Cả 3 án (`007685`, `020897`, `078607`): Đều bị lỗi M1-FINDING-001 nuốt hàng trăm đoạn văn bản gốc thành sidecars do nhảy số.
3. **Mẫu rủi ro B — Reset / Song ngữ (3 án, 9 vùng):**
   - 2 án (`038799`, `057925`): Reset tiếng Pháp đúng ngữ cảnh.
   - 1 án (`050936`): Bị lỗi M1-FINDING-002 (trích dẫn [1] trong thân bài làm reset hỏng toàn bộ án).
4. **Mẫu rủi ro C — Tỷ lệ unnumbered cao (3 án, 9 vùng):**
   - Cả 3 án (`046028`, `066595`, `068174`): Đều bị lỗi M1-FINDING-001 nuốt từ 15.000 đến 19.000 bytes thân án thành `unnumbered` vì thiếu đúng 1 số đoạn ở đầu!
5. **Mẫu rủi ro D — Heading candidates & Outer quote (3 án, 9 vùng):**
   - Cả 3 án (`019591`, `042691`, `077071`): Đều bị lỗi M1-FINDING-003 biến tên tòa án và headnote thành heading cấu trúc.

---

## 5. HƯỚNG SỬA ĐỔI TỐI THIỂU CHO M1 (MINIMAL FIX SPECIFICATION)

Không sửa trực tiếp mã nguồn trong đợt review này. Đề xuất phạm vi sửa tối thiểu cho phiên bản tiếp theo của M1:

1. **Sửa logic nhận diện đoạn lồng (`pipeline_v2/source/core.py`):**
   - **Bỏ điều kiện:** `(number != expected and not reset)` làm căn cứ tự động gán `nested = True`.
   - **Thay bằng logic bảo thủ:** Chỉ coi là nested quote khi có bằng chứng thực tế: có câu dẫn trích dẫn (`intro = True`), hoặc có thụt lề rõ rệt (`indent > root_indent`), hoặc nằm trong khối quote đang mở.
   - **Xử lý nhảy số:** Nếu `number > last_outer` mà không có dấu hiệu trích dẫn, coi đây là đoạn văn bản ngoài tiếp theo (`last_outer = number`), tắt `quote_active = False`, và bổ sung cờ cảnh báo `numbering_gap_observed`.
2. **Sửa logic Reset đánh số:**
   - Khi gặp `number == 1`, không kích hoạt reset tài liệu nếu đoạn đó đang nằm ngay sau một câu trích dẫn hoặc citation colon mà không có dòng phân cách (`.......`, `[translation]`, hoặc ngắt trang).
   - Nếu đoạn văn bản tiếp theo khớp với số thứ tự trước đó (`last_outer + 1`), lập tức hủy bỏ reset và xem `[1]` là trích dẫn.
   - Cho phép reset bản dịch kích hoạt ngay cả khi thiếu [1] nếu có phân cách rõ ràng (`.......` hoặc `[Traduction]`).
3. **Sửa bộ dò Heading:**
   - Loại trừ các dòng trong header trước paragraph đầu tiên khớp với tên tòa án (`Federal Court`, `Trial Division`) hoặc dòng phân loại (`Topic \d+`).
   - Mở rộng `KNOWN_HEADING` thêm các từ khóa viết hoa chuẩn: `ORDER`, `ORDONNANCE`, `INTRODUCTION`, `ARGUMENTS`, `LEGISLATION`, `MOTIFS`.
4. **Cải tiến Harness Validator:**
   - Bổ sung assertion kiểm tra cấu trúc độc lập: Cảnh báo nếu một paragraph cha chứa chuỗi sidecars tăng dần liên tục trên 3 số; cảnh báo nếu khối `unnumbered` chứa các đoạn có đánh số `[n]`.

---

## 6. DANH MỤC SẢN PHẨM BÀN GIAO TRONG THƯ MỤC REVIEW

Tất cả các tệp nghiệm thu đã được tạo hoàn chỉnh dưới thư mục [`pipeline_v2/reviews/m1_review_v1/`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/):
- [`sampling_manifest.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/sampling_manifest.json): Danh sách 24 án mẫu, tiêu chí nhóm, ngưỡng, seed 20261105 và toàn bộ lý do chọn.
- [`findings.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/findings.json): 7 phát hiện (5 confirmed defects, 2 accepted limitations) với đầy đủ case ID, hash, byte offsets, text evidence, repro command và hướng sửa.
- [`reviewed_regions.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/reviewed_regions.json): Toàn bộ 72 vùng đã đọc kèm context trước/sau và kết quả phân xử.
- [`commands_and_results.json`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/commands_and_results.json): Nhật ký toàn bộ lệnh đã chạy, exit code, thời gian và kết quả thật.
- Thư mục [`scripts/`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/scripts/):
  - `integrity_check.py`: Phép kiểm độc lập toàn bộ 7.708 nguồn.
  - `tamper_test.py`: Phép kiểm tamper resistance trên fixture biệt lập.
  - `sampling.py`: Script sinh sampling manifest xác định.
  - `inspect_samples.py`: Trích xuất ngữ cảnh 72 vùng.
  - `build_reviewed_regions.py`: Đánh giá 72 vùng.
  - `build_findings.py`: Biên soạn findings.
  - `repro_findings.py`: Script độc lập một lệnh tái hiện toàn bộ lỗi.
- [`REPORT.md`](file:///E:/Git/coliee-case-retrieval/pipeline_v2/reviews/m1_review_v1/REPORT.md): Báo cáo tổng hợp này.
