#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量出模：一次跑一整个批次（10 / 20 / 40 套完全不同的模具），并行渲染。

    python src\\batch_molds.py --batch xmas40 --list inputs\\batch_xmas40.csv --jobs 8

清单（CSV，第一行表头，允许 # 注释行）：
    item,input,size,relief,mode
    snowman_A,inputs/snowman_A.png,85,1.8,raise
    star_B,inputs/star_B.png,70,2.0,sink

产出（配对一定在同一目录里，单号就是批次下的模型名）：
    print/jobs/<batch>/<item>/base.stl      底模 / 凹模
    print/jobs/<batch>/<item>/cutter.stl    边框
    out/<batch>/<item>/{report.json, preview.png, MANIFEST.md, model.html}
    out/<batch>/INDEX.md                    给人看的批次总表
    out/<batch>/batch.json                  机器读：参数 + 耗时 + 体检 + 文件路径
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", OPENBLAS_NUM_THREADS="1")


def read_list(path: Path) -> list[dict]:
    rows = []
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("items", [])
    else:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")]
        for r in csv.DictReader(lines):
            rows.append(r)
    out = []
    for r in rows:
        out.append({
            "item": (r.get("item") or Path(r["input"]).stem).strip(),
            "input": r["input"].strip(),
            "size": float(r.get("size") or 85),
            "relief": float(r.get("relief") or 1.8),
            "mode": (r.get("mode") or "raise").strip(),
        })
    return out


