#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三款手柄并排剖面图（给选型用的）：dome / straight / column。

    python src/tools/preview_handle_styles.py

数据源就是 make_handle.py 里的三条剖面数组，斜面占比来自 STL 面法线实测统计。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_handle import STYLES  # noqa: E402

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 名称、面数、体积、斜面占比（2026-11-24 实测：面法线与面积加权）
ITEMS = [
    ("dome", "φ14 × 25", "对照款 · 1,728 面 · 2.03 cm³ · 斜面 61.6%"),
    ("straight", "柄 φ10 / 底 φ15 × 25", "★ 定稿 · 1,344 面 · 2.05 cm³ · 斜面 7.7%"),
    ("column", "φ14 × 25", "对照款 · 960 面 · 3.76 cm³ · 斜面 9.3%"),
]


def main():
    root = Path(__file__).resolve().parent.parent.parent
    out = root / "out" / "handles" / "handle_styles.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(11, 4.6), dpi=160)
    fig.patch.set_facecolor("#181b21")
    for ax, (key, dia, tag) in zip(axes, ITEMS):
        ax.set_facecolor("#181b21")
        prof = STYLES[key]
        r = [p[0] for p in prof]
        z = [p[1] for p in prof]
        ax.fill_betweenx(z, [-v for v in r], r, color="#2b3240", zorder=2)
        ax.plot(r, z, "-", color="#cfd6e2", lw=1.6, zorder=3)
        ax.plot([-v for v in r], z, "-", color="#cfd6e2", lw=1.6, zorder=3)
        ax.axhline(0, color="#3a4150", lw=0.8)
        ax.set_xlim(-11, 11)
        ax.set_ylim(-2, 29)
        ax.set_aspect("equal")
        ax.tick_params(colors="#7c8798", labelsize=8)
        for s in ax.spines.values():
            s.set_color("#333a45")
        ax.set_title(f"{key}  {dia}mm", color="#d8dee9", fontsize=11)
        ax.set_xlabel(tag, color="#98a2b3", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, facecolor=fig.get_facecolor())
    print(f"预览: {out}")


if __name__ == "__main__":
    main()
