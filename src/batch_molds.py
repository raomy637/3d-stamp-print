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


def build_task(spec: dict, batch: str, html: bool, preview: bool) -> dict:
    """把一套的参数编成任务：主进程只拼参数，真正干活在常驻 worker 里。"""
    item = spec["item"]
    job = f"{batch}/{item}"
    out_dir = ROOT / "out" / batch / item
    base = ROOT / "print" / "jobs" / batch / item / "base.stl"
    cutter = ROOT / "print" / "jobs" / batch / item / "cutter.stl"
    rep_p = out_dir / "report.json"

    argv = ["--input", spec["input"], "--out", str(out_dir), "--job", job,
            "--size", str(spec["size"]), "--relief", str(spec["relief"]),
            "--relief-mode", spec["mode"], "--no-index"]
    if not preview:
        argv.append("--no-preview")

    viewer = None
    if html:
        viewer = ["--stl", str(base), "--report", str(rep_p),
                  "--out", str(out_dir / "model.html"), "--title", f"{batch} · {item}",
                  "--cutter", str(cutter)]
        h = ROOT / "print" / "standard" / "handle_straight.stl"
        if h.exists():
            viewer += ["--handle", str(h)]      # 边框还没出时 viewer 自己会跳过缺失件？不——见 worker
    return {"item": item, "spec": spec, "job": job, "argv": argv, "viewer": viewer,
            "out_dir": str(out_dir), "base": str(base), "cutter": str(cutter),
            "report": str(rep_p)}


def collect(tasks: list[dict], results: list[dict]) -> list[dict]:
    """worker 只回 rc/耗时；报告与文件由主进程读，保证同一口径。"""
    by_item = {r["item"]: r for r in results}
    recs = []
    for t in tasks:
        spec = t["spec"]
        r = by_item.get(t["item"], {"rc": 1, "render_s": 0, "log": "worker 没返回结果"})
        rec = {**spec, "job": t["job"], "rc": r["rc"],
               "render_s": round(float(r.get("render_s") or 0), 1),
               "files": {}, "html": None, "err": None}
        if rec["rc"] != 0:
            rec["err"] = (r.get("log") or "").strip()[-800:]
            recs.append(rec)
            continue
        rep_p = Path(t["report"])
        rec["report"] = {}
        if rep_p.exists():
            rep = json.loads(rep_p.read_text(encoding="utf-8"))
            rec["report"] = {k: rep.get(k) for k in
                             ("relief_mode", "size_mm", "stamp_size_mm", "relief",
                              "base_thickness", "cavity_draft_deg", "engine",
                              "scad_render_s", "watertight", "triangles")}
        for k, p in (("base", t["base"]), ("cutter", t["cutter"])):
            if Path(p).exists():
                rec["files"][k] = p
        hp = Path(t["out_dir"]) / "model.html"
        if t.get("viewer") and hp.exists():
            rec["html"] = str(hp)
        recs.append(rec)
    return recs


def run_serial(tasks: list[dict], workers: int) -> list[dict]:
    """老路子：每套一个 python 子进程（便于单套排错，慢在重复导入）。"""
    def one(t):
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, str(ROOT / "src" / "stamp_pipeline.py")] + t["argv"],
                           cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")
        rc = p.returncode
        if rc == 0 and t.get("viewer"):
            v = subprocess.run([sys.executable, str(ROOT / "src" / "viewer" / "make_viewer.py")]
                               + t["viewer"], cwd=ROOT, env=ENV,
                               capture_output=True, text=True, encoding="utf-8")
            rc = rc if v.returncode == 0 else v.returncode
            if v.returncode:
                p = v
        return {"item": t["item"], "rc": rc, "render_s": round(time.perf_counter() - t0, 2),
                "log": (p.stderr or p.stdout or "").strip()}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, tasks))


