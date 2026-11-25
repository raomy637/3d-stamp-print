#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量底模与边框的实际间隙：沿 720 个角度比较底模外沿与边框内腔。

    python src\\tools\\check_fit.py --base print\\jobs\\bakers_v6\\base.stl --cutter print\\jobs\\bakers_v6\\cutter.stl --plot out\\_ref\\fit_v6.png

取点规则（这是精度关键，早先版本按全高度取 max/min 会混入图案顶点与翼缘顶点，误报 -1.6mm）：

- 底模：z ≈ 0 那一圈顶点就是底板外形轮廓，按角度取最大半径。
- 边框：z 取「垂直薄刃段」（height-edge_h+0.3 ~ height-0.2），该段内壁是垂直面，
  半径恒等于设计内腔；按角度取最小半径。

为什么需要这个数：设计值是 clearance/边，但 FDM 打完外壁会胀、内壁会缩（象脚 + 线宽），
0.4 实测会卡死，0.8 才有实际净间隙。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh


def profile(m, zmin, zmax, pick, bins):
    """z 落在 [zmin,zmax] 的顶点按角度分桶取 min/max 半径（原点固定 0,0）。"""
    v = np.asarray(m.vertices)
    sel = (v[:, 2] >= zmin) & (v[:, 2] <= zmax)
    pts = v[sel][:, :2]
    if len(pts) == 0:
        return None
    r = np.hypot(pts[:, 0], pts[:, 1])
    th = (np.degrees(np.arctan2(pts[:, 1], pts[:, 0])) + 360.0) % 360.0
    idx = np.clip((th / (360.0 / bins)).astype(int), 0, bins - 1)
    out = np.full(bins, np.nan)
    for b in range(bins):
        rb = r[idx == b]
        if len(rb):
            out[b] = rb.max() if pick == "max" else rb.min()
    return out


def fill_nan(a):
    n = len(a)
    ok = ~np.isnan(a)
    if ok.sum() < 6:
        return a
    x = np.arange(n)
    a = a.copy()
    a[~ok] = np.interp(x[~ok], x[ok], a[ok])
    return a


def best_shift(rb, rc):
    """扫一圈相位，找最小平均偏差 —— 差值若能被一个整体旋转吃掉，就是「错位」，不是「尺寸差」。"""
    best = (1e9, 0.0)
    step = 360.0 / len(rb)
    for k in range(-int(30 / step), int(30 / step) + 1):
        e = float(np.mean(np.abs(np.roll(rc, k) - rb)))
        if e < best[0]:
            best = (e, k * step)
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(description="量底模与边框的贴合间隙")
    ap.add_argument("--base", required=True, help="底模 / 凹模 STL")
    ap.add_argument("--cutter", required=True, help="边框 STL")
    ap.add_argument("--base-z", type=float, nargs=2, default=None,
                    help="底模取哪段高度（默认 0 ~ 0.06，即底板底面轮廓）")
    ap.add_argument("--cutter-z", type=float, nargs=2, default=None,
                    help="边框取哪段高度（默认垂直薄刃段，自动按刃口段高 3.0 推断）")
    ap.add_argument("--bins", type=int, default=720)
    ap.add_argument("--min-gap", type=float, default=0.6,
                    help="低于这个值就报警（默认 0.6：0.4 在 FDM 上实测卡死）")
    ap.add_argument("--plot", default=None, help="半径/间隙曲线图")
    args = ap.parse_args(argv)

    base = trimesh.load(args.base, force="mesh")
    cut = trimesh.load(args.cutter, force="mesh")
    h = float(cut.bounds[1][2])
    bz = args.base_z or [0.0, 0.06]
    cz = args.cutter_z or [max(h - 3.0, 0.0), h]

    rb = fill_nan(profile(base, bz[0], bz[1], "max", args.bins))
    rc = fill_nan(profile(cut, cz[0], cz[1], "min", args.bins))
    if rb is None or rc is None:
        print("[x] 取不到顶点（z 区间可能选错）")
        return 2
    gap = rc - rb
    ok = ~np.isnan(gap)
    g = gap[ok]

    mins, p05 = float(np.min(g)), float(np.percentile(g, 5))
    med, mx = float(np.median(g)), float(np.max(g))
    deg_min = int(np.nanargmin(gap))
    err, shift = best_shift(rb, rc)

    print(f"底模外沿 半径 {np.nanmin(rb):.2f}–{np.nanmax(rb):.2f}mm（z {bz[0]:.2f}–{bz[1]:.2f}）")
    print(f"边框内腔 半径 {np.nanmin(rc):.2f}–{np.nanmax(rc):.2f}mm（z {cz[0]:.2f}–{cz[1]:.2f}，高 {h:.1f}）")
    print(f"间隙 mm：min {mins:.2f} | p05 {p05:.2f} | 中位 {med:.2f} | max {mx:.2f}")
    print(f"最窄处在 {deg_min * 360.0 / args.bins:.1f}°（该处 {mins:.2f}mm）")
    print(f"相位扫描：最佳旋转 {shift:.1f}°，残差 {err:.2f}mm "
          f"（残差≈中位=形状吻合；残差明显小于中位=错位）")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        th = np.arange(args.bins) * (360.0 / args.bins)
        fig, ax = plt.subplots(2, 1, figsize=(11, 7), dpi=150)
        ax[0].plot(th, rb, label="base outline", lw=1.2)
        ax[0].plot(th, rc, label="cutter cavity", lw=1.2)
        ax[0].set_xlabel("angle deg")
        ax[0].set_ylabel("radius mm")
        ax[0].legend()
        ax[0].grid(alpha=0.3)
        ax[1].plot(th, gap, color="crimson", lw=1.2)
        ax[1].axhline(args.min_gap, color="green", ls="--", lw=1, label=f"target >= {args.min_gap}")
        ax[1].axhline(0, color="black", ls=":", lw=1)
        ax[1].set_xlabel("angle deg")
        ax[1].set_ylabel("gap mm (cavity - base)")
        ax[1].legend()
        ax[1].grid(alpha=0.3)
        fig.tight_layout()
        Path(args.plot).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.plot)
        print(f"曲线图 {args.plot}")

    n_bad = int(np.nansum(gap < args.min_gap))
    if mins < 0:
        print(f"[x] {n_bad} 个扇区负间隙：内腔比底模还小，物理上塞不进去")
    elif mins < args.min_gap:
        print(f"[!] {n_bad} 个扇区间隙 < {args.min_gap}mm，FDM 打完容易卡")
    else:
        print(f"[OK] 全部扇区 >= {args.min_gap}mm，打完能松配")
    return 0


if __name__ == "__main__":
    sys.exit(main())
