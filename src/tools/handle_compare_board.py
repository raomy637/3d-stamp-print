#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一板三款：把 dome / straight / column 各一个排成一排，一次打印对比手感。

    python src/tools/handle_compare_board.py

产出 print/test/handle_shape/compare_3.stl（试打件，随时可删）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh


def main():
    root = Path(__file__).resolve().parent.parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=8.0, help="件间距 mm")
    ap.add_argument("--out", default=str(root / "print" / "test" / "handle_shape" / "compare_3.stl"))
    args = ap.parse_args()

    src = [
        root / "print" / "standard" / "handle_slim.stl",       # dome
        root / "out" / "_ref" / "handle_straight.stl",         # straight（对照件，不占标准件位）
        root / "print" / "standard" / "handle_column.stl",     # column
    ]
    missing = [str(p) for p in src if not p.exists()]
    if missing:
        raise SystemExit("缺少源件（先跑 make_handle.py --style ...）：\n  " + "\n  ".join(missing))

    parts = []
    d_max = 0.0
    for p in src:
        m = trimesh.load(str(p), force="mesh")
        b = m.bounds
        d = max(b[1][0] - b[0][0], b[1][1] - b[0][1])
        d_max = max(d_max, d)
        m.apply_translation([-b[0][0] - d / 2.0, -b[0][1] - d / 2.0, -b[0][2]])
        parts.append(m)

    pitch = d_max + args.gap
    placed = []
    for i, m in enumerate(parts):
        c = m.copy()
        c.apply_translation([(i - (len(parts) - 1) / 2.0) * pitch, 0.0, 0.0])
        placed.append(c)

    board = trimesh.util.concatenate(placed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    board.export(str(out))
    b = board.bounds
    size = b[1] - b[0]
    print(f"对比板 : {out}")
    print(f"  排版 {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm，{len(board.faces)} 面，"
          f"水密 {board.is_watertight}，{board.volume/1000:.2f} cm³")
    print("  顺序：dome(φ14 圆顶) | straight(φ11.8 直筒) | column(φ14 直筒)")


if __name__ == "__main__":
    main()
