#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把手柄联排 STL 画成俯视图，方便一眼确认排布和间距（不需要开切片器）。

    python src/tools/preview_handle_batch.py                    # 默认 print/standard/handle_x6.stl -> out/handles/
    python src/tools/preview_handle_batch.py print/standard/handle_x12.stl
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.collections import PolyCollection

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def main():
    root = Path(__file__).resolve().parent.parent.parent
    stl = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "print" / "standard" / "handle_x6.stl"
    if not stl.is_absolute():
        stl = root / stl
    out_dir = root / "out" / "handles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (stl.stem + "_preview.png")

    mesh = trimesh.load(stl)
    tri = mesh.vertices[mesh.faces][:, :, :2]          # 只看 XY 投影
    b = mesh.bounds

    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=160)
    fig.patch.set_facecolor("#181b21")
    ax.set_facecolor("#181b21")
    ax.add_collection(PolyCollection(tri, facecolors="#cfd6e2",
                                     edgecolors="#3a4150", linewidths=0.12))
    ax.set_xlim(b[0][0] - 6, b[1][0] + 6)
    ax.set_ylim(b[0][1] - 6, b[1][1] + 6)
    ax.set_aspect("equal")
    ax.set_title(f"{stl.name}   {b[1][0]-b[0][0]:.0f} × {b[1][1]-b[0][1]:.0f} mm   "
                 f"（P1S 可用 256 × 256）", color="#d8dee9", fontsize=11)
    ax.tick_params(colors="#7c8798", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#333a45")
    fig.tight_layout()
    fig.savefig(out, facecolor=fig.get_facecolor())
    print(f"预览: {out}")


if __name__ == "__main__":
    main()
