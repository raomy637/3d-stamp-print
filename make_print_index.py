#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 print/ 目录，生成根目录 PRINT.md（"哪些文件可以直接拿去打印"的总表）。

用法：
    python make_print_index.py            # 重写 PRINT.md
    python make_print_index.py --check    # 只检查不写，退出码 1 表示有异常件

打印件命名约定（由 stamp_pipeline.py / make_handle.py 保证）：
    print/<job>_base.stl      底模（带浮雕，压图案）
    print/<job>_cutter.stl    边框（独立切模，切粘土外形）
    print/handle_slim.stl     手柄单个
    print/handle_x6.stl       手柄 6 联排
    print/handle_x12.stl      手柄 12 联排（一盘）

本文件是**自动生成**的，别手改：改完代码重跑本脚本即可。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parent
PRINT_DIR = ROOT / "print"
OUT_DIR = ROOT / "out"

PART_CN = {"base": "底模", "cutter": "边框"}


def probe(path: Path):
    """读 STL 拿尺寸 / 面数 / 水密。失败返回 None。"""
    try:
        m = trimesh.load(str(path), force="mesh")
        b = m.bounds
        return {
            "size": [round(float(b[1][i] - b[0][i]), 1) for i in range(3)],
            "faces": int(len(m.faces)),
            "watertight": bool(m.is_watertight),
            "volume_cm3": round(float(m.volume) / 1000.0, 2),
        }
    except Exception:
        return None


def job_report(job: str) -> dict:
    p = OUT_DIR / job / "report.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def collect():
    jobs, handles, bad = {}, [], []
    if not PRINT_DIR.exists():
        return {"jobs": {}, "handles": [], "bad": ["print/ 目录不存在"]}

    for f in sorted(PRINT_DIR.glob("*.stl"), key=lambda p: p.stat().st_mtime, reverse=True):
        info = probe(f)
        if info is None:
            bad.append(f"{f.name}（读取失败）")
            continue
        name = f.stem
        if name.startswith("handle_"):
            handles.append({"file": f, **info})
            continue
        if name.endswith("_base") or name.endswith("_cutter"):
            job = name.rsplit("_", 1)[0]
            part = name.rsplit("_", 1)[1]
            jobs.setdefault(job, {})[part] = {"file": f, **info}
            continue
        bad.append(f"{f.name}（命名不符合 <job>_base / <job>_cutter / handle_*）")

    # 水密异常也算"要人看一眼"
    for job, parts in jobs.items():
        for part, d in parts.items():
            if not d["watertight"]:
                bad.append(f"{d['file'].name}（非水密，切片前先修复）")
    for h in handles:
        if not h["watertight"]:
            bad.append(f"{h['file'].name}（非水密）")

    # 只有 base 没有 cutter 的 job 提示一下
    for job, parts in jobs.items():
        if "base" in parts and "cutter" not in parts:
            bad.append(f"{job}（只有底模、没有边框：是不是用了 --no-cutter？）")
    return {"jobs": jobs, "handles": handles, "bad": bad}


