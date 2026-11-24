# -*- coding: utf-8 -*-
"""临时：生成一个自动点击某个按钮的 HTML 副本，供 headless 截图验证视角。"""
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
clicks = [x for x in sys.argv[3:]]

html = src.read_text(encoding="utf-8")
js = "".join("document.getElementById('%s').click();" % c for c in clicks)
inject = "<script>setTimeout(function(){%s}, 600);</script></body>" % js
html = html.replace("</body>", inject)
dst.write_text(html, encoding="utf-8")
print("written", dst)
