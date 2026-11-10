# Deploy Qwen3-Embedding-4B lên Modal

**Cấu hình hiện hành: GPU L4 theo yêu cầu người dùng.** Run hiện hành là `pipeline_v2/artifacts/m3_pilot_20261106_l4_v1`, đã tạo plan và audit local PASS, 20/20 kiểm thử liên quan PASS. Plan A10 `m3_pilot_20261106_v1` được giữ làm lịch sử và bị guard từ chối với profile L4; không sửa checksum/profile trong plan cũ để vượt guard. `.env` không thay đổi. GPU/deploy thực chưa chạy trong bước cập nhật này; receipts ở `reviews/m3_l4_update_20261106_v1/`.

File deployment đã có: `pipeline_v2/deployments/modal/qwen3_embed.py`, engine `engine.py` bên cạnh. App/GPU/model/revision/dimensions nằm trong profile M3 đã freeze; helper mới `pipeline_v2/deploy_modal.py` đọc `.env` local rồi gọi đúng file đó, không thay source/profile M3 hoặc plan đã khóa.

## 1. Cấu hình local

File `pipeline_v2/.env` đã tạo và được Git ignore; `pipeline_v2/.env.example` là mẫu không credential. Không copy token từ profile SDK vào file một cách tự động.

```dotenv
MODAL_PROFILE=
MODAL_ENVIRONMENT=
MODAL_TOKEN_ID=
MODAL_TOKEN_SECRET=
```

- Đã đăng nhập Modal trên máy: giữ trống token ID/secret. Profile/environment trống dùng lựa chọn sẵn có của SDK/workspace. Có thể điền tên profile/environment thực sự muốn dùng.
- Dùng API token riêng: điền **cả hai** ID và secret trực tiếp vào `.env`. Không gửi token trong chat. File chỉ phục vụ client local, không upload lên Modal.
- Chưa đăng nhập và không dùng token riêng: chạy lệnh dưới rồi hoàn tất đăng nhập trong trình duyệt:

```powershell
Set-Location E:/Git/coliee-case-retrieval
& .venv/Scripts/python.exe -m modal token new --activate
```

SDK hỗ trợ API token pair hoặc profile đã lưu, xem [Modal config](https://modal.com/docs/reference/modal.config) và [CLI token](https://modal.com/docs/reference/cli/token). Profile được chọn không ghi đè token pair đã có trong environment: SDK ưu tiên environment credentials.

Helper nhận bốn key trên, không `eval`, chạy shell hay mở rộng `$VARIABLE`. Dòng comment phải đứng riêng; giá trị có quote được bỏ cặp quote ngoài, `#` trong giá trị được giữ. Giá trị không rỗng trong `.env` ưu tiên hơn process environment; dòng rỗng không xóa credentials/environment đang có. Token pair điền thiếu một vế bị chặn trước khi gọi Modal. Không đặt model/GPU/app/volume vào `.env` để override ngầm profile M3.

## 2. Kiểm local và deploy

```powershell
Set-Location E:/Git/coliee-case-retrieval
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal check
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal deploy
```

`check` chỉ kiểm cấu hình local và in metadata an toàn, không xác thực tài khoản qua mạng hay chứng minh deployment chạy được. `deploy` mới gọi Modal thực; không cần truyền token trên argv. CLI kế thừa `.venv` và giữ exit code của Modal.

Cấu hình hiện tại:
- App `coliee-pipeline-v2-embed-m3-pilot-v1`.
- Volume model cache `coliee-pipeline-v2-qwen3-4b-cache-v1`.
- Model `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`.
- GPU L4, tối đa một container, min0, idle60s; BF16/2560dimensions/last-token/L2 theo M3.

SDK báo deploy thành công nghĩa là app/image đã đăng ký. Do min0 và lazy load, **model weights được tải/load ở lần gọi GPU đầu tiên**, không suy model đã warm chỉ từ deploy. Bản hiện tại dùng authenticated Modal SDK class `Embedder`, không tạo public HTTP embedding URL; client gọi qua app/class được cấu hình.

## 3. Preflight GPU sau deploy

Khởi động Qdrant Docker theo [hướng dẫn DB](M3_QDRANT_DOCKER.md), sau đó:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 preflight --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1
```

Lệnh này nạp cùng `.env`, kiểm Qdrant và thực sự gọi GPU để kiểm token/EOS/hash/model/pooling/batch parity. Đây mới là preflight thực, có thể tải weights và phát sinh inference; không phải lệnh local `check`.

Pilot và resume bằng cùng helper (không tự chạy full):

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 run --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1 --stop-after-batches 1
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 run --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 verify --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1 --restore-test
```

`m3 search` cũng đi qua helper nếu cần credentials trong `.env`. Chỉ chạy restore test một lần trên cùng run vì collection `_restore` không bị ghi đè. Xem [M3](M3.md) để biết scope, receipts và giới hạn nghiệm thu. AG chỉ review/test/chạy lệnh có sẵn; production fixes vẫn do Codex.

## Trạng thái chuẩn bị

Trong bước tạo helper/env/hướng dẫn này chưa deploy, đăng nhập hộ user, gọi inference hoặc khởi động Docker. `.env` thực ban đầu không chứa token; có thể dùng ngay nếu SDK đã đăng nhập, hoặc điền credentials local theo bước1.

Helper đã freeze; **12/12 kiểm thử độc lập PASS (0,591s)**, chỉ dùng temporary env và subprocess mocks. Check thực trên cấu hình local PASS ở trạng thái `local_configuration_only`, authentication chưa kiểm, network requests0. Git xác nhận `.env` được ignore và không tracked. Fingerprint M3 `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63` không đổi nên plan1.024passages vẫn khớp; không phải replan chỉ vì thêm helper này.

Evidence: `reviews/modal_deploy_env_validation_v1/{REPORT.md,preparation_receipt.json}`. M3 suite104tests là checkpoint trước helper; bước này chỉ chạy12tests helper phù hợp thay đổi, không lặp toàn suite M3 không đổi. Không suy local PASS thành deploy/GPU/pilot PASS.
