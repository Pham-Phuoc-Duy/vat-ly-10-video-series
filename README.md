# Vật Lý 10 — Video Series 🎬

Kho này có một **robot GitHub Actions** tự dựng video từ kịch bản `.md`:
giọng đọc tiếng Việt (Microsoft Edge TTS, miễn phí) + chữ/công thức trên màn hình + phụ đề + thanh tiến độ.

## Cách dùng

1. Viết kịch bản mới, đặt tên bắt đầu bằng `kich-ban` (vd `kich-ban-bai-2.md`) ở thư mục gốc hoặc trong thư mục `kich-ban/`.
2. Commit lên nhánh `main` → robot tự chạy (tab **Actions**).
3. Khoảng 2–5 phút sau, vào mục **Releases** để tải `*.mp4` (kèm phụ đề `.srt` và ảnh bìa `-bia.png`).

Muốn dựng lại bằng tay: **Actions → Dựng video từ kịch bản → Run workflow** (để trống = dựng tất cả).

## Mẫu kịch bản

```markdown
---
tieu_de: Vật nặng rơi nhanh hơn vật nhẹ? SAI!
bai: Bài 10. Sự rơi tự do
giong_doc: vi-VN-HoaiMyNeural   # giọng nữ; giọng nam: vi-VN-NamMinhNeural
khung_hinh: doc                 # doc = 1080x1920 (TikTok/Shorts), ngang = 1920x1080 (YouTube)
toc_do: +5%                     # (tuỳ chọn) đọc nhanh/chậm hơn, vd -10%
---

## Cảnh 1 | Mở đầu
Lời: Câu thuyết minh — được đọc thành tiếng và hiện thành phụ đề.
Hình: Mô tả hình. Chữ trong "ngoặc kép" và công thức $s = \frac{1}{2} g t^2$ sẽ hiện to giữa màn hình.
Chữ: (tuỳ chọn) ghi rõ chữ muốn hiện giữa màn hình, thay cho phần lấy từ Hình.
```

- Cảnh không có chữ "ngoặc kép"/công thức thì hiện tên cảnh.
- Viết số và công thức trong **Lời** bằng chữ để giọng đọc chuẩn (vd "chín phẩy tám mét trên giây bình phương").
- Công thức dùng cú pháp LaTeX trong `$...$` (`\frac`, `^`, `_`, `\Delta`, `\vec`…).

## Thêm hình minh hoạ

Đặt ảnh vào `hinh/<tên-file-kịch-bản>/canh-<số>.png` (hoặc `.jpg`), vd
`hinh/kich-ban-bai-1/canh-2.png`. Ảnh sẽ thay cho phần chữ giữa màn hình của cảnh đó; phụ đề vẫn giữ nguyên.

## Chạy thử trên máy

```bash
pip install -r tools/requirements.txt     # cần có ffmpeg
python tools/dung_video.py kich-ban-bai-1.md --out out
python tools/dung_video.py kich-ban-bai-1.md --out out --khong-giong   # thử nhanh, không cần mạng
```
