# Schema cho pipeline LegalUnit

## 1. Luồng dữ liệu 

```text
Nguồn + manifest
        |
        v
Code phân tách cấu trúc
        |
        |  LegalUnit candidate: code_provisional
        v
LLM lượt 1: chỉ sửa biên
        |
        |  remove + insert + review
        v
Host dựng lại các span từ nguồn
        |
        v
LLM lượt 2: chỉ phân loại các span đã khóa
        |
        |  functions + attribution + voice + language + confidence + unknowns
        v
Host dựng LegalUnit cuối + validate_llm_units()
        |
        v
legal_units.jsonl chỉ nhận case complete
```

Quyền sở hữu dữ liệu:

| Thành phần | Được quyết định | Không được quyết định |
|---|---|---|
| Code phân tách | Biên cấu trúc tạm, offset, thứ tự, dấu hiệu cấu trúc | Chức năng pháp lý, speaker, reporting voice, ngôn ngữ semantic |
| LLM sửa biên | Xóa biên có sẵn, thêm biên bằng exact anchor, báo vùng chưa chắc | Viết lại nguồn, tự tạo offset, gán nhãn semantic |
| LLM phân loại | Nhãn của đúng các unit key do host cung cấp | Split, merge, đổi text, đổi span, thêm hoặc bỏ unit key |
| Host | Hash, vùng editable, offset thật, text, ID, order, materialization, validation | Tự sửa nhãn sai thành `unknown` hoặc coi schema hợp lệ là semantic đúng |

`text`, `source_span`, `id` và `order` của LegalUnit cuối luôn do host dựng từ
nguồn đã khóa. Model không được trả các trường này.

## 2. Contract đầu vào 

Mỗi case phải có:

- `case_id`: tên file
- `text`: nội dung lấy nguyên văn từ file nguồn
- `source_ref`: đường dẫn nguồn (ví dụ "samples/cases/024310.txt");
- `source_sha256`: hash của file nguồn;
- `base_units`: danh sách ứng viên do code phân tách.

Trước khi gọi LLM, host kiểm tra `source_sha256` với `manifest.json`. Mỗi request
sửa biên còn có `state_sha256`, được tính từ `case_id`, hash nguồn, span và một
số trường trạng thái của các unit hiện tại. Response được tạo từ nguồn hoặc
trạng thái cũ phải bị từ chối.

## 3. Schema output của bước code phân tách

Output chính đặt ở file `legal_unit_candidates.jsonl`
Mỗi unit có dạng:

```json
{
  "id": "024310.txt:lu:1",
  "case_id": "024310.txt",
  "text": "Verbatim source slice",
  "source_span": {
    "source_ref": "agentic_pipeline/legal_unit/samples/cases/024310.txt",
    "start_char": 0,
    "end_char": 23
  },
  "order": 0,
  "functions": ["unknown"],
  "attributed_to": {
    "kind": "unknown",
    "party_role": null
  },
  "reporting_voice": null,
  "language": "unknown",
  "confidence": 0.0,
  "unknowns": [
    "semantic function, speaker, language, and boundary adequacy require later review"
  ],
  "status": "code_provisional",
  "boundary_basis": ["document_start"],
  "segmenter_version": "structural-boundaries-v5.1"
}
```

### 3.1. Yêu cầu từng trường

