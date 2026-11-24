#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 print/ 目录，生成根目录 PRINT.md（"哪些文件可以直接拿去打印"的总表）。

用法：
    python src/make_print_index.py            # 重写 PRINT.md
    python src/make_print_index.py --check    # 只检查不写，退出码 1 表示有异常件

目录约定（由 src/stamp_pipeline.py / src/make_handle.py 保证）：
    print/standard/            标准件，定稿后可复用：handle_slim.stl / handle_x6.stl / handle_x12.stl
    print/jobs/<job>/base.stl      这一单的底模（凸模压图案 / 凹模刻图案）
    print/jobs/<job>/cutter.stl    这一单的边框
    print/test/<名字>/*.stl    试打、对比、报废实验件（不要求配对）

PRINT.md 是**自动生成**的，别手改：改完代码重跑本脚本即可。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parent.parent
PRINT_DIR = ROOT / "print"
OUT_DIR = ROOT / "out"

PART_CN = {"base": "底模", "cutter": "边框"}


def info_path(f: Path) -> str:
    try:
        return f.relative_to(ROOT).as_posix()
    except Exception:                      # noqa: BLE001
        return f.name


def probe(path: Path):
    """读 STL 拿尺寸 / 面数 / 水密。失败返回 None。"""
    try:
        m = trimesh.load(str(path), force="mesh")
        b = m.bounds
        return {
            "file": path,
            "rel": info_path(path),
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
    jobs, standard, tests, bad = {}, [], [], []
    if not PRINT_DIR.exists():
        return {"jobs": {}, "standard": [], "tests": [], "bad": ["print/ 目录不存在"]}

    # ---- 标准件
    for f in sorted((PRINT_DIR / "standard").glob("*.stl"), key=lambda p: p.stat().st_mtime):
        info = probe(f)
        if info is None:
            bad.append(f"{info_path(f)}（读取失败）")
            continue
        standard.append(info)

    # ---- 订单：一单一个子目录，base/cutter 各一件
    jobs_dir = PRINT_DIR / "jobs"
    if jobs_dir.exists():
        for d in sorted([p for p in jobs_dir.glob("*") if p.is_dir()],
                        key=lambda p: p.stat().st_mtime, reverse=True):
            job = d.name
            for part in ("base", "cutter"):
                f = d / f"{part}.stl"
                if not f.exists():
                    continue
                info = probe(f)
                if info is None:
                    bad.append(f"{info_path(f)}（读取失败）")
                    continue
                jobs.setdefault(job, {})[part] = info
            for f in [p for p in d.glob("*.stl") if p.stem not in ("base", "cutter")]:
                info = probe(f)
                if info is None:
                    bad.append(f"{info_path(f)}（读取失败）")
                else:
                    jobs.setdefault(job, {})[f.stem] = info

    # ---- 测试件：可放子目录，不要求配对
    test_dir = PRINT_DIR / "test"
    if test_dir.exists():
        for f in sorted(test_dir.rglob("*.stl"), key=lambda p: p.stat().st_mtime, reverse=True):
            info = probe(f)
            if info is None:
                bad.append(f"{info_path(f)}（读取失败）")
                continue
            info["group"] = f.parent.name if f.parent != test_dir else ""
            tests.append(info)

    # ---- 体检
    for job, parts in jobs.items():
        for part, info in parts.items():
            if not info["watertight"]:
                bad.append(f"{info['rel']}（非水密，切片前先修复）")
        if "base" in parts and "cutter" not in parts:
            bad.append(f"jobs/{job}（只有底模、没有边框：是不是用了 --no-cutter？）")
    for info in standard + tests:
        if not info["watertight"]:
            bad.append(f"{info['rel']}（非水密）")
    return {"jobs": jobs, "standard": standard, "tests": tests, "bad": bad}


def render(data) -> str:
    jobs, standard, tests, bad = data["jobs"], data["standard"], data["tests"], data["bad"]
    L = ["# 打印清单", "",
         "> 由 `src/make_print_index.py` 自动生成，**别手改**；重跑脚本或重新出件后会自动刷新。",
         f"> 最近更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
         "**先看这一句**：能直接丢进切片器的文件全在 `print/` 下，分三个抽屉——"
         "`standard/` 是定稿可复用的标准件，`jobs/` 是这一单要打的模具，`test/` 是试打对比件。"
         "其余目录（`out/`）都是给人看的。", ""]

    if bad:
        L += ["## 需要处理", ""] + [f"- {b}" for b in bad] + [""]

    L += ["## 订单模具（`print/jobs/`，一单一个目录）", ""]
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
            L += [f"### `{job}` {sub}", "",
                  "| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |", "|---|---|---|---|---|---|"]
            for part in ("base", "cutter"):
                d = jobs[job].get(part)
                if not d:
                    continue
                L.append(f"| {PART_CN[part]} | `{d['rel']}` | "
                         f"{d['size'][0]} × {d['size'][1]} × {d['size'][2]} | "
                         f"{d['faces']:,} | {'✓' if d['watertight'] else '×'} | {d['volume_cm3']} |")
            L.append("")
        L.append("打印要点：底模平板贴床、图案（或凹槽）朝上，0.2 喷嘴 0.10 层高 / 4 墙 / 顶面熨烫 / 无支撑；"
                 "边框翼缘贴床、刃口朝上，4 墙 + 4mm brim，打完翻过来用。详见 `guides/printing.md`。")
    else:
        L.append("_还没有出过模具。跑 `python src/stamp_pipeline.py --input 图 --out out/<job>`。_")
    L.append("")

    L += ["## 标准件（`print/standard/`，定稿复用，换图不用重打）", ""]
    if standard:
        L += ["| 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |", "|---|---|---|---|---|"]
        for h in standard:
            L.append(f"| `{h['rel']}` | {h['size'][0]} × {h['size'][1]} × {h['size'][2]} | "
                     f"{h['faces']:,} | {'✓' if h['watertight'] else '×'} | {h['volume_cm3']} |")
        L += ["", "打印要点：底盘贴床直立、无支撑。层高按外观给：0.4 喷嘴 0.12、要手感换 0.2 喷嘴 0.08–0.10。"
                 "粘接面 φ14，502 涂一薄圈就够。"]
    else:
        L.append("_还没有标准件。跑 `python src/make_handle.py --count 12 --cols 6`。_")
    L.append("")

    L += ["## 测试件（`print/test/`，试打与对比，随时可删）", ""]
    if tests:
        L += ["| 文件 | 用途 | 外形 mm | 面数 | 水密 |", "|---|---|---|---|---|"]
        for t in tests:
            L.append(f"| `{t['rel']}` | {t.get('group') or '试打'} | "
                     f"{t['size'][0]} × {t['size'][1]} × {t['size'][2]} | {t['faces']:,} | "
                     f"{'✓' if t['watertight'] else '×'} |")
    else:
        L.append("_目前没有测试件。_")
    L.append("")

    L += ["## 非打印产物（都是给人看的）", "",
          "| 位置 | 内容 |", "|---|---|",
          "| `out/<job>/MANIFEST.md` | 这一单出了什么、每件能不能打（自动生成） |",
          "| `out/<job>/report.json` | 几何体检：尺寸 / 面数 / 水密 / 线宽 / 边框参数 |",
          "| `out/<job>/preview.png` | 三栏预览（实物 / 压印效果 / 剖面带尺寸） |",
          "| `out/<job>/model.html` | 单文件 3D 预览，双击即开 |",
          "| `out/handles/` | 手柄体检 json + 联排俯视图 |",
          "| `out/_archive/` | 淘汰件留档，别拿去打 |", ""]
    return "\n".join(L) + "\n"


def rebuild(write=True) -> int:
    data = collect()
    md = render(data)
    if write:
        (ROOT / "PRINT.md").write_text(md, encoding="utf-8")
        print(f"PRINT.md 已更新：{len(data['jobs'])} 单 / {len(data['standard'])} 个标准件 / "
              f"{len(data['tests'])} 个测试件"
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
        print(f"[i] {len(data['jobs'])} 单 / {len(data['standard'])} 个标准件 / "
              f"{len(data['tests'])} 个测试件；"
              + ("全部可打印" if not data["bad"] else f"{len(data['bad'])} 条待处理"))
        return 1 if data["bad"] else 0
    return rebuild(write=True)


if __name__ == "__main__":
    sys.exit(main())
