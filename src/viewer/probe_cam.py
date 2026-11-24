import sys, re, pathlib
src = pathlib.Path(sys.argv[1]); dst = pathlib.Path(sys.argv[2]); tag = sys.argv[3]
html = src.read_text(encoding="utf-8")
ins = {
 "A": "mode='asm'; applyMode(); view.az=-1.75; view.el=0.30; refresh();",
 "B": "view.az=0.35; view.el=0.05; refresh();",
 "C": "mode='asm'; applyMode(); view.az=-2.55; view.el=0.18; refresh();",
}[tag]
html = html.replace("requestAnimationFrame(tick);\n})();", ins + "\nrequestAnimationFrame(tick);\n})();")
dst.write_text(html, encoding="utf-8")
print("ok", dst)