def run_one(spec: dict, batch: str, html: bool, preview: bool) -> dict:
    item = spec["item"]
    job = f"{batch}/{item}"
    out_dir = ROOT / "out" / batch / item
    base = ROOT / "print" / "jobs" / batch / item / "base.stl"
    cutter = ROOT / "print" / "jobs" / batch / item / "cutter.stl"

    cmd = [sys.executable, str(ROOT / "src" / "stamp_pipeline.py"),
           "--input", spec["input"], "--out", str(out_dir), "--job", job,
           "--size", str(spec["size"]), "--relief", str(spec["relief"]),
           "--relief-mode", spec["mode"], "--no-index"]
    if not preview:
        cmd.append("--no-preview")
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")
    secs = time.perf_counter() - t0
    rec = {**spec, "job": job, "rc": p.returncode, "render_s": round(secs, 1),
           "files": {}, "html": None, "err": None}

    if p.returncode != 0:
        rec["err"] = (p.stderr or p.stdout or "").strip()[-800:]
        return rec

    rep_p = out_dir / "report.json"
    rep = json.loads(rep_p.read_text(encoding="utf-8")) if rep_p.exists() else {}
    rec["report"] = {k: rep.get(k) for k in
                     ("relief_mode", "size_mm", "stamp_size_mm", "relief", "base_thickness",
                      "cavity_draft_deg", "engine", "scad_render_s", "watertight", "triangles")}
    for k, f in (("base", base), ("cutter", cutter)):
        if f.exists():
            rec["files"][k] = str(f)

    if html and base.exists():
        hp = out_dir / "model.html"
        vc = [sys.executable, str(ROOT / "src" / "viewer" / "make_viewer.py"),
              "--stl", str(base), "--report", str(rep_p), "--out", str(hp),
              "--title", f"{batch} · {item}"]
        if cutter.exists():
            vc += ["--cutter", str(cutter)]
        h = ROOT / "print" / "standard" / "handle_straight.stl"
        if h.exists():
            vc += ["--handle", str(h)]
        v = subprocess.run(vc, cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")
        if v.returncode == 0:
            rec["html"] = str(hp)
    return rec


def write_index(batch: str, recs: list[dict], wall: float, workers: int) -> None:
    batch_dir = ROOT / "out" / batch
    (batch_dir / "batch.json").write_text(
        json.dumps({"batch": batch, "items": recs, "wall_s": round(wall, 1),
                    "workers": workers}, ensure_ascii=False, indent=2), encoding="utf-8")

    L = [f"# 批次 {batch}", "",
         f"> 由 `src/batch_molds.py` 自动生成。{len(recs)} 套模具，并行 {workers} 路，"
         f"总墙钟 {wall/60:.1f} 分钟（平均每套 {wall/len(recs):.1f}s）。", "",
         "每套的底模与边框都在同一个单号目录下，配对关系看下表最后一列。", "",
         "| 单号 | 图案 | 成品 mm | 凸/凹 | 底模 | 边框 | 面数 | 水密 | 耗时 s |",
         "|---|---|---|---|---|---|---|---|---|"]
    ok = 0
    for r in sorted(recs, key=lambda x: x["item"]):
        if r.get("rc") != 0:
            L.append(f"| `{r['item']}` | {Path(r['input']).name} | {r['size']:g} | {r['mode']} | "
                     f"_失败_ | | | | {r['render_s']} |")
            continue
        ok += 1
        rep = r.get("report", {})
        base = r["files"].get("base", "")
        cut = r["files"].get("cutter", "")
        L.append(f"| `{r['item']}` | {Path(r['input']).name} | {rep.get('size_mm', r['size']):g} | "
                 f"{'凹模' if r['mode']=='sink' else '凸模'} | "
                 f"`{Path(base).name if base else '缺'}` | `{Path(cut).name if cut else '缺'}` | "
                 f"{rep.get('triangles', '?')} | {'✓' if rep.get('watertight') else '×'} | {r['render_s']} |")
    L += ["", f"成功 {ok} / {len(recs)} 套。", "",
          "打印入口：`print/jobs/" + batch + "/<单号>/`，底模 + 边框成对；"
          "手柄不在这批里（`print/standard/handle_straight.stl`，单独打）。"]
    (batch_dir / "INDEX.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="批量出模（并行 + 配对目录）")
    ap.add_argument("--batch", required=True, help="批次名，如 xmas40（会成为 print/jobs/<批次>/）")
    ap.add_argument("--list", required=True, help="清单 CSV / JSON")
    ap.add_argument("--jobs", type=int, default=max(2, min(8, os.cpu_count() // 2)),
                    help="并行路数（默认 CPU 线程数的一半，最多 8）")
    ap.add_argument("--no-html", action="store_true", help="跳过每套的 model.html")
    ap.add_argument("--no-preview", action="store_true", help="跳过多栏预览图（更快）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 套（试跑用）")
    args = ap.parse_args(argv)

    specs = read_list(Path(args.list))
    if args.limit:
        specs = specs[:args.limit]
    if not specs:
        print("[x] 清单是空的")
        return 2

    print(f"=== 批次 {args.batch}：{len(specs)} 套，并行 {args.jobs} 路 ===")
    t0 = time.perf_counter()
    recs = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(run_one, s, args.batch, not args.no_html, not args.no_preview): s
                for s in specs}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            recs.append(rec)
            done += 1
            flag = "✓" if rec.get("rc") == 0 else "×"
            print(f"  [{done}/{len(specs)}] {flag} {rec['item']:<18} {rec['render_s']:>6.1f}s"
                  + ("" if rec.get("rc") == 0 else f"  {rec['err'][-200:] if rec['err'] else ''}"))
    wall = time.perf_counter() - t0

    write_index(args.batch, recs, wall, args.jobs)
    ok = sum(1 for r in recs if r.get("rc") == 0)
    print(f"\n完成 {ok}/{len(specs)} · 总墙钟 {wall:.1f}s（平均 {wall/len(recs):.1f}s/套）")
    print(f"  批次表  {ROOT / 'out' / args.batch / 'INDEX.md'}")
    print(f"  打印件  {ROOT / 'print' / 'jobs' / args.batch / '<单号>' / '{{base,cutter}}.stl'}")

    try:
        from make_print_index import rebuild
        rebuild()
    except Exception as exc:            # noqa: BLE001
        print(f"  [i] PRINT.md 未刷新：{exc}")
    return 0 if ok == len(specs) else 1


if __name__ == "__main__":
    sys.exit(main())
