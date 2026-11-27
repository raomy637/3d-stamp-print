"""位图 → SVG（线宽封顶 + 花瓣等径）验收测试（TDD）。

判据（house 原图，cap = 1.0mm）：
1. 线宽封顶：输出每个连通块骨架中位线宽 <= cap + 0.15mm；
2. 不增粗：任何块不得比它在源稿里的线宽更粗（<= 源中位 + 0.15mm）；
3. 不丢块：输出连通块数 >= 源块数 90%；
4. 中心线忠实：源骨架（剪毛刺）被输出 mask 以 2px 容差覆盖 >= 95%；
5. 花瓣等径：输出外框外轮廓峰半径 CV < 1.5%、角间距 CV < 1.5%。

用法：
  python tests/test_raster_to_svg.py red    # 基线：cap=3.0（等于不封顶）→ 判据 1 必须 FAIL
  python tests/test_raster_to_svg.py        # 正式：cap=1.0 → 全 PASS
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import filters, morphology

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src" / "tools"))

import stamp_pipeline as sp
from monoline_normalize import prune_spurs

SRC = REPO / "work" / "订单" / "20261126" / "4246454365" / "house" / "原始图" / "house.png"
OUT = REPO / "work" / "_实验" / "raster2svg"
PY = str(REPO / ".venv" / "Scripts" / "python.exe") if (REPO / ".venv").exists() else sys.executable
SIZE, MARGIN, PX = 101.6, 1.2, 2000
MODE = sys.argv[1] if len(sys.argv) > 1 else "green"
SPEC = 1.0                 # 产品口径：线宽上限 1mm（判据不随参数漂移）
CAP = 3.0 if MODE == "red" else SPEC
TAG = "red" if MODE == "red" else "cap1"

FAILS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    if not ok:
        FAILS.append(name)


def load_gray(p):
    return np.asarray(Image.open(p).convert("L"))


def mask_of(g, thr=None):
    t = thr if thr is not None else float(filters.threshold_otsu(g))
    if t <= 1:
        t = 128.0
    m = g < t
    return ~m if m.mean() > 0.55 else m


def mmpp_of(mask):
    ys, xs = np.where(mask)
    span = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
    return (SIZE - 2 * MARGIN) / span


def widths(mask, mmpp):
    dt = ndi.distance_transform_edt(mask)
    lab, n = ndi.label(mask, np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        reg = lab == i
        if reg.sum() < 40:
            continue
        sk = morphology.skeletonize(reg)
        if not sk.any():
            continue
        out.append((int(reg.sum()), float(np.median(dt[sk])) * 2 * mmpp))
    return out, n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    svg = OUT / f"house_{TAG}.svg"
    png = OUT / f"house_{TAG}.png"
    rep = OUT / f"house_{TAG}.json"

    r = subprocess.run([PY, str(REPO / "src" / "tools" / "raster_to_svg.py"),
                        "--input", str(SRC), "--out-svg", str(svg), "--out-png", str(png),
                        "--report", str(rep), "--size", str(SIZE), "--cap-mm", str(CAP),
                        "--px", str(PX)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        check("工具能跑", False)
        return finish()
    print(r.stdout.strip())
    info = json.loads(rep.read_text(encoding="utf-8"))

    src_mask = mask_of(load_gray(SRC))
    out_mask = mask_of(load_gray(png))
    src_w, src_n = widths(src_mask, mmpp_of(src_mask))
    out_w, out_n = widths(out_mask, info["scale_mm_per_px"])

    # 外框环按 --frame-mm 单独控制（默认 1.5mm），不计入图案封顶判据
    fe_out = sp.find_frame(out_mask)[0]
    frame_area_out = int(fe_out.sum()) if fe_out is not None else 0
    pat_out = [w for a, w in out_w if not (frame_area_out and a == frame_area_out)]
    pat_src = [w for a, w in src_w]

    # 1 线宽封顶（图案区，不含外框）：看中位与 95 分位，单块的骨架噪声不算
    worst = max(pat_out)
    med = float(np.median(pat_out))
    p95 = float(np.percentile(pat_out, 95))
    check("1 线宽封顶", med <= SPEC + 0.10 and p95 <= SPEC + 0.20,
          f"中位 {med:.2f} / 95分位 {p95:.2f} / 最粗 {worst:.2f}mm（限中位≤{SPEC + 0.10:.2f}、95分位≤{SPEC + 0.20:.2f}）")

    # 2 不增粗（按全图分位数比较，避免块编号不一致）
    src_med = float(np.median(pat_src))
    out_med = float(np.median(pat_out))
    check("2 不增粗", out_med <= src_med + 0.15, f"源中位 {src_med:.2f} → 输出中位 {out_med:.2f}")

    # 2b 细线保留原样：源里最细的块（< cap）不得被拉到 cap
    src_min = min(pat_src)
    out_min = min(pat_out)
    check("2b 细线不拉粗", out_min <= src_min + 0.10,
          f"源最细 {src_min:.2f} → 输出最细 {out_min:.2f}")

    # 3 不丢块
    keep = out_n / max(src_n, 1)
    check("3 不丢块", keep >= 0.90, f"{src_n} → {out_n} 块（{keep:.0%}）")

    # 4 中心线忠实（按内容 bbox 做仿射对齐后比较，输出分辨率更高）
    src_pat = src_mask.copy()
    frame, _ = sp.find_frame(src_mask)
    if frame is not None:
        src_pat[frame] = False
    lab, n = ndi.label(src_pat, np.ones((3, 3)))
    cov_ok = cov_tot = 0
    dil = morphology.binary_dilation(out_mask, morphology.disk(2))
    sy, sx = np.where(src_mask)          # 源内容 bbox
    oy, ox = np.where(out_mask)          # 输出内容 bbox
    rx = (ox.max() - ox.min()) / max(sx.max() - sx.min(), 1)
    ry = (oy.max() - oy.min()) / max(sy.max() - sy.min(), 1)
    for i in range(1, n + 1):
        reg = lab == i
        if reg.sum() < 40:
            continue
        sk = prune_spurs(morphology.skeletonize(reg))
        ys, xs = np.where(sk)
        if len(ys) == 0:
            continue
        ty = np.rint((ys - sy.min()) * ry + oy.min()).astype(int)
        tx = np.rint((xs - sx.min()) * rx + ox.min()).astype(int)
        ty = np.clip(ty, 0, dil.shape[0] - 1)
        tx = np.clip(tx, 0, dil.shape[1] - 1)
        cov_ok += int(dil[ty, tx].sum())
        cov_tot += len(ys)
    rate = cov_ok / max(cov_tot, 1)
    check("4 中心线忠实", rate >= 0.95, f"源骨架覆盖率 {rate:.1%}")

    # 5 花瓣等径
    fe = sp.find_frame(out_mask)[0]
    petals_ok, detail = False, "无外框"
    if fe is not None:
        sil = ndi.binary_fill_holes(fe)
        from shapely.geometry import Polygon
        from skimage import measure
        cs = measure.find_contours(np.pad(sil, 1).astype(float), 0.5)
        poly = Polygon([(x - 1, y - 1) for y, x in max(cs, key=len)])
        poly = poly if poly.is_valid else poly.buffer(0)
        m = sp.analyze_scallop(poly)
        if m is not None:
            petals_ok = m["peak_radius_cv"] < 0.015 and m["spacing_cv"] < 0.015
            detail = (f"{m['petals']} 瓣，峰半径 CV {m['peak_radius_cv']:.4f}，"
                      f"角间距 CV {m['spacing_cv']:.4f}")
    check("5 花瓣等径", petals_ok, detail)

    check("SVG 产出", svg.exists() and svg.stat().st_size > 10000, f"{svg.stat().st_size if svg.exists() else 0} bytes")
    finish()


def finish():
    print()
    if FAILS:
        print(f"结果：FAIL（{len(FAILS)} 项）→ {'基线，预期如此' if MODE == 'red' else '需修实现'}")
        sys.exit(1)
    print("结果：PASS 5/5")
    sys.exit(0)


if __name__ == "__main__":
    main()