| Trường | Kiểu | Yêu cầu                                                                                         |
|---|---|-------------------------------------------------------------------------------------------------|
| `id` | string | Không rỗng, duy nhất trong case; code tạo dạng `{case_id}:lu:{ordinal}` với ordinal bắt đầu từ 1 |
| `case_id` | string | Không rỗng và khớp case đang được xử lý                                                         |
| `text` | string | Bằng chính xác `source_text[start_char:end_char]`; là bản text duy nhất được lưu                |
| `source_span` | object | Chỉ chứa `source_ref`, `start_char`, `end_char`; không được chứa `text`                         |
| `source_span.source_ref` | string | Không rỗng, là đường dẫn đến file source                                                        |
| `source_span.start_char` | integer | Offset ký tự bắt đầu của đoạn text trong file souce                                             |
| `source_span.end_char` | integer | Offset; phải lớn hơn `start_char`                                                               |
| `order` | integer | Bắt đầu từ 0, tăng dần theo thứ tự xuất hiện trong nguồn                                        |
| `functions` | array[string] | Chức năng của legal unit; xem enum và giá trị mặc định của bước code ở bảng dưới                |
| `attributed_to` | object | Mô tả nội dung trong LegalUnit thuộc về ai, gồm `kind` và `party_role`                          |
| `reporting_voice` | string hoặc null | Mô tả ai đang thuật lại nội dung được chủ thể `attributed_to` phát biểu                         |
| `language` | string | Xem enum và giá trị mặc định ở bảng dưới                                                        |
| `confidence` | number | Nằm trong `[0,1]`                                                                               |
| `unknowns` | array[string] | Lý do nếu chưa xác định hoặc chức năng không rõ ràng                                            |
| `status` | string | `code_provisional` ở bước code, `llm_materialized` sau khi có kết quả LLM                       |
| `boundary_basis` | array[string] | Dấu hiệu cấu trúc đã tạo/giữ ranh giới; dùng để theo dõi                                        |
| `segmenter_version` | string | Version                                                                        |

Đây là các trường semantic. Bước code không tự chỉ điền giá trị mặc định; bước LLM được phép thay các giá trị đó:

| Trường | Giá trị có thể điền trong schema                                                                                                                                                                      | Giá trị mặc định ở bước code cứng                      |
|---|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| `functions` | Cho phép mỗi unit được gán nhiều nhãn: `fact`, `issue`, `rule_or_legal_test`, `procedure`, `application_reasoning`, `disposition_or_conclusion`, <br/>2 nhãn này chỉ đứng một mình:`other`, `unknown` | `["unknown"]`                                          |
| `attributed_to.kind` | `current_court`, `party`, `cited_court`, `legislation_or_regulation`, `headnote_or_editor`, `unknown`                                                                                                 | `"unknown"`                                            |
| `attributed_to.party_role` | Chuỗi không rỗng hoặc `null`; chỉ khác `null` khi `kind="party"`                                                                                                                                      | `null`                                                 |
| `reporting_voice` | Cùng enum với `attributed_to.kind`, hoặc `null`                                                                                                                                                       | `null`                                                 |
| `language` | `en`, `fr`, `mixed`, `unknown`                                                                                                                                                                        | `"unknown"`                                            |
| `confidence` | Number trong `[0,1]`                                                                                                                                                                                  | `0.0`                                                  |
| `unknowns` | Danh sách chuỗi nêu lý do bất định; sau bước LLM phải có lý do nếu function, speaker hoặc language vẫn là `unknown`                                                                                   | Cảnh báo chưa được LLM review                          |


## 4. LLM lượt 1: sửa biên

#### Phần này có sử dụng một số ký hiệu trong prompt cho LLM để tiết kiệm token

### 4.1. Input

LLM nhận một cửa sổ văn bản gồm:
- case và chế độ xử lý;
- vùng được phép sửa;
- các biên hiện có, ký hiệu b0, b1, ...;
- các đoạn văn bản, ký hiệu s0, s1, ...;
- E: đoạn được phép sửa;
- R: đoạn chỉ dùng làm ngữ cảnh.
Các ID b* và s* chỉ có hiệu lực trong request hiện tại. Host đồng thời cung cấp JSON Schema để giới hạn LLM chỉ được xóa biên editable hoặc thêm biên trong đoạn editable.

### 4.1. Output

Truyền JSON Schema cho engine để ép LLM chỉ trả:
```json
{
  "version": "...",
  "remove": [],
  "insert": [],
  "review": []
}
```

