#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""手柄层高对比件：一次生成"一排 3 个"的手柄，并附一份对比记录表。

同一模型、同一 G-code 之外，唯一变量是层高；所以模型只需要一个 STL，
三种层高分三次打（从左到右编号 1/2/3，靠位置区分，省掉雕刻编号）。

    python src/tools/handle_layer_test.py                 # 默认 3 个一排 -> print/test/handle_layer/
    python src/tools/handle_layer_test.py --count 4 --gap 10

打出记录写到 out/handles/layer_test.md（有旧记录就不覆盖，只追加提醒）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import make_handle as mh   # noqa: E402


TEMPLATE = """# 手柄层高对比

同一个 STL（`print/test/handle_layer/{stl}`）分三次打，唯一变量是层高。
位置从左到右 = 1 / 2 / 3，靠位置认，不用雕刻编号。

| 位次 | 喷嘴 | 层高 | 外壁速度 | 打印用时 | 手感（1–5） | 备注 |
|---|---|---|---|---|---|---|
| 1（左） | 0.4 | 0.16 | 60 |  |  | 基线，之前那批就是这组 |
| 2（中） | 0.4 | 0.12 | 40 |  |  | 推荐：外壁线宽 0.42 + 输入整形 |
| 3（右） | 0.2 | 0.08 | 35 |  |  | 最细，时间约 2 倍以上 |

判读要点：横纹间距 ≈ 层高，量一下就知道是不是层高问题；圆顶和收颈（两处 45° 斜面）
本来就比侧面糙，那不是参数问题。想更快见效可以 240 → 800 → 1200 目湿磨。
不用雕刻编号：三个手柄在盘上从左到右排，切片器里只打整盘，三次换层高重切同一个 STL 即可。
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成手柄层高对比件")
    ap.add_argument("--count", type=int, default=3, help="一排几个（默认 3）")
    ap.add_argument("--gap", type=float, default=10.0, help="件间距 mm")
    ap.add_argument("--segments", type=int, default=96)
    ap.add_argument("--style", choices=["dome", "straight", "column"], default="straight",
                    help="手柄形状，默认定稿款 straight（柄 φ10 / 底盘 φ15）")
    ap.add_argument("--name", default="handle_layer", help="放在 print/test/<name>/")
    args = ap.parse_args(argv)

    out_dir = ROOT / "print" / "test" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / f"layer_{args.count}.stl"

    one = mh.revolve(mh.STYLES[args.style], segments=args.segments)
    mesh, grid = mh.layout_batch(one, args.count, gap=args.gap, cols=args.count)
    mesh.export(str(stl))

    size = mesh.bounds[1] - mesh.bounds[0]
    print(f"对比件 STL : {stl}")
    print(f"  {args.count} 个一排 · {grid[0]}列x{grid[1]}行 · "
          f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm · "
          f"{len(mesh.faces):,} 面 · 水密 {mesh.is_watertight}")

    md = ROOT / "out" / "handles" / "layer_test.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    if md.exists():
        print(f"记录表已有，没覆盖：{md}")
    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        md.write_text(f"> 生成于 {now}\n\n" + TEMPLATE.format(stl=stl.name), encoding="utf-8")
        print(f"记录表     : {md}")

    try:
        from make_print_index import rebuild
        rebuild()
    except Exception as exc:            # noqa: BLE001
        print(f"[i] PRINT.md 未刷新：{exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
