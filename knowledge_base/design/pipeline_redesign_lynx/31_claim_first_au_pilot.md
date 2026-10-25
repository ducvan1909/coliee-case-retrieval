# Pilot AU theo legal point, một lượt chính

Sau live v1, bản sửa hướng dẫn `claim_first_v2` được mô tả ở [kế hoạch giữ nghĩa và đủ legal point](32_claim_first_v2_fidelity_coverage.md). Wire vẫn là `au-claim-v1`; không thêm trường hay vòng kiểm tra mặc định. Khi đổi prompt phải tạo workload/root mới, không resume checkpoint v1 bằng code v2. Kết quả v1 được giữ nguyên làm đối chứng lịch sử.

## Mục tiêu và phạm vi

Thử hướng tạo AU trực tiếp: model viết proposition pháp lý rồi chọn evidence cho proposition đó. Tách riêng module `knowledge_base/pipeline_v1/au_claim/`, không đổi profile cũ hoặc artifact lịch sử. Dùng model 9B, cấu hình `.env` hiện tại, cùng 16 TARGET đã khóa và 18 reference KOS. Chưa mở corpus, đổi reranker, thêm NER, đổi model hoặc làm AU–NN match.

Thí nghiệm thay cách tạo AU và điều phối context; không thể quy toàn bộ khác biệt cho riêng một câu prompt. KOS là reference calibration, không human gold. Không đưa Claim/Limits/kind/Issue KOS vào model.

## Luồng xử lý

1. Host lấy đầy đủ nguyên văn TARGET và map câu hiện có; cấp alias ngắn `s1`, `s2`... Không tính offset bằng model. Giữ source hash/offset ở host.
2. Một request chính nhận TARGET, định nghĩa kind ngắn và vài ví dụ tổng hợp không lấy đáp án KOS. Model trả `aus` và `context_request`.
3. Mỗi AU có `claim`, `kind`, `evidence_ids`, `limits`. Claim một hoặc hai câu, không phải bản sao ID/span. Cho phép 0–3 AU để cùng trần pilot cũ, không cấp ba anchor slot để model điền. Một holding và rationale hỗ trợ thường là một AU; tách khi có legal point độc lập.
4. Host gắn evidence, provenance, ID AU và lưu checkpoint. Chỉ gộp bản ghi hoàn toàn giống nhau về claim/kind/evidence/limits sau chuẩn hóa whitespace; cùng evidence nhưng proposition/phủ định khác chỉ đánh dấu để xem, không fuzzy-merge.
5. Chỉ mở context nếu model chỉ rõ câu hỏi thiếu có thể đổi nghĩa hoặc tư cách AU. Không mở chỉ để điền đủ speaker/scope hoặc khôi phục tên authority bị che. Không xác định được kind thì dùng null; không loại claim rõ chỉ vì kind chưa chắc.
6. Tối đa một lượt bổ sung/TARGET: gửi **toàn bộ TARGET ban đầu**, bounded context đã khóa và draft. Cho model sửa lại claim, kind, evidence và limits. Không tiếp tục khóa lựa chọn sai từ lượt đầu. Kết quả còn thiếu thông tin được giữ riêng, không tự gọi vòng thứ ba.

Mọi AU trong lượt bổ sung cần ít nhất một evidence thuộc TARGET, nhưng điều kiện này chỉ kiểm địa chỉ; không chứng minh model không lấy legal point từ context. Pilot phải đọc nguồn để kiểm ownership và attribution. Lời bên đối lập trong context không được biến thành speaker của proposition của tòa.

## Wire tối thiểu

```json
{
  "aus": [
    {
      "claim": "A short legal proposition supported by the supplied source.",
      "kind": "procedural_rule",
      "evidence_ids": ["s1", "s2"],
      "limits": null
    }
  ],
  "context_request": null
}
```

`kind` dùng các kind đang có hoặc null, bỏ `unresolved_kind` để tránh diễn giải một nhãn unknown thành nội dung pháp lý. `context_request` nếu có chỉ gồm một câu hỏi ngắn. Evidence context dùng `c1`... và chỉ xuất hiện ở lượt bổ sung. Không có global decision, reason code, primary/support bắt buộc, speaker slots hoặc ID AU do model viết.

Giới hạn pilot: claim tối đa 500 ký tự, limits 250, câu hỏi context 200; output cap 800 token như baseline. Đây là trần, không phải độ dài cần điền. Giữ JSON grammar đơn giản, enum/ref hợp lệ và kiểm Unicode/độ dài. Output bị cắt là lỗi cần báo, không tự coi là negative hoặc tự thêm nhiều vòng sửa JSON.

## Những phần giữ và bỏ

Giữ source bất biến, hash/offset do host quản lý, cache/checkpoint, warmup chung, GET-before-POST và counters thực tế. Đây là phần local/transport đã hoạt động, không phải lý do đọc lại bằng LLM.

Bỏ immutable primary/support/kind giữa hai lượt, các cặp trạng thái global/anchor phức tạp, nghĩa vụ điền speaker/scope và vòng context mặc định. Không thêm verifier LLM cho mọi AU. Claim tự do hơn tạo rủi ro diễn giải vượt nguồn; exact evidence không tự chứng minh entailment.

## Kiểm thử và chạy

Local trước: khóa cùng source/TARGET/context; payload không lộ annotation KOS; alias đúng; first-pass không nhận context; bổ sung nhận cả TARGET chưa chọn; sửa được claim/kind/evidence; chặn evidence chỉ thuộc context; null kind không cản AU; phân biệt duplicate đúng biểu diễn với các claim khác nghĩa; timeout, truncation, resume và cache.

Default CLI/script chỉ prepare/preflight/mock/compare. `--execute` hoặc `-Execute` mới gọi endpoint. Tối đa 16 request chính + 16 bổ sung, concurrency 2, không inference trong đợt triển khai local. Budget và token thực tính cả lỗi/retry; không dùng USD/request giả định. Input reservation bằng byte phải ghi rõ không phải token.

So đầu ra với profile cũ và KOS trên cùng nguồn: proposition, omission, điều kiện/ngoại lệ/phủ định, attribution, legal function, duplicate, số lần cần context và tổng token. Baseline cũ dùng lại kết quả đã có, không tự gọi lại. Không chấm Claim bằng string similarity, không coi overlap là semantic match. Không coi ít request do đọc thiếu/ngừng sớm là tiết kiệm.

Quyết định promote chỉ sau live và review nguồn. Mục tiêu gần một request/TARGET là giả thuyết cần đo. Nếu vẫn có claim vượt nguồn, ownership sai hoặc mất điều kiện đáng kể thì chưa promote, dù JSON và offsets đạt.
