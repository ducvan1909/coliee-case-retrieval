# Chẩn đoán K0 AU rỗng

Giữ nguyên package/workload/live checkpoint K0. Không deploy, đổi model, sửa prompt K0 hoặc mở thêm nguồn. Tối đa 3 POST từ client, input reserve <=6000/output <=800 mỗi request, tổng reserve <=30000; unknown usage dừng POST mới. GET hoặc resume không submit trùng job đã có intent.

1. Native CPU XGrammar0.2.1, tokenizer Qwen đúng SHA/revision, vocab248320, EOS248044/248046. `cpu.json`: 2 grammar probe, 8 positive/6 negative, 570 token replay PASS. `cpu_original.json`: exact grammar cả5 request K0 cũ, positive AU witnesses PASS. Không inference trong CPU.
2. Synthetic grammar/plain: cùng nguồn quy tắc tự tạo, cùng prompt, temperature0, thinkingfalse, output800, chỉ khác ebnf. Đếm AU và đọc xem giữ emergency exception; JSON valid riêng không đồng nghĩa control pass.
3. Case011904: cùng8scope/21parts đã gửi, không thêm KOS claim/reviewer answer. Đổi hướng dẫn sang authoring một lượt và chỉ cho finish_case, vẫn cho AU rỗng. Hai biến thay đổi cùng lúc nên không tách causal effect của action khỏi instruction.

Runtime tự warmup trong container có inference riêng theo deployment đã có. Client warmup chỉ GET. Khi runtime inspector chưa truy cập được, không biết usage của startup; không coi 0 POST client là 0 tài nguyên server.