def run_workers(tasks: list[dict], workers: int, on_done=None) -> list[dict]:
    """默认路子：N 个常驻 worker，每个只导入一次库，顺序跑自己分到的套。"""
    n = max(1, min(workers, len(tasks)))
    buckets = [[] for _ in range(n)]
    for i, t in enumerate(tasks):
        buckets[i % n].append(t)

    procs, tmp = [], ROOT / "print" / "_tmp" / "batch"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(buckets):
        if not b:
            continue
        tp, rp = tmp / f"tasks_{i}.json", tmp / f"results_{i}.json"
        tp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        if rp.exists():
            rp.unlink()
        procs.append((subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "batch_worker.py"), str(tp), str(rp)],
            cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE), rp))

    results = []
    for pr, rp in procs:
        stderr = pr.communicate()[1]
        if rp.exists():
            results.extend(json.loads(rp.read_text(encoding="utf-8")))
        else:
            tail = (stderr or b"").decode("utf-8", "replace").strip()[-600:]
            print(f"  [!] 一个 worker 没写结果：{tail}")
    for t in tasks:
        if t["item"] not in {r["item"] for r in results}:
            results.append({"item": t["item"], "rc": 1, "render_s": 0,
                            "log": "worker 崩溃，没拿到这套的结果"})
    return results


def mark_same_cutters(recs: list[dict]) -> None:
    """同形边框只提示、不删文件：同 size 同外框的两套，边框 STL 字节完全一致。"""
    import hashlib
    seen: dict[str, str] = {}
    for r in sorted(recs, key=lambda x: x["item"]):
        c = r["files"].get("cutter")
        if not c or not Path(c).exists():
            continue
        try:
            h = hashlib.sha256(Path(c).read_bytes()).hexdigest()
        except Exception:                  # noqa: BLE001
            continue
        if h in seen:
            r["cutter_same_as"] = seen[h]
        else:
            seen[h] = r["item"]


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
        cut_txt = Path(cut).name if cut else "缺"
        if r.get("cutter_same_as"):
            cut_txt = f"{Path(cut).name}（同 `{r['cutter_same_as']}`，不必重复打）"
        L.append(f"| `{r['item']}` | {Path(r['input']).name} | {rep.get('size_mm', r['size']):g} | "
                 f"{'凹模' if r['mode']=='sink' else '凸模'} | "
                 f"`{Path(base).name if base else '缺'}` | {cut_txt} | "
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
    ap.add_argument("--no-preview", action="store_true", help="跳过多栏预览图（更快，省 ~20%）")
    ap.add_argument("--preview", action="store_true", help="批量也出多栏预览图（默认不出，html 仍出）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 套（试跑用）")
    ap.add_argument("--serial", action="store_true",
                    help="每套起一个独立 python 进程（排错用，慢在重复导入约 4.7s/套）")
    args = ap.parse_args(argv)

    specs = read_list(Path(args.list))
    if args.limit:
        specs = specs[:args.limit]
    if not specs:
        print("[x] 清单是空的")
        return 2

    html = not args.no_html
    preview = bool(args.preview) and not args.no_preview
    tasks = [build_task(s, args.batch, html, preview) for s in specs]
    mode = "每套独立进程（--serial）" if args.serial else f"常驻 worker ×{args.jobs}（导入只付一次）"
    print(f"=== 批次 {args.batch}：{len(specs)} 套 · {mode} ===")
    t0 = time.perf_counter()
    results = run_serial(tasks, args.jobs) if args.serial else run_workers(tasks, args.jobs)
    wall = time.perf_counter() - t0
    recs = collect(tasks, results)
    for r in sorted(recs, key=lambda x: x["item"]):
        flag = "✓" if r.get("rc") == 0 else "×"
        print(f"  {flag} {r['item']:<18} {r['render_s']:>6.1f}s"
              + ("" if r.get("rc") == 0 else f"  {(r.get('err') or '')[-200:]}"))

    mark_same_cutters(recs)
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
