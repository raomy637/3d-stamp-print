"""OpenSCAD 渲染后端：shapely 2D 轮廓 -> polygon() 模块 -> openscad -> STL。

为什么不用 SVG import：OpenSCAD 2021.01 对多个 SVG 的 y 轴映射不一致
（实测 outline 落在 0..84.2，pattern 落在 72.37..168.4），
两件 union 会整体错位；polygon() 是纯数值，没有解析歧义。

参数一律通过 -D 传入：job.scad 只提供 2D 模块与模板正文，
不再给同名变量赋值，避免 `x = is_undef(x) ? 默认 : x` 在同作用域里自我覆盖。
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

REPO = Path(__file__).resolve().parent.parent
SCAD_DIR = REPO / "scad"


def find_openscad() -> Path | None:
    """按 环境变量 -> repo 内 tools/ -> PATH 的顺序找 openscad 可执行文件。"""
    env = os.environ.get("OPENSCAD_BIN")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    for name in ("openscad.com", "openscad.exe"):
        p = REPO / "tools" / "openscad" / name
        if p.is_file():
            return p
    for name in ("openscad", "openscad.com", "openscad.exe"):
        w = shutil.which(name)
        if w:
            return Path(w)
    return None


def _fmt(v: float, nd: int = 3) -> str:
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _lit(v) -> str:
    if isinstance(v, str):
        return '"' + v.replace("\\", "/") + '"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _fmt(float(v), 6)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    raise TypeError(f"不支持的参数类型: {type(v)}")


def geom_to_scad_module(geom, name: str) -> str:
    """把 shapely 多边形写成 OpenSCAD 的 polygon() 模块（坐标原样，y 向上）。"""
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    lines = [f"module {name}() {{"]
    for poly in polys:
        if poly.is_empty:
            continue
        ext = list(poly.exterior.coords)[:-1]
        if len(ext) < 3:
            continue
        pts = [f"[{_fmt(x)}, {_fmt(y)}]" for x, y in ext]
        idx = list(range(len(ext)))
        paths = [idx]
        base = len(ext)
        for ring in poly.interiors:
            c = list(ring.coords)[:-1]
            if len(c) < 3:
                continue
            pts += [f"[{_fmt(x)}, {_fmt(y)}]" for x, y in c]
            paths.append(list(range(base, base + len(c))))
            base += len(c)
        p_str = "[" + ", ".join(pts) + "]"
        path_str = "[" + ", ".join("[" + ", ".join(str(i) for i in p) + "]" for p in paths) + "]"
        lines.append(f"    polygon(points = {p_str}, paths = {path_str});")
    lines.append("}")
    return "\n".join(lines)


def write_job_scad(modules: dict[str, str], template: Path, out: Path) -> Path:
    """写 job.scad：先给 2D 模块，再拼模板正文。参数由 -D 传，不落在文件里。"""
    body = template.read_text(encoding="utf-8")
    parts = [f"// 由 src/scad_engine.py 自动生成（模板：{template.name}），勿手改", ""]
    for text in modules.values():
        parts.append(text)
        parts.append("")
    parts.append(body)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def render(scad_file: Path, stl_file: Path, defs: dict | None = None,
           timeout: int = 1800) -> tuple[bool, float, str]:
    """调 openscad 渲染。返回 (成功, 耗时秒, 日志尾部)。"""
    exe = find_openscad()
    if exe is None:
        return False, 0.0, "找不到 openscad：用 OPENSCAD_BIN 指定，或放到 tools/openscad/"
    stl_file.parent.mkdir(parents=True, exist_ok=True)
    if stl_file.exists():
        stl_file.unlink()
    cmd = [str(exe)]
    for k, v in (defs or {}).items():
        cmd += ["-D", f"{k}={_lit(v)}"]
    cmd += ["-o", str(stl_file), "--export-format", "binstl", str(scad_file)]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, f"openscad 超时（>{timeout}s）"
    dt = time.time() - t0
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-6:] +
                     (proc.stderr or "").strip().splitlines()[-4:])
    ok = proc.returncode == 0 and stl_file.exists() and stl_file.stat().st_size > 0
    return ok, dt, tail


def as_multipolygon(g) -> MultiPolygon:
    if g is None or g.is_empty:
        return MultiPolygon()
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    return g


def draft_ratio(relief_mm: float, draft_deg: float, geom) -> float:
    """把「每侧外张 relief*tan(draft)」折算成 linear_extrude 的缩放比。

    scale 是整体等比缩放，不是等距 offset；用包围盒半对角当特征半径，
    最远点的内缩量等于设计值，细线宽度变化 <1%。
    """
    if draft_deg <= 0 or relief_mm <= 0 or geom.is_empty:
        return 1.0
    minx, miny, maxx, maxy = geom.bounds
    r = 0.5 * math.hypot(maxx - minx, maxy - miny)
    if r <= 1e-6:
        return 1.0
    inset = relief_mm * math.tan(math.radians(draft_deg))
    return 1.0 + inset / r