Ví dụ: 
```json
{
  "version": "legal-unit-two-stage-v1",
  "remove": ["b1"],
  "insert": [
    {
      "s": "s4",
      "before": "The application is therefore dismissed.",
      "nth": 0
    }
  ],
  "review": [
    {
      "s": "s6",
      "k": "quotation",
      "n": "The closing quotation boundary remains ambiguous."
    }
  ]
}
```

### 4.2. `remove`

|           | Yêu cầu                                                    |
|-----------------|------------------------------------------------------------|
| Kiểu            | `array[string]`                                            |
| Giá trị         | Chỉ các ID nằm trong danh sách editable của request        |
| Số lượng tối đa | Số boundary editable trong request                         |

Phương thức này được dùng để ghép 2 unit liền nhau bằng cách xoá boundary giữa chúng

### 4.3. `insert`

Mỗi phần tử phải có đúng ba trường:

| Trường | Kiểu | Yêu cầu |
|---|---|---|
| `s` | string | Segment ID editable thuộc enum của request |
| `before` | string | Exact, case-sensitive, dài 1–120 ký tự |
| `nth` | integer | Chỉ số lần xuất hiện, bắt đầu từ 0 |

Ở đây thực hiện chèn boundary vào sau chuỗi `before`, chuỗi được xác định bằng vị trí thứ `nth` trong segment `s`

Code tìm mọi lần xuất hiện của `before` bên trong đúng segment `s`, rồi đặt boundary
ngay trước lần thứ `nth`. `insert` bị từ chối khi:

- segment không editable hoặc không tồn tại;
- vị trí cắt bên trong suppression marker;
- vị trí trùng một boundary đã có;
- unit rỗng ở giữa.

Mỗi window được thêm tối đa 4 boundary.

### 4.4. `review`

Mỗi phần tử có đúng:

| Trường | Kiểu | Giá trị                                                  |
|---|---|----------------------------------------------------------|
| `s` | string hoặc null | Segment cần xem lại; null nếu không gắn được một segment |
| `k` | string | `boundary`, `citation`, `quotation`, hoặc `context`      |
| `n` | string | Lý do không rỗng, tối đa 160 ký tự theo JSON Schema      |

Mỗi window có tối đa 8 review item. `review` dùng cho trường hợp LLM không chắc.

## 5. LLM lượt 2: phân loại

### 5.1. Input
Sau lượt sửa biên, khóa danh sách unit và chia thành các request tối đa 12
unit. Mỗi request cấp các ID tạm cho các unit: `u0`, `u1`,...

Model không được split, merge, bỏ, thêm hoặc đổi ID.

### 5.1. Output

```json
{
  "version": "legal-unit-two-stage-v1",
  "labels": {
    "u0": {
      "f": ["rule_or_legal_test", "application_reasoning"],
      "a": "current_court",
      "r": null,
      "v": null,
      "l": "en",
      "c": 91,
      "x": []
    },
    "u1": {
      "f": ["issue"],
      "a": "party",
      "r": "appellant",
      "v": "current_court",
      "l": "en",
      "c": 84,
      "x": []
    }
  }
}
```

### 5.2. Schema của một label item

Mỗi item phải có đúng bảy trường:

| Trường | Kiểu | Giá trị hợp lệ                                            | Ý nghĩa |
|---|---|-----------------------------------------------------------|---|
| `f` | array[string] | Xem bảng functions; ít nhất 1, không trùng                | Chức năng pháp lý, cho phép đa nhãn |
| `a` | string | `current_court`, `party`, `cited_court`, `legislation_or_regulation`, `headnote_or_editor`, `unknown` | Chủ thể của mệnh đề |
| `r` | string hoặc null | Chuỗi 1–80 ký tự hoặc null                                | Vai trò cụ thể, chỉ được có khi `a="party"` |
| `v` | string hoặc null | Cùng enum với `a`, hoặc null                              | Giọng đang thuật lại chủ thể trong `a` |
| `l` | string | `en`, `fr`, `mixed`, `unknown`                            | Ngôn ngữ của unit |
| `c` | integer | `0..100`                                                  | Độ tin cậy annotation của model |
| `x` | array[string] | Lý do nếu có phần chưa rõ ràng                            |

