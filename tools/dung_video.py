#!/usr/bin/env python3
"""Robot dựng video Vật Lý 10 từ kịch bản Markdown.

Kịch bản (.md) gồm phần đầu (front matter) và các cảnh:

    ---
    tieu_de: Vật nặng rơi nhanh hơn vật nhẹ? SAI!
    bai: Bài 10. Sự rơi tự do
    giong_doc: vi-VN-HoaiMyNeural      # hoặc vi-VN-NamMinhNeural
    khung_hinh: doc                     # doc = 1080x1920 (TikTok), ngang = 1920x1080
    toc_do: +5%                         # (tuỳ chọn) tốc độ đọc
    ---

    ## Cảnh 1 | Mở đầu
    Lời: câu thuyết minh sẽ được đọc thành tiếng và hiện phụ đề.
    Hình: mô tả hình. Chữ trong "ngoặc kép" và công thức $...$ sẽ hiện lên màn hình.
    Chữ: (tuỳ chọn) dòng chữ hiện to giữa màn hình, ghi đè phần lấy từ Hình.

Ảnh minh hoạ (tuỳ chọn): đặt ở hinh/<ten-file-kich-ban>/canh-1.png (hoặc .jpg).

Cách chạy:
    python tools/dung_video.py kich-ban-bai-1.md --out out
    python tools/dung_video.py kich-ban-bai-1.md --out out --khong-giong   # thử nhanh, không cần mạng
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FPS = 30
CANH_DEM_GIAY = 0.45      # khoảng lặng cuối mỗi cảnh
TU_MOI_GIAY = 2.8          # ước lượng tốc độ đọc khi không có giọng

# ---------- Màu sắc ----------
NEN_TREN = (16, 24, 48)
NEN_DUOI = (30, 58, 110)
MAU_CHU = (255, 255, 255)
MAU_PHU = (180, 200, 235)
MAU_NHAN = (255, 196, 61)
MAU_PHU_DE_NEN = (0, 0, 0, 170)


# ---------- Đọc kịch bản ----------
@dataclass
class Canh:
    so: int
    ten: str
    loi: str = ""
    hinh: str = ""
    chu: str = ""


@dataclass
class KichBan:
    duong_dan: Path
    meta: dict = field(default_factory=dict)
    canh: list[Canh] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.duong_dan.stem


def doc_kich_ban(path: Path) -> KichBan:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    kb = KichBan(path)
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.split(" #", 1)[0].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                kb.meta[k.strip()] = v.strip().strip('"')
        text = text[m.end():]

    hien_tai: Canh | None = None
    khoa: str | None = None
    for line in text.splitlines():
        h = re.match(r"^##\s*Cảnh\s*(\d+)\s*(?:[|:\-–]\s*(.*))?$", line.strip(), re.I)
        if h:
            hien_tai = Canh(int(h.group(1)), (h.group(2) or "").strip())
            kb.canh.append(hien_tai)
            khoa = None
            continue
        if hien_tai is None:
            continue
        k = re.match(r"^(Lời|Hình|Chữ)\s*:\s*(.*)$", line.strip(), re.I)
        if k:
            khoa = {"lời": "loi", "hình": "hinh", "chữ": "chu"}[k.group(1).lower()]
            setattr(hien_tai, khoa, k.group(2).strip())
        elif khoa and line.strip():
            setattr(hien_tai, khoa, (getattr(hien_tai, khoa) + " " + line.strip()).strip())
    if not kb.canh:
        raise SystemExit(f"{path}: không tìm thấy cảnh nào (cần tiêu đề dạng '## Cảnh 1 | Tên cảnh').")
    return kb


def muc_tren_man_hinh(c: Canh) -> list[tuple[str, str]]:
    """Trả về danh sách ('chu'|'cong_thuc', nội dung) để hiện giữa màn hình."""
    nguon = c.chu or c.hinh
    muc: list[tuple[str, str]] = []
    if c.chu:
        for phan in re.split(r"(\$[^$]+\$)", c.chu):
            phan = phan.strip()
            if phan:
                muc.append(("cong_thuc" if phan.startswith("$") else "chu", phan))
        return muc
    for m in re.finditer(r"\$([^$]+)\$|[\"“]([^\"”]+)[\"”]", nguon):
        if m.group(1):
            muc.append(("cong_thuc", f"${m.group(1)}$"))
        else:
            muc.append(("chu", m.group(2)))
    return muc


# ---------- Phông chữ ----------
FONT_DIRS = [Path(__file__).resolve().parent.parent / "fonts",
             Path("/usr/share/fonts/truetype/noto"),
             Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts")]


def tim_font(dam: bool) -> str:
    ten = (["NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"] if dam
           else ["NotoSans-Regular.ttf", "DejaVuSans.ttf"])
    for d in FONT_DIRS:
        for t in ten:
            for p in d.rglob(t) if d.exists() else []:
                return str(p)
    raise SystemExit("Không tìm thấy phông chữ hỗ trợ tiếng Việt (cài fonts-noto-core hoặc fonts-dejavu-core).")


_font_cache: dict = {}


def font(co: int, dam: bool = True):
    key = (co, dam)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(tim_font(dam), co)
    return _font_cache[key]


def ngat_dong(draw, text: str, f, rong: int) -> list[str]:
    dong, hien = [], ""
    for tu in text.split():
        thu = (hien + " " + tu).strip()
        if draw.textlength(thu, font=f) <= rong or not hien:
            hien = thu
        else:
            dong.append(hien)
            hien = tu
    if hien:
        dong.append(hien)
    return dong


def ve_khoi_chu(draw, text, f, rong, cx, y, mau, gian=1.25, vien=0):
    for d in ngat_dong(draw, text, f, rong):
        w = draw.textlength(d, font=f)
        draw.text((cx - w / 2, y), d, font=f, fill=mau, stroke_width=vien, stroke_fill=(0, 0, 0))
        y += int(f.size * gian)
    return y


def anh_cong_thuc(tex: str, co_px: int) -> Image.Image:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    fig = plt.figure(figsize=(0.01, 0.01), dpi=100)
    fig.text(0, 0, tex, fontsize=co_px * 0.75, color="white")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.15, dpi=100)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


# ---------- Vẽ khung hình ----------
def nen(W, H) -> Image.Image:
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(NEN_TREN, NEN_DUOI)))
    return img


def tim_anh_minh_hoa(kb: KichBan, c: Canh) -> Path | None:
    goc = kb.duong_dan.resolve().parent
    for thu_muc in [goc / "hinh" / kb.slug, goc.parent / "hinh" / kb.slug]:
        for duoi in ("png", "jpg", "jpeg", "webp"):
            p = thu_muc / f"canh-{c.so}.{duoi}"
            if p.exists():
                return p
    return None


def ve_khung(kb: KichBan, c: Canh, W, H, phu_de: str, tien_do: float, so_canh: int) -> Image.Image:
    img = nen(W, H).convert("RGBA")
    d = ImageDraw.Draw(img)
    doc = H > W
    le = int(W * 0.07)
    rong = W - 2 * le
    s = W / 1080 if doc else H / 1080

    # Đầu trang: tên bài + thẻ cảnh
    y = int(H * (0.06 if doc else 0.05))
    bai = kb.meta.get("bai", "Vật Lý 10")
    d.text((le, y), bai, font=font(int(38 * s), False), fill=MAU_PHU)
    y += int(70 * s)
    the = f"Cảnh {c.so}/{so_canh}" + (f" · {c.ten}" if c.ten else "")
    ft = font(int(40 * s))
    tw = d.textlength(the, font=ft)
    d.rounded_rectangle([le, y, le + tw + 48 * s, y + 66 * s], radius=int(33 * s), fill=MAU_NHAN)
    d.text((le + 24 * s, y + 10 * s), the, font=ft, fill=NEN_TREN)

    # Vùng giữa
    vung_tren = y + int(110 * s)
    vung_duoi = int(H * (0.70 if doc else 0.74))
    anh = tim_anh_minh_hoa(kb, c)
    muc = muc_tren_man_hinh(c)
    if anh:
        im = Image.open(anh).convert("RGBA")
        im.thumbnail((rong, vung_duoi - vung_tren))
        img.alpha_composite(im, ((W - im.width) // 2, vung_tren + (vung_duoi - vung_tren - im.height) // 2))
    else:
        if not muc:
            muc = [("chu", c.ten or kb.meta.get("tieu_de", ""))]
        khoi = []
        for loai, nd in muc:
            if loai == "cong_thuc":
                try:
                    im = anh_cong_thuc(nd, int(170 * s))
                    if im.width > rong:
                        im = im.resize((rong, int(im.height * rong / im.width)))
                    khoi.append(("anh", im, im.height))
                    continue
                except Exception as e:  # công thức lỗi -> hiện dạng chữ
                    print(f"  ! Không vẽ được công thức {nd}: {e}", file=sys.stderr)
                    nd = nd.strip("$")
            co = int((110 if len(nd) < 18 else 84 if len(nd) < 40 else 64) * s)
            f = font(co)
            n = len(ngat_dong(d, nd, f, rong))
            khoi.append(("chu", (nd, f), int(n * co * 1.25)))
        gian = int(50 * s)
        tong = sum(k[2] for k in khoi) + gian * (len(khoi) - 1)
        yy = vung_tren + max(0, (vung_duoi - vung_tren - tong) // 2)
        for i, (loai, nd, cao) in enumerate(khoi):
            if loai == "anh":
                img.alpha_composite(nd, ((W - nd.width) // 2, yy))
            else:
                ve_khoi_chu(d, nd[0], nd[1], rong, W / 2, yy, MAU_NHAN if i == 0 else MAU_CHU, vien=int(3 * s))
            yy += cao + gian

    # Phụ đề
    if phu_de:
        f = font(int(58 * s))
        dong = ngat_dong(d, phu_de, f, rong - int(40 * s))
        cao = int(len(dong) * f.size * 1.3 + 50 * s)
        y0 = int(H * (0.76 if doc else 0.79))
        lop = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(lop).rounded_rectangle([le - 10, y0, W - le + 10, y0 + cao], radius=int(28 * s), fill=MAU_PHU_DE_NEN)
        img.alpha_composite(lop)
        d = ImageDraw.Draw(img)
        ve_khoi_chu(d, phu_de, f, rong - int(40 * s), W / 2, y0 + int(25 * s), MAU_CHU, gian=1.3)

    # Thanh tiến độ
    cao_tt = int(12 * s)
    d.rectangle([0, H - cao_tt, W, H], fill=(255, 255, 255, 50))
    d.rectangle([0, H - cao_tt, int(W * tien_do), H], fill=MAU_NHAN)
    return img.convert("RGB")


def anh_bia(kb: KichBan, W, H) -> Image.Image:
    img = nen(W, H)
    d = ImageDraw.Draw(img)
    s = W / 1080 if H > W else H / 1080
    le = int(W * 0.08)
    tieu_de = kb.meta.get("tieu_de", kb.slug)
    f = font(int(120 * s))
    n = len(ngat_dong(d, tieu_de, f, W - 2 * le))
    y = (H - n * f.size * 1.25) / 2
    ve_khoi_chu(d, tieu_de, f, W - 2 * le, W / 2, y, MAU_NHAN, vien=int(4 * s))
    ve_khoi_chu(d, kb.meta.get("bai", "Vật Lý 10"), font(int(52 * s), False), W - 2 * le, W / 2,
                y - 120 * s, MAU_PHU)
    return img


# ---------- Phụ đề & giọng đọc ----------
def chia_phu_de(loi: str, toi_da_tu: int) -> list[str]:
    cau = [x.strip() for x in re.split(r"(?<=[.,!?;:])\s+", loi) if x.strip()]
    doan: list[str] = []
    for c in cau:
        tu = c.split()
        if len(tu) > toi_da_tu:               # câu quá dài -> chia đều
            so = -(-len(tu) // toi_da_tu)
            co = -(-len(tu) // so)
            while len(tu) > co:
                doan.append(" ".join(tu[:co]))
                tu = tu[co:]
        if doan and len(tu) <= 3 and len(doan[-1].split()) + len(tu) <= toi_da_tu:
            doan[-1] += " " + " ".join(tu)
        else:
            doan.append(" ".join(tu))
    return doan or [""]


def thoi_luong(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


async def doc_tts(text: str, giong: str, toc_do: str, ra: Path):
    import edge_tts
    loi_cuoi = None
    for lan in range(4):
        try:
            await edge_tts.Communicate(text, giong, rate=toc_do).save(str(ra))
            if ra.exists() and ra.stat().st_size > 1000:
                return
        except Exception as e:
            loi_cuoi = e
        await asyncio.sleep(3 * (lan + 1))
    raise RuntimeError(f"Không tạo được giọng đọc ({giong}): {loi_cuoi}")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def giay_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


# ---------- Dựng video ----------
def dung(path: Path, out_dir: Path, co_giong: bool) -> Path:
    kb = doc_kich_ban(path)
    doc = kb.meta.get("khung_hinh", "doc").lower() not in ("ngang", "ngan", "16:9")
    W, H = (1080, 1920) if doc else (1920, 1080)
    giong = kb.meta.get("giong_doc", "vi-VN-HoaiMyNeural")
    toc_do = kb.meta.get("toc_do", "+0%")
    if not re.match(r"^[+-]\d+%$", toc_do):
        toc_do = "+0%"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"▶ {path.name}: {len(kb.canh)} cảnh, {W}x{H}, giọng {giong if co_giong else '(tắt)'}")

    tmp = Path(tempfile.mkdtemp(prefix=f"video-{kb.slug}-"))
    doan_video: list[Path] = []
    srt: list[str] = []
    t_tong = 0.0
    # Ước lượng tổng thời lượng để vẽ thanh tiến độ: làm 2 lượt (âm thanh trước, hình sau)
    am_thanh: list[tuple[Path, float]] = []
    for c in kb.canh:
        a = tmp / f"canh-{c.so}.m4a"
        if co_giong and c.loi:
            mp3 = tmp / f"canh-{c.so}.mp3"
            asyncio.run(doc_tts(c.loi, giong, toc_do, mp3))
            dur = thoi_luong(mp3) + CANH_DEM_GIAY
            ffmpeg("-i", str(mp3), "-af", f"apad=whole_dur={dur}", "-ar", "44100", "-ac", "2",
                   "-c:a", "aac", "-b:a", "160k", str(a))
        else:
            dur = max(2.5, len(c.loi.split()) / TU_MOI_GIAY) + CANH_DEM_GIAY
            ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{dur}",
                   "-c:a", "aac", "-b:a", "160k", str(a))
        am_thanh.append((a, thoi_luong(a)))
        print(f"  • Cảnh {c.so}: {am_thanh[-1][1]:.1f}s")
    tong = sum(d for _, d in am_thanh)

    for c, (a, dur) in zip(kb.canh, am_thanh):
        doan = chia_phu_de(c.loi, 12 if doc else 16)
        noi = dur - CANH_DEM_GIAY
        trong_so = [max(len(x), 1) for x in doan]
        list_txt = tmp / f"canh-{c.so}.txt"
        dong_list = []
        t = 0.0
        for i, (pd, w) in enumerate(zip(doan, trong_so)):
            d_pd = noi * w / sum(trong_so)
            if i == len(doan) - 1:
                d_pd = dur - t
            khung = tmp / f"c{c.so}-{i}.png"
            ve_khung(kb, c, W, H, pd, (t_tong + t) / tong, len(kb.canh)).save(khung)
            dong_list += [f"file '{khung}'", f"duration {d_pd:.3f}"]
            if pd:
                srt.append(f"{len(srt) + 1}\n{giay_srt(t_tong + t)} --> {giay_srt(t_tong + t + min(d_pd, noi - t + 0.2))}\n{pd}\n")
            t += d_pd
        dong_list.append(f"file '{khung}'")  # yêu cầu của concat demuxer
        list_txt.write_text("\n".join(dong_list) + "\n", encoding="utf-8")

        seg = tmp / f"canh-{c.so}.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_txt), "-i", str(a),
               "-vf", f"fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.25",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
               "-c:a", "copy", "-t", f"{dur:.3f}", "-shortest", str(seg))
        doan_video.append(seg)
        t_tong += dur

    noi_list = tmp / "tat-ca.txt"
    noi_list.write_text("".join(f"file '{p}'\n" for p in doan_video), encoding="utf-8")
    mp4 = out_dir / f"{kb.slug}.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(noi_list), "-c", "copy", "-movflags", "+faststart", str(mp4))
    (out_dir / f"{kb.slug}.srt").write_text("\n".join(srt), encoding="utf-8")
    anh_bia(kb, W, H).save(out_dir / f"{kb.slug}-bia.png")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"✔ {mp4} ({thoi_luong(mp4):.1f}s)")
    return mp4


def main():
    ap = argparse.ArgumentParser(description="Dựng video từ kịch bản .md")
    ap.add_argument("kich_ban", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--khong-giong", action="store_true", help="bỏ giọng đọc (thử nhanh, không cần mạng)")
    a = ap.parse_args()
    loi = 0
    for p in a.kich_ban:
        try:
            dung(p, a.out, not a.khong_giong)
        except Exception as e:
            loi += 1
            print(f"✘ {p}: {e}", file=sys.stderr)
    sys.exit(1 if loi else 0)


if __name__ == "__main__":
    main()
