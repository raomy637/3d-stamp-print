#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把底模的浮雕层投影成 2D 图，用来判断"线条断"是几何断还是打印断。

    python src\\tools\\shape_floor.py --stl print\\jobs\\bakers_v5\\base.stl --out out\\_ref\\floor_v5.png

浮雕（z > 底板上表面）的所有三角形投到 XY 平面填充成黑色，其余透明。
几何上若某处笔画断开，图上会直接看到断口；若图是连续的，那实物断开就是打印参数
（顶面熨烫 / 细线打不出）导致的，不是模型问题。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.collections import PolyCollection


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-t", type=float, default=3.0, help="底板厚度，浮雕从这一层往上")
    ap.add_argument("--dpi", type=int, default=600)
    args = ap.parse_args(argv)

    m = trimesh.load(args.stl, force="mesh")
    tri = np.asarray(m.triangles)
    keep = tri[:, :, 2].max(axis=1) > (args.base_t + 0.02)
    proj = tri[keep][:, :, :2]

    fig, ax = plt.subplots(figsize=(8, 8), dpi=args.dpi)
    ax.add_collection(PolyCollection(proj, facecolors="black", edgecolors="none"))
    b = m.bounds
    ax.set_xlim(b[0][0], b[1][0])
    ax.set_ylim(b[0][1], b[1][1])
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=args.dpi, transparent=True, bbox_inches="tight", pad_inches=0)
    print(f"写出 {args.out}（{len(proj)} 个三角形）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