### 5.3. `functions` và quy tắc đa nhãn

| Giá trị `f` | Dùng khi |
|---|---|
| `fact` | Nền tảng sự kiện hoặc tình tiết thực tế |
| `issue` | Câu hỏi pháp lý cần được quyết định |
| `rule_or_legal_test` | Quy tắc hoặc phép kiểm tra pháp lý ở mức khái quát |
| `procedure` | Sự kiện hoặc lịch sử tố tụng |
| `application_reasoning` | Áp dụng quy tắc hoặc đánh giá chứng cứ/lập luận |
| `disposition_or_conclusion` | Kết luận, quyết định, lệnh hoặc outcome được nêu rõ |
| `other` | Nội dung hiểu được nhưng không thuộc các chức năng trên |
| `unknown` | Không đủ căn cứ để xác định chức năng |

- `other` phải đứng một mình;
- `unknown` phải đứng một mình.

Ví dụ, một unit vừa nêu test vừa áp dụng test có thể mang
`["rule_or_legal_test", "application_reasoning"]`. 

### 5.4. Enum attribution dùng chung

LLM và LegalUnit cuối dùng cùng tên giá trị. Host giữ nguyên `a` vào
`attributed_to.kind` và `v` vào `reporting_voice`, không chuyển đổi tên.

| Giá trị dùng chung | Ý nghĩa |
|---|---|
| `current_court` | Tòa hiện tại |
| `party` | Một bên trong vụ án |
| `cited_court` | Tòa/bản án được trích dẫn |
| `legislation_or_regulation` | Luật hoặc quy định |
| `headnote_or_editor` | Phần tóm tắt hoặc lời biên tập |
| `unknown` | Chưa xác định được chủ thể |
| `null` | Chỉ dùng cho `v`; thành `reporting_voice=null` |

`a` là nguồn của mệnh đề. `v` là giọng đang thuật lại. Ví dụ, tòa hiện tại
thuật lại lập luận của appellant dùng `a="party"`, `r="appellant"`,
`v="current_court"`.

`r` phải là `null` khi `a` không phải `party`. Khi `a="party"`, `r` vẫn có thể
là `null` nếu vai trò cụ thể không được xác định; nếu khác null thì phải là chuỗi
không rỗng.

### 5.5. Trường hợp không chắc chắn và confidence

Nếu `f` chứa `unknown`, hoặc `a="unknown"`, hoặc `l="unknown"`, thì `x` phải có
ít nhất một lý do không rỗng. Host không tự thêm lý do và không tự thay nhãn lỗi
bằng `unknown`.

`c` là integer `0..100` trong response LLM. Khi materialize, host đổi thành
`confidence = c / 100`, tức number trong `[0,1]`. Pipeline hiện không dùng một
ngưỡng confidence để tự động tuyên bố semantic đúng.

## 6. Schema LegalUnit cuối 

Sau khi label response qua kiểm tra, code dựng mỗi unit có dạng như sau:

```json
{
  "id": "024310.txt:llm:120:356",
  "case_id": "024310.txt",
  "text": "Verbatim source slice",
  "source_span": {
    "source_ref": "agentic_pipeline/legal_unit/samples/cases/024310.txt",
    "start_char": 120,
    "end_char": 356
  },
  "order": 0,
  "functions": ["application_reasoning"],
  "attributed_to": {
    "kind": "current_court",
    "party_role": null
  },
  "reporting_voice": null,
  "language": "en",
  "confidence": 0.91,
  "unknowns": [],
  "status": "llm_materialized",
  "protocol_version": "legal-unit-two-stage-v1"
}
```

