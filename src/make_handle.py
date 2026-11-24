#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""手柄：一次性定尺寸，批量打印的独立件。

为什么独立：
    章体是每张图都要重做的，手柄是「一套配所有」的标准件。
    所以它不跟 stamp_pipeline.py 一起出，这里单独出，一次打一批。

用法：
    python make_handle.py                                  # 只要 1 个 -> handles/handle_slim.stl
    python make_handle.py --count 6                        # 6 联排版 -> handles/handle_slim_x6.stl
    python make_handle.py --count 12 --gap 6 --out handles/x12.stl

打印：竖着打（底盘贴床），不用支撑；0.4 喷嘴 0.16 层高、4 墙、20% 填充即可。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import trimesh

try:                       # 同目录模块（脚本直接运行时可用）
    import scad_engine
except ImportError:        # 作为包导入时
    from . import scad_engine

# --------------------------------------------------------------------------- #
# 尺寸（改这里就等于换一款手柄；改完重跑本脚本，章体不用动）
# --------------------------------------------------------------------------- #
# 小把手：底盘 φ14 x 1.4 粘接面 -> 收颈 -> φ9.8~11 腰形握柄 -> 圆顶，总高 25
HANDLE_PROFILE = [
    (0.0, 0.0),      # 底面中心
    (7.0, 0.0),      # 底盘外缘 φ14
    (7.0, 1.4),      # 底盘厚度（粘接面 154mm²）
    (5.4, 2.6),      # 收颈
    (5.0, 5.0),
    (4.9, 10.5),     # 握柄，轻微腰形（拇指食指捏）
    (5.2, 15.0),
    (5.5, 19.0),     # 指腹压的那一段略鼓
    (4.6, 21.8),     # 圆顶过渡
    (2.8, 23.9),
    (0.0, 25.0),
]
HANDLE_HEIGHT = HANDLE_PROFILE[-1][1]
HANDLE_FLANGE_D = 14.0

# 直筒版：去掉圆顶与收颈，斜面占比从 62% 降到 <10%，
# 表面横纹主要来自斜面（FDM 垂直面最光），所以这版打出来更干净。
HANDLE_STRAIGHT = [
    (0.0, 0.0),
    (7.0, 0.0),
    (7.0, 1.4),
    (6.2, 2.2),
    (5.9, 3.2),
    (5.9, 22.4),     # 直筒 φ11.8
    (5.4, 23.6),     # 顶 R3 圆角
    (4.0, 24.6),
    (2.4, 25.0),
    (0.0, 25.0),
]
STYLES = {"dome": HANDLE_PROFILE, "straight": HANDLE_STRAIGHT}


def revolve(profile, segments=96):
    """把 (r, z) 折线绕 Z 轴旋转成水密实体。r==0 处收成极点。"""
    verts, rings = [], []
    for r, z in profile:
        if r <= 1e-9:
            rings.append(("pole", len(verts)))
            verts.append([0.0, 0.0, z])
        else:
            start = len(verts)
            for i in range(segments):
                a = 2.0 * math.pi * i / segments
                verts.append([r * math.cos(a), r * math.sin(a), z])
            rings.append(("ring", start))

    faces = []
    for k in range(len(rings) - 1):
        t_a, i_a = rings[k]
        t_b, i_b = rings[k + 1]
        if t_a == "ring" and t_b == "ring":
            for i in range(segments):
                i2 = (i + 1) % segments
                faces.append([i_a + i, i_a + i2, i_b + i2])
                faces.append([i_a + i, i_b + i2, i_b + i])
        elif t_a == "ring" and t_b == "pole":
            for i in range(segments):
                faces.append([i_a + i, i_a + (i + 1) % segments, i_b])
        elif t_a == "pole" and t_b == "ring":
            for i in range(segments):
                faces.append([i_a, i_b + (i + 1) % segments, i_b + i])

    m = trimesh.Trimesh(vertices=np.array(verts, dtype=float),
                        faces=np.array(faces, dtype=int), process=True)
    m.merge_vertices()
    m.fix_normals()
    return m


def make_handle(segments=96):
    return revolve(HANDLE_PROFILE, segments=segments)


def make_handle_scad(profile, segments, tmpdir: Path):
    """用 OpenSCAD 的 rotate_extrude 旋转剖面出件（改 profile 一行就换形状）。"""
    tmpdir.mkdir(parents=True, exist_ok=True)
    job = scad_engine.write_job_scad({}, scad_engine.SCAD_DIR / "handle.scad",
                                     tmpdir / "handle_job.scad")
    stl = tmpdir / "handle_body.stl"
    ok, secs, tail = scad_engine.render(
        job, stl, defs=dict(profile=[[float(r), float(z)] for r, z in profile],
                            seg=int(segments)))
    if not ok:
        raise RuntimeError(f"OpenSCAD 渲染失败：{tail}")
    m = trimesh.load(str(stl))
    m.merge_vertices()
    m.fix_normals()
    return m, secs