def render(data) -> str:
    jobs, handles, bad = data["jobs"], data["handles"], data["bad"]
    L = []
    L.append("# 打印清单")
    L.append("")
    L.append("> 由 `make_print_index.py` 自动生成，**别手改**；重跑脚本或重新出件后会自动刷新。")
    L.append(f"> 最近更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append("**只看这一句也够**：能直接丢进切片器的文件全在 `print/` 里，一个 `.stl` 都不用挑；"
             "其余都是给人看的（预览图、报告、SVG）。")
    L.append("")

    if bad:
        L.append("## ⚠️ 需要处理")
        L.append("")
        for b in bad:
            L.append(f"- {b}")
        L.append("")

    L.append("## 底模 + 边框（凸模/凹模，每个图案一套，换图要重做）")
    L.append("")
    if jobs:
        for job in sorted(jobs, key=lambda j: max(
                (d["file"].stat().st_mtime for d in jobs[j].values()), default=0), reverse=True):
            rep = job_report(job)
            sub = ""
            if rep:
                if rep.get("relief_mode") == "sink":
                    sub = (f"（凹模 · 成品 {rep.get('size_mm', '?')}mm · 槽深 {rep.get('relief', '?')}mm "
                           f"外张 {rep.get('cavity_draft_deg', '?')}° · 底板 {rep.get('base_thickness', '?')}mm）")
                else:
                    sub = (f"（凸模 · 成品 {rep.get('size_mm', '?')}mm · 浮雕 {rep.get('relief', '?')}mm · "
                           f"底板 {rep.get('base_thickness', '?')}mm）")
            L.append(f"### `{job}` {sub}")
            L.append("")
            L.append("| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |")
            L.append("|---|---|---|---|---|---|")
            for part in ("base", "cutter"):
                d = jobs[job].get(part)
                if not d:
                    continue
                L.append(f"| {PART_CN[part]} | `print/{d['file'].name}` | "
                         f"{d['size'][0]} × {d['size'][1]} × {d['size'][2]} | "
                         f"{d['faces']:,} | {'✓' if d['watertight'] else '×'} | {d['volume_cm3']} |")
            L.append("")
        L.append("打印要点：底模**平板贴床、图案朝上**，0.2 喷嘴 0.10 层高 / 4 墙 / 顶面熨烫 / 无支撑；"
                 "边框**翼缘贴床、刃口朝上**，4 墙 + 4mm brim，打完翻过来用。详见 `guides/printing.md`。")
    else:
        L.append("_还没有出过底模/边框。_")
    L.append("")

    L.append("## 手柄（标准件，一套配所有图案，换图不用重打）")
    L.append("")
    if handles:
        L.append("| 文件 | 说明 | 外形 mm | 面数 | 水密 | 体积 cm³ |")
        L.append("|---|---|---|---|---|---|")
        label = {"handle_slim": "单个（试打/补件）", "handle_x6": "6 个一排（124×14）",
                 "handle_x12": "12 个一盘（124×36，一次打完）"}
        for h in handles:
            L.append(f"| `print/{h['file'].name}` | {label.get(h['file'].stem, '联排')} | "
                     f"{h['size'][0]} × {h['size'][1]} × {h['size'][2]} | "
                     f"{h['faces']:,} | {'✓' if h['watertight'] else '×'} | {h['volume_cm3']} |")
        L.append("")
        L.append("打印要点：底盘贴床直立、无支撑、0.16 层高 / 3 墙 / 15% 填充。"
                 "粘接面 φ14，502 涂一薄圈就够。")
    else:
        L.append("_还没有手柄。跑 `python make_handle.py --count 12 --cols 6`。_")
    L.append("")

    L.append("## 非打印产物在哪（都是给人看的）")
    L.append("")
    L.append("| 位置 | 内容 |")
    L.append("|---|---|")
    L.append("| `out/<图案>/MANIFEST.md` | 这一次出的所有文件 + 每个件能不能打印（自动生成） |")
    L.append("| `out/<图案>/report.json` | 几何体检：尺寸 / 面数 / 水密 / 线宽 / 边框参数 |")
    L.append("| `out/<图案>/preview.png` | 三栏预览（镜像实物 / 压印效果 / 半剖带尺寸） |")
    L.append("| `out/<图案>/model.html` | 单文件 3D 预览，双击即开（三件套装配/分离） |")
    L.append("| `out/<图案>/lines.svg` | 分层 SVG（底面 / 图案分开，可进 Inkscape 手改） |")
    L.append("| `out/handles/` | 手柄体检 json + 联排俯视图 |")
    L.append("| `out/_archive/` | 被淘汰的旧件（v2 那批），只是留档，别拿去打 |")
    L.append("")
    return "\n".join(L) + "\n"


def rebuild(write=True) -> int:
    data = collect()
    md = render(data)
    if write:
        (ROOT / "PRINT.md").write_text(md, encoding="utf-8")
        print(f"PRINT.md 已更新：{len(data['jobs'])} 套模具 / {len(data['handles'])} 个手柄件"
              + (f"，{len(data['bad'])} 条待处理" if data["bad"] else ""))
    return 1 if data["bad"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 PRINT.md 打印总表")
    ap.add_argument("--check", action="store_true", help="只检查，不写文件；有异常时退出码 1")
    args = ap.parse_args(argv)
    if args.check:
        data = collect()
        for b in data["bad"]:
            print(f"[x] {b}")
        print(f"[i] {len(data['jobs'])} 套模具 / {len(data['handles'])} 个手柄件；"
              + ("全部可打印" if not data["bad"] else f"{len(data['bad'])} 条待处理"))
        return 1 if data["bad"] else 0
    return rebuild(write=True)


if __name__ == "__main__":
    sys.exit(main())
