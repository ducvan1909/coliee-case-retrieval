# Biên bản điều phối phản biện vòng 2

## Tài liệu

- `agent_a_review.md`: đánh giá độc lập về coverage, context, attribution, qualifier, treatment và provenance.
- `agent_b_review.md`: đánh giá độc lập về token, compute, cap, cache, retry, update và comparability.
- `agent_a_cross_review.md`: Agent A steelman và phản biện Agent B, sau đó sửa quan điểm.
- `agent_b_cross_review.md`: Agent B steelman và phản biện Agent A, sau đó sửa quan điểm.

Hai bản độc lập được viết trước khi chuyển báo cáo đối phương. Vòng chéo giới hạn tối đa năm phản biện quan trọng và yêu cầu cấu trúc claim → evidence/counterexample → consequence → exact fix → deciding test.

## Điểm hai bên chấp nhận đưa vào contract

1. BM25, semantic-raw và hybrid-raw là các arm riêng; không âm thầm nâng baseline.
2. Source floor phải có quota, tie-break, dedup và gained/lost trace.
3. R3 dùng nested route manifest có checksum cùng sentinel omission sample.
4. Evidence resolver lưu searched ranges/modes, stop reason và cap unique chars/calls/time.
5. Derived field có witness/dependency riêng và acceptance profile theo record type.
6. Cache ledger tách charged, originating và amortized cost; update dùng dependency closure.
7. Mẫu đại diện và safety oversample có mục đích, weighting và gate riêng.

## Bất đồng còn lại

Không bên nào được phép chốt bằng lập luận: raw retrieval nào thắng, source-floor quota, scheduler/frontier expansion, model local, annotation type, derived/AU lane hoặc LLM cap. Các mục này được chuyển thành arms và deciding tests trong `../05_experiment_plan.md`.

Một số lần khởi tạo agent trước đó không tạo output do usage limit hoặc chạy không hoàn tất; chúng không được dùng làm bằng chứng. Bốn file liệt kê ở trên là vòng phản biện hoàn tất.
