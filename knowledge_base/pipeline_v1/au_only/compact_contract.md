# Compact AU contract v1

Mỗi target trả một compact result với `aus` từ 0 đến 3 phần tử. Đây chỉ là proposal có neo SentenceAtom; host vẫn kiểm map/source và materialize full output sau đó.

## Decision và coverage

| `decision` | `aus` | `coverage_status` | reason fields |
|---|---:|---|---|
| `positive` | 1–3 | `complete` hoặc `needs_split` | cả hai `null` |
| `hard_negative` | 0 | chỉ `complete` | `hard_negative_reason` enum non-null; `unresolved_reason: null` |
| `unresolved` | 0 | `complete` hoặc `needs_split` | `hard_negative_reason: null`; `unresolved_reason` enum non-null |

`coverage_status: needs_split` nói rằng region không đủ hình dạng hoặc coverage để coi phần chưa trả là đã được kiểm. Nó không tự tạo split, không là hard-negative, và không thay thế `unresolved_reason`.

## AU compact

Mỗi AU mang `kind`, `other_kind`, `claim` (1–300 ký tự), 1–3 `evidence_ref_ids`, `speaker`, `attribution_role`, và `needs_context`.

`needs_context` là mảng unique, có tối đa sáu obligation: `attribution`, `condition`, `exception`, `limit`, `current_court_response`, `cross_block_context`. Nó không chứa boolean, offset, quote, hay suy luận legal metadata. `other_kind` phải là `null` trừ `kind: other`.

Contract này không dispatch split model và không cho normalizer bịa condition, exception, limit, court treatment, quote hay offset.

`hard_negative_reason` giữ nguyên distinction semantic của full contract; normalizer không được đổi hard-negative thành unresolved hoặc tự chọn reason.

## Atom expansion policy

Host không gửi source fragment. Với mỗi requested `source_ref`, host lấy toàn bộ SentenceAtom có half-open span giao ref đó, render nguyên văn atom và gắn `TARGET` nếu atom giao target ref, ngược lại `CONTEXT`. Preflight ghi `requested_char_union`, `rendered_atom_char_union`, `expansion_chars`, và estimate input từ UTF-8 byte union của atoms render cộng 512 protocol tokens. Không có target-intersecting atom sau expansion là preflight failure.
