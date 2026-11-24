#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻出件 worker：一个进程里连续跑多套，只付一次 Python 导入成本。

    python src\\batch_worker.py <tasks.json> <results.json>

tasks.json 是任务数组，每项：
    {"item": "<单号>", "argv": [<stamp_pipeline 参数>], "viewer": [<make_viewer 参数>] | null}

为什么需要它：每套单独起 `python stamp_pipeline.py` 时，numpy/scipy/skimage/shapely/trimesh
要重新导入约 4.7s（40 套就是 188s 纯 CPU）。这里把任务分片给 N 个常驻进程，
每片只导入一次，其余时间全在算几何。

不改变任何几何：调用的仍是同一个 `stamp_pipeline.main()` / `make_viewer.main()`。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
import traceback
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import importlib.util     # noqa: E402

import stamp_pipeline      # noqa: E402  （导入一次，后面复用）


def _load_viewer():
    """src/viewer 不是包（没有 __init__.py），按文件路径加载。"""
    p = SRC / "viewer" / "make_viewer.py"
    spec = importlib.util.spec_from_file_location("make_viewer", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


make_viewer = _load_viewer()


def call(fn, argv):
    """跑一个 main(argv) 并把它的日志收进缓冲，只留尾巴。"""
    buf = io.StringIO()
    rc = 0
    try:
        with contextlib.redirect_stdout(buf):
            rc = fn(argv)
    except SystemExit as exc:                     # argparse 的 --help / 参数错
        rc = int(exc.code or 0)
    except Exception:                             # noqa: BLE001
        buf.write("\n" + traceback.format_exc())
        rc = 1
    tail = buf.getvalue().strip().splitlines()[-6:]
    return rc, "\n".join(tail)


def sanitize_viewer(argv):
    """边框/手柄还没出时，把指向不存在文件的 --cutter/--handle 摘掉，别让 viewer 崩。"""
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--cutter", "--handle") and i + 1 < len(argv) and not Path(argv[i + 1]).exists():
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: batch_worker.py <tasks.json> <results.json>")
        return 2
    tasks_p, results_p = Path(argv[0]), Path(argv[1])
    tasks = json.loads(tasks_p.read_text(encoding="utf-8"))

    results = []
    for t in tasks:
        t0 = time.perf_counter()
        rc, log = call(stamp_pipeline.main, t["argv"])
        vrc, vlog = 0, ""
        if rc == 0 and t.get("viewer"):
            vrc, vlog = call(make_viewer.main, sanitize_viewer(t["viewer"]))
        results.append({
            "item": t["item"],
            "rc": rc,
            "viewer_rc": vrc,
            "render_s": round(time.perf_counter() - t0, 2),
            "log": log if rc == 0 else (log + "\n" + vlog).strip(),
        })
    results_p.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
