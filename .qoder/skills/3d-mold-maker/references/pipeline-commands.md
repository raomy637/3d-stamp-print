# 两套流水线的命令与参数

工作目录始终是仓库根 `D:\opencode\3D-stamp-print`；宠物浮雕程序用绝对路径，不切换工作区。

印章线解释器优先用仓库内 `.venv\Scripts\python.exe`（本机已装齐依赖，`.venv` 已 gitignore）；只有该路径不存在时才回退 `python`，并先跑依赖自检。

## 依赖自检

印章线：

```text
.venv\Scripts\python.exe -c "import numpy,PIL,scipy,skimage,shapely,trimesh,mapbox_earcut,manifold3d"
```

缺包时报告具体缺项，按 README 安装；不要静默替换环境。OpenSCAD 优先用 `tools\openscad\openscad.exe`。

宠物浮雕：

```text
D:\opencode\3Dprint\pet-relief\.venv\Scripts\python.exe D:\opencode\3Dprint\pet-relief\reliefgen.py check
```

只允许把依赖装进 `pet-relief\.venv`，不改全局 Python。

## 印章线：单套

```text
.venv\Scripts\python.exe src\stamp_pipeline.py --input "inputs\图.png" --out out\<job> ^
  --size 85 --relief 2.5 --relief-mode raise ^
  --close-gap 1.5 --cutter-clearance 0.8
```

- `--relief-mode raise`：凸模，成品凹线；`sink`：凹模，成品凸起，默认 5° 脱模锥度。槽深受底板限制（`min(relief, base-1)`），要 2.5 槽深需 `--base-thickness 4.0`，否则日志会提示并压到 2.0。
- 默认镜像；只有确认过“正压”才加 `--no-mirror`。
- 外轮廓：默认 `--frame-regularize auto`；明显大小瓣会按检测到的瓣数规整，生成 `frame_check.png`。`off` 保留原轮廓，`force` 强制，`--frame-petals N` 指定瓣数。
- 常用：`--min-stroke 0.9`（0.4 喷嘴）、`--cutter-height 15`、`--no-cutter`、`--no-mirror`。
- monoline 细线件：先 `.venv\Scripts\python.exe src\tools\monoline_normalize.py --input 原图.png --out 细线.png --size 101.6 --target-mm 0.6`（代码中心线归一，目标线宽受源稿最密间距限制，见 `references/monoline-source.md`），再跑单套命令、**不加 `--stroke-cap`**；切片默认 2–3 墙 + Arachne。核验 `frame.reason != no_frame` 且 `stroke_stats_mm.max <= 1.3`。
- 输出：`print\jobs\<job>\base.stl`、`cutter.stl`、`plate.stl`（底模同心套在边框内腔、同一文件）；`out\<job>\` 内 `report.json`、`preview.png`、`MANIFEST.md`、可选 `lines.svg`/`frame_check.png`。单套不自动出 `model.html`，需要时另跑 `src\viewer\make_viewer.py` 写到 `out\<job>\model.html`。
- `plate.stl` 与分开件同时生成，不是替代；`--no-cutter` 时没有合盘。

## 印章线：批量

清单 CSV：

```text
item,input,size,relief,mode
A_snowman,inputs/snowman.png,85,2.5,raise
B_star,inputs/star.png,70,2.5,sink
```

```text
.venv\Scripts\python.exe src\batch_molds.py --batch 20261126_pets --list inputs\batch_pets.csv --jobs 8
```

- 先 `--limit 2` 试跑两套看图，再跑全批；`--preview` 才出三栏预览图，`--no-html` 才跳过每套自动生成的 `model.html`。
- 输出：`print\jobs\<批次>\<单号>\{base,cutter}.stl`；`out\<批次>\<单号>\...` + `INDEX.md`、`batch.json`。
- 批次名纯 ASCII、无空格；同一批次 item 不得重名。
- 跑完 `.venv\Scripts\python.exe src\make_print_index.py --check`（只覆盖旧 `print/` 批次），退出码 0 才叫“可打”；`work/` 订单验收读各件 `report.json`。

## 宠物浮雕：准备与标注

```text
D:\opencode\3Dprint\pet-relief\.venv\Scripts\python.exe D:\opencode\3Dprint\pet-relief\reliefgen.py prepare --image "客户样图.png" --job "D:\...\job.json"
```

- 看 AI 重绘图，核对姿势、耳形、翅膀和细弱连接；确认最长边（>0 且 ≤100，未指定用 95）。
- 每个任务单独建；不复用示例坐标。
- 填 `annotation`：闭合外轮廓、正浮雕分区、开放的眼睛/嘴巴沟槽；像素坐标 X 右 Y 下，路径不越界、不自交。

预览：

```text
... reliefgen.py preview --job "job.json" --output "D:\...\preview-v1" --size 95 --relief 4
```

Read `annotation_overlay.png`、`relief_front.png`、`relief_oblique.png`，确认轮廓贴合、凸起正确、细羽毛未丢。

生成：

```text
... reliefgen.py build --job "job.json" --output "D:\...\trial-v1" --size 95 --relief 4 --approve-annotation
```

- 交付：`outline.stl`（轮廓框）、`lid.stl`（阴模盖，凹面已镜像）、`positive_reference.stl`（参考件，不是模具）。
- `validation.json` 读实测：尺寸、水密、单实体、法向、体积、框盖干涉 ≤ 0.01 mm³。
- 挂孔默认不生成；需要挂环时另行改几何或成型后冲孔，不声称已支持。
- 宠物图有文字时，lid 仍按几何镜像；不要套印章线的 `--no-mirror`，否则压出方向会反。

## 工作目录脚本

```text
.venv\Scripts\python.exe .qoder\skills\3d-mold-maker\scripts\workspace.py plan ^
  --root work --kind order --batch 20261126_pets --inbox "work\_inbox\20261126_pets" ^
  --date 20261126 --manifest "work\_inbox\20261126_pets\manifest.csv" --route stamp
```

- `plan` 只读，输出源→目标、mirror、冲突；确认后再 `apply --plan <plan.json>`。
- `apply` 只复制原图并建目录，不动收件箱，不覆盖；同名自动 `_v2`。
- 印章线：`collect --plan <plan.json> --item <款式> --model-dir "print\jobs\<job>" --record-dir "out\<job>"`。
- 宠物浮雕：`collect --plan <plan.json> --item <款式> --source-dir "<reliefgen 输出目录>"`（STL 与记录同目录）。
- `collect` 把可打印件收进 `打印模型\`，其余记录进 `_记录\`。
- `migrate-plan --repo . --root work` 只出报告；`migrate-apply --plan ...` 只复制、不删旧件。