def layout_batch(one, count, gap=8.0, cols=None):
    """按网格在打印床上摆 count 个，返回合并后的单一网格（可直接切片）。"""
    if count <= 1:
        return one.copy(), (1, 1)

    d = float(one.bounds[1][0] - one.bounds[0][0])
    pitch = d + gap
    if cols is None:
        cols = max(1, int((250.0 + gap) // pitch))   # P1S 可用 250 左右
    cols = min(cols, count)
    rows = int(math.ceil(count / cols))

    parts = []
    for k in range(count):
        r, c = divmod(k, cols)
        offset = np.array([(c - (cols - 1) / 2.0) * pitch,
                           ((rows - 1) / 2.0 - r) * pitch,
                           0.0])
        m = one.copy()
        m.apply_translation(offset)
        parts.append(m)
    return trimesh.util.concatenate(parts), (cols, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None,
                    help="输出 STL；默认 print/standard/handle_slim.stl（或 handle_x<N>.stl）")
    ap.add_argument("--count", type=int, default=1, help="排几个（一批打印）")
    ap.add_argument("--gap", type=float, default=8.0, help="件间距 mm")
    ap.add_argument("--cols", type=int, default=None, help="每行几个，默认按床宽自动")
    ap.add_argument("--segments", type=int, default=96)
    ap.add_argument("--style", choices=["dome", "straight"], default="dome",
                    help="dome=现在的圆顶款（默认）；straight=直筒+顶 R3，表面更光")
    ap.add_argument("--engine", choices=["scad", "mesh"], default="scad",
                    help="scad=OpenSCAD rotate_extrude（改剖面只动一个数组）；mesh=旧 revolve()")
    ap.add_argument("--json", default=None, help="体检报告输出路径；默认 out/handles/")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    profile = STYLES[args.style]
    # 标准件统一进 print/standard/（定稿可复用）；体检 json 进 out/handles/（给人看的）
    default_name = ("handle_slim.stl" if args.style == "dome" else "handle_straight.stl") \
        if args.count <= 1 else (
            f"handle_x{args.count}.stl" if args.style == "dome"
            else f"handle_straight_x{args.count}.stl")
    out = Path(args.out) if args.out else (root / "print" / "standard" / default_name)
    out.parent.mkdir(parents=True, exist_ok=True)
    rep_dir = root / "out" / "handles"
    rep_dir.mkdir(parents=True, exist_ok=True)

    secs = None
    if args.engine == "scad":
        try:
            one, secs = make_handle_scad(profile, args.segments, rep_dir / "_scad")
            print(f"  [i] 引擎：OpenSCAD（渲染 {secs:.1f}s）")
        except Exception as exc:            # noqa: BLE001
            print(f"  [!] OpenSCAD 失败，回退 revolve：{exc}")
            one = revolve(profile, segments=args.segments)
    else:
        one = revolve(profile, segments=args.segments)
    mesh, grid = layout_batch(one, args.count, gap=args.gap, cols=args.cols)
    mesh.export(str(out))

    b = mesh.bounds
    size = b[1] - b[0]
    grip_d = 2.0 * max(r for r, z in profile if 2.6 <= z <= 19.0)
    info = {
        "file": str(out.relative_to(root)) if out.is_relative_to(root) else str(out),
        "engine": "scad" if secs else "mesh",
        "scad_render_s": round(secs, 1) if secs else None,
        "style": args.style,
        "count": args.count,
        "grid": list(grid),
        "gap_mm": args.gap,
        "height_mm": round(float(one.bounds[1][2] - one.bounds[0][2]), 2),
        "flange_d_mm": HANDLE_FLANGE_D,
        "grip_d_mm": round(float(grip_d), 1),
        "plate_size_mm": [round(float(size[0]), 2), round(float(size[1]), 2)],
        "triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "volume_cm3_one": round(float(one.volume) / 1000.0, 2),
    }
    print(f"手柄 STL   : {out}")
    print(f"  单个     : φ{HANDLE_FLANGE_D:.0f} x {info['height_mm']:.1f}mm，"
          f"{len(one.faces)} 面，水密 {one.is_watertight}，{info['volume_cm3_one']} cm3")
    print(f"  本批     : {args.count} 个，{grid[0]}列x{grid[1]}行，"
          f"排版尺寸 {info['plate_size_mm'][0]:.0f}x{info['plate_size_mm'][1]:.0f}mm，"
          f"{info['triangles']} 面，水密 {mesh.is_watertight}")

    jp = Path(args.json) if args.json else rep_dir / (out.stem + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  报告     : {jp}")

    try:
        from make_print_index import rebuild
        rebuild()
    except Exception as exc:            # noqa: BLE001
        print(f"  [i] PRINT.md 未刷新：{exc}")


if __name__ == "__main__":
    main()
