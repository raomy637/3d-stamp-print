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
import subprocess
import sys
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

# 直筒版（2026-11-24 用户定稿尺寸）：φ10 握柄 + φ15 底盘 + 顶 R3。
# 底盘到握柄是直角台阶（朝上环面，不算斜面），斜面只剩顶部那 3mm 圆角。
HANDLE_STRAIGHT = [
    (0.0, 0.0),
    (7.5, 0.0),      # 底盘 φ15
    (7.5, 1.5),      # 底盘厚 1.5，粘接面 π·7.5² = 176.7mm²
    (5.0, 1.5),      # 水平环台（朝上，可打，零斜面）
    (5.0, 22.0),     # φ10 直筒
    (4.60, 23.50),   # 顶 R3 圆角：圆心 (r2, z22)，30°
    (3.50, 24.60),   # 60°
    (2.00, 25.00),   # 90°，顶上留 φ4 平台
    (0.0, 25.00),
]
# 直筒升级版：口径直接给到底盘同径 φ14、取消收颈，只剩顶端 R3 圆角，
# 斜面只存在于顶部那 3mm 环带。握持感变成 "带倒角的柱子"，横纹最少。
HANDLE_COLUMN = [
    (0.0, 0.0),
    (7.0, 0.0),      # 底面 φ14，粘接面 154mm²
    (7.0, 22.0),     # φ14 直筒贯通到 z22
    (6.60, 23.50),   # 顶 R3 圆角：圆心 (r4, z22)，30°
    (5.50, 24.60),   # 60°
    (4.00, 25.00),   # 90°，顶上留 φ8 平台
    (0.0, 25.00),
]
# 小圆钮款（对照件，2026-11-25 用户按实物照片提的方案）：
# 底盘 φ16 × 1.2 粘接，整体矮圆顶收到 13 高，顶留 φ2 小平面。
HANDLE_KNOB = [
    (0.0, 0.0),
    (8.0, 0.0),      # 底盘 φ16
    (8.0, 1.2),      # 底盘厚 1.2，粘接面 π·8² = 201mm²
    (7.8, 2.6),
    (7.2, 4.6),      # 圆顶母线（近似 1/4 椭圆，收得比直筒快）
    (6.4, 6.8),
    (5.4, 8.8),
    (4.2, 10.5),
    (2.8, 11.9),
    (1.4, 12.8),
    (0.0, 13.0),     # 总高 13
]
STYLES = {"dome": HANDLE_PROFILE, "straight": HANDLE_STRAIGHT, "column": HANDLE_COLUMN,
          "knob": HANDLE_KNOB}
# 标准件命名（换图不重打，所以名字必须稳定）
NAMES = {
    "dome": ("handle_slim.stl", "handle_x{n}.stl"),
    "straight": ("handle_straight.stl", "handle_straight_x{n}.stl"),
    "column": ("handle_column.stl", "handle_column_x{n}.stl"),
    "knob": ("handle_knob.stl", "handle_knob_x{n}.stl"),
}


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


def grip_radius_at(profile, z=10.0):
    """剖面上 z 高度处的半径（线性插值）。剖面点可能很稀（直筒只有两个点），不能只按折点筛。"""
    for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
        if z0 <= z <= z1 and z1 > z0:
            t = (z - z0) / (z1 - z0)
            return r0 + t * (r1 - r0)
    return max(r for r, _ in profile)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None,
                    help="输出 STL；默认 print/standard/handle_slim.stl（或 handle_x<N>.stl）")
    ap.add_argument("--count", type=int, default=1, help="排几个（一批打印）")
    ap.add_argument("--gap", type=float, default=8.0, help="件间距 mm")
    ap.add_argument("--cols", type=int, default=None, help="每行几个，默认按床宽自动")
    ap.add_argument("--segments", type=int, default=96)
    ap.add_argument("--style", choices=["dome", "straight", "column", "knob"], default="dome",
                    help="dome=圆顶款（默认）；straight=φ11.8 直筒；column=φ14 直筒，斜面最少；"
                         "knob=小圆钮（底盘 φ16 / 高 13，对照件）")
    ap.add_argument("--engine", choices=["scad", "mesh"], default="scad",
                    help="scad=OpenSCAD rotate_extrude（改剖面只动一个数组）；mesh=旧 revolve()")
    ap.add_argument("--json", default=None, help="体检报告输出路径；默认 out/handles/")
    ap.add_argument("--no-viewer", action="store_true",
                    help="跳过 3D 预览 html（默认每件都出一份，规则要求）")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    profile = STYLES[args.style]
    # 标准件统一进 print/standard/（定稿可复用）；体检 json 进 out/handles/（给人看的）
    single_name, batch_name = NAMES[args.style]
    default_name = single_name if args.count <= 1 else batch_name.format(n=args.count)
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
    grip_d = 2.0 * grip_radius_at(profile, 10.0)
    info = {
        "file": str(out.relative_to(root)) if out.is_relative_to(root) else str(out),
        "engine": "scad" if secs else "mesh",
        "scad_render_s": round(secs, 1) if secs else None,
        "style": args.style,
        "count": args.count,
        "grid": list(grid),
        "gap_mm": args.gap,
        "height_mm": round(float(one.bounds[1][2] - one.bounds[0][2]), 2),
        "flange_d_mm": round(float(2.0 * max(r for r, _ in profile)), 1),
        "grip_d_mm": round(float(grip_d), 1),
        "plate_size_mm": [round(float(size[0]), 2), round(float(size[1]), 2)],
        "triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "volume_cm3_one": round(float(one.volume) / 1000.0, 2),
    }
    print(f"手柄 STL   : {out}")
    print(f"  单个     : 底盘 φ{info['flange_d_mm']:.1f} × 握柄 φ{info['grip_d_mm']:.1f} × "
          f"高 {info['height_mm']:.1f}mm，"
          f"{len(one.faces)} 面，水密 {one.is_watertight}，{info['volume_cm3_one']} cm3")
    print(f"  本批     : {args.count} 个，{grid[0]}列x{grid[1]}行，"
          f"排版尺寸 {info['plate_size_mm'][0]:.0f}x{info['plate_size_mm'][1]:.0f}mm，"
          f"{info['triangles']} 面，水密 {mesh.is_watertight}")

    jp = Path(args.json) if args.json else rep_dir / (out.stem + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  报告     : {jp}")

    if not args.no_viewer:
        html = rep_dir / (out.stem + ".html")
        cmd = [sys.executable, str(root / "src" / "viewer" / "make_viewer.py"),
               "--stl", str(out), "--out", str(html), "--kind", "handle",
               "--title", f"手柄 {args.style} · 底 φ{info['flange_d_mm']:.1f}"
                          f" × 柄 φ{info['grip_d_mm']:.1f} × 高 {info['height_mm']:.1f}mm"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        print(f"  预览     : {html}" if r.returncode == 0 else f"  [!] 预览失败：{r.stderr[-400:]}")

    try:
        from make_print_index import rebuild
        rebuild()
    except Exception as exc:            # noqa: BLE001
        print(f"  [i] PRINT.md 未刷新：{exc}")


if __name__ == "__main__":
    main()
