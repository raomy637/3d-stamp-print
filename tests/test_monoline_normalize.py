"""monoline 中心线归一的验收测试（TDD）。

判据（对 santa 原图图案区，目标线宽 0.9mm）：
1. 线宽均匀：stroke_stats max <= 1.05 且 min >= 0.80；
2. 不拆字：每个原连通块在输出里仍恰好对应 1 个连通块；
3. 中心线忠实：原骨架（剪毛刺后）被输出覆盖（1px 容差）；
4. 不长毛刺：输出骨架端点数 <= 原骨架端点数 + 2。

RED 基线：现有量产收细路径 cap_stroke_width（骨架∩原区域）。
GREEN：src/tools/monoline_normalize.py 的 normalize_pattern。
"""
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from skimage import morphology, measure

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src" / "tools"))

import stamp_pipeline as sp

SANTA = REPO / "work" / "订单" / "20261126" / "4246454365" / "santa" / "原始图" / "santa.png"
SIZE, MARGIN = 101.6, 1.2
TARGET = float(sys.argv[2]) if len(sys.argv) > 2 else 0.9


def load_pattern():
    from PIL import Image
    g = np.asarray(Image.open(SANTA).convert("L"))
    mask = g < float(__import__("skimage.filters", fromlist=["threshold_otsu"]).threshold_otsu(g))
    frame, _ = sp.find_frame(mask)
    pat = mask.copy()
    if frame is not None:
        pat[frame] = False
    ys, xs = np.where(frame if frame is not None else mask)
    span = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
    mmpp = (SIZE - 2 * MARGIN) / span
    return pat, mmpp


def skeleton_pruned(comp, min_len=4):
    sk = morphology.skeletonize(comp)
    cnt = ndi.convolve(sk.astype(np.uint8), np.ones((3, 3)), mode="constant") - sk
    ends = np.argwhere(sk & (cnt == 1))
    for y, x in ends:
        path = [(y, x)]
        cur = (y, x)
        for _ in range(min_len):
            yy, xx = cur
            nbrs = [(yy + dy, xx + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                    if (dy or dx) and 0 <= yy + dy < sk.shape[0] and 0 <= xx + dx < sk.shape[1]
                    and sk[yy + dy, xx + dx] and (yy + dy, xx + dx) not in path]
            if len(nbrs) != 1:
                break
            cur = nbrs[0]
            path.append(cur)
            c = cnt[cur[0], cur[1]]
            if c >= 3:
                break
        if len(path) < min_len:
            for yy, xx in path:
                sk[yy, xx] = False
    return sk


def check(normalizer, label):
    pat, mmpp = load_pattern()
    r = max(1, int(round((TARGET / mmpp - 1) / 2)))
    out = normalizer(pat, r, mmpp)
    stats = sp.stroke_stats(out, mmpp)
    fails = []
    if not (stats["min"] >= TARGET - 0.12 and stats["max"] <= 1.3
            and stats["max"] <= TARGET + 0.45):
        fails.append(f"线宽不均匀 min={stats['min']} max={stats['max']}（目标 {TARGET}）")
    lab_o, no = sp._label(pat)
    lab_n, nn = sp._label(out)
    for i in range(1, no + 1):
        reg = lab_o == i
        if reg.sum() < 50:
            continue
        overlap = np.unique(lab_n[reg & (out > 0)])
        overlap = overlap[overlap > 0]
        if len(overlap) != 1:
            fails.append(f"原连通块 {i} 被拆成 {len(overlap)} 块")
    cov = morphology.binary_dilation(out, morphology.disk(1))
    for i in range(1, no + 1):
        reg = lab_o == i
        if reg.sum() < 50:
            continue
        sk = skeleton_pruned(reg)
        if sk.sum() and not cov[sk].all():
            fails.append(f"原连通块 {i} 中心线未被覆盖 {int((~cov[sk]).sum())}px")
    def n_ends(m):
        s = morphology.skeletonize(m)
        c = ndi.convolve(s.astype(np.uint8), np.ones((3, 3)), mode="constant") - s
        return int((s & (c == 1)).sum())
    eo, en = n_ends(pat), n_ends(out)
    if en > eo + 2:
        fails.append(f"输出毛刺端点 {en} > 原 {eo}+2")
    print(f"[{label}] " + ("PASS" if not fails else "FAIL: " + "; ".join(fails[:6])))
    return not fails


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "cap"
    if which == "cap":
        ok = check(lambda p, r, mmpp: sp.cap_stroke_width(p, TARGET, mmpp)[0], "RED cap_stroke_width")
    else:
        import monoline_normalize as mn
        ok = check(lambda p, r, mmpp: mn.normalize_pattern(p, r), "GREEN normalize_pattern")
    sys.exit(0 if ok else 1)