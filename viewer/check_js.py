# -*- coding: utf-8 -*-
"""语法体检：把 HTML 里最后一段 <script> 抽出来丢给 node --check。"""
import os
import pathlib
import re
import subprocess
import sys

html_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("out/viewer/bakers_v2.html")
html = html_path.read_text(encoding="utf-8")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
print("script blocks:", len(scripts), [len(s) for s in scripts])

tmp = pathlib.Path(os.environ.get("TEMP", ".")) / "viewer_check.js"
tmp.write_text(scripts[-1], encoding="utf-8")
r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True, encoding="utf-8")
print("node --check rc =", r.returncode)
print((r.stdout or "")[-2000:])
print((r.stderr or "")[-2000:])
