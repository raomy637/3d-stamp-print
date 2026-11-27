"""monoline 中心线归一：原图笔画 → 均匀细线，几何中心线不变（代码路线，不用生图模型）。

与 `stamp_pipeline.cap_stroke_width` 的区别（后者量产禁用、测试 RED）：
- 不做 `dilation(skeleton) & region`：交集会在原笔画窄处削掉重建线、在接头留粗块，线宽不均匀；
- 先剪毛刺（短于 min_len 的骨架端枝）再定半径重建，全图线宽 = 2r+1 px；
- 外框环不参与归一（只取剪影，保留原线宽或单独加粗）。

用法：
  python src/tools/monoline_normalize.py --input 原图.png --out 细线.png --size 101.6 --target-mm 0.9
输出保留灰度抗锯齿（高斯 sigma 0.7），避免纯二值图让管线 Otsu 阈值退化为 0。
"""
import argparse

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import filters, morphology


def prune_spurs(sk: np.ndarray, min_len: int = 4) -> np.ndarray:
    """删除短于 min_len 的端枝（毛刺），保留长枝与分叉点。"""
    sk = sk.copy()
    cnt = ndi.convolve(sk.astype(np.uint8), np.ones((3, 3)), mode="constant") - sk
    ends = np.argwhere(sk & (cnt == 1))
    for y, x in ends:
        if not sk[y, x]:
            continue
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
            if cnt[cur[0], cur[1]] >= 3:
                break
        if len(path) < min_len:
            for yy, xx in path:
                sk[yy, xx] = False
    return sk


def normalize_pattern(pat: np.ndarray, r: int) -> np.ndarray:
    """每个连通块：骨架 → 剪毛刺 → disk(r) 重建。不交集、不并块。"""
    lab, n = ndi.label(pat, structure=np.ones((3, 3)))
    out = np.zeros_like(pat)
    disk = morphology.disk(r)
    for i in range(1, n + 1):
        reg = lab == i
        if reg.sum() < 4:
            out |= reg
            continue
        sk = prune_spurs(morphology.skeletonize(reg))
        out |= morphology.dilation(sk, disk)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=float, default=101.6, help="成品尺寸 mm（估 mm/px 用）")
    ap.add_argument("--margin", type=float, default=1.2)
    ap.add_argument("--target-mm", type=float, default=0.9)
    ap.add_argument("--thr", type=float, default=None)
    args = ap.parse_args()

    g = np.asarray(Image.open(args.input).convert("L"))
    thr = args.thr if args.thr is not None else float(filters.threshold_otsu(g))
    mask = g < thr
    if mask.mean() > 0.55:
        mask = ~mask

    # 外框环（铺满 + 闭合环）保留原样，只归一内部图案
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    h, w = mask.shape
    frame = None
    best = 0.0
    for i in range(1, n + 1):
        reg = lab == i
        area = float(reg.sum())
        if area < 0.02 * h * w:
            continue
        ys, xs = np.where(reg)
        wr, hr = (xs.max() - xs.min() + 1) / w, (ys.max() - ys.min() + 1) / h
        fr = ndi.binary_fill_holes(reg).sum() / area
        if wr > 0.80 and hr > 0.80 and fr > 2.0 and area > best:
            best, frame = area, reg
    pat = mask.copy()
    if frame is not None:
        pat[frame] = False
        ys, xs = np.where(frame)
        span = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
    else:
        ys, xs = np.where(mask)
        span = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
    mmpp = (args.size - 2 * args.margin) / span
    r = max(1, int(round((args.target_mm / mmpp - 1) / 2)))
    out = normalize_pattern(pat, r)
    if frame is not None:
        out |= frame
    print(f"mm/px={mmpp:.5f} r={r}px -> 线宽 {(2 * r + 1) * mmpp:.2f}mm, 外框={'保留' if frame is not None else '无'}")

    img = ndi.gaussian_filter((~out).astype(float) * 255.0, sigma=0.7)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(args.out)
    print("saved", args.out)


if __name__ == "__main__":
    main()