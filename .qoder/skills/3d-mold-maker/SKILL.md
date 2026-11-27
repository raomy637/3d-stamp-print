---
name: 3d-mold-maker
description: 3D打印模具制作与批次归档。线稿/文字走本仓库 stamp_pipeline（凸模 raise / 凹模 sink、文案镜像、边框手柄、批量）；AI 宠物图走 pet-relief（轮廓框+阴模盖）。用户要求做 3D 打印模具、粘土印章/曲奇模、凸模/凹模、图片转浮雕模具、打样/订单批量、P1S 试模、镜像确认、归档历史件时使用。不是全自动图片转三维服务，不自动启动打印。
---

# 3D打印模具制作

## 先确认，再落盘（硬门槛）

每次调用先过完整清单；缺一项就不建目录、不跑流水线：

1. 批次类型：打样 / 订单。
2. 打样项目名；或订单处理日期（`YYYYMMDD`）+ 订单号。
3. 收件箱批次目录与图片清单；每张图对应哪个 item；多款式是否分层。
4. 模具类型：凸模 `raise` / 凹模 `sink`。
5. 有无文案 + 翻压 / 正压，据此定镜像；有文案默认镜像，无文案默认不镜像，按压方式确认结果覆盖默认。
6. 成品尺寸、浮雕/槽深（默认 2.5）、是否出边框/手柄。
7. 外轮廓是否花瓣框：默认 `--frame-regularize auto` 检测；预览 `frame_check.png`，明显大小瓣再规整。
8. 数量：只记清单，不复制多份 STL。
9. 目标已存在：自动 `_v2`，不覆盖。
10. 先预览，再 build；批量同样两次确认。
11. 线宽路线：粗线存量（切片 100% 填充 + 8 墙）/ monoline 细线（源稿重画 ≈0.9mm，切片默认墙数）。细线路线禁止 `--stroke-cap` 算法收细；订单件改细线风格先给客户确认。判据与源稿要求见 `references/monoline-source.md`。

把确认结果原样写进本次 `manifest`；未确认的项不得用默认值偷偷开工。

## 两条路线

| 输入 | 路线 | 产物 |
|---|---|---|
| 线稿/文字/logo | 本仓库 `src/stamp_pipeline.py`；批量 `src/batch_molds.py` | `base.stl` + `cutter.stl`，另出合盘 `plate.stl`（两件同文件） |
| AI 宠物图（单主体、背景干净） | `D:\opencode\3Dprint\pet-relief\reliefgen.py` | `outline.stl` + `lid.stl` |

- 凸模：图案凸起，压出的成品是凹线。凹模：图案下沉成带 5° 脱模锥度的槽，成品图案凸起（见 `guides/cavity.md`）。
- 宠物浮雕的 `lid.stl` 出厂已镜像，压出方向才与原图一致；**不要对 lid 再套印章线的 `--no-mirror` 规则**。`positive_reference.stl` 是参考件，不是模具，不得混入打印清单。
- 路线不明确时先问，不猜。

## 数据根与目录

默认数据根：`D:\opencode\3D-stamp-print\work`（已在 `.gitignore` 排除）。完整树、命名、manifest 字段与迁移映射见 `references/folder-layout.md`。

```
work/
├─ _inbox/<批次名>/                 ← 用户丢图；只读，复制不移动
├─ 打样/<项目名>/{原始图,打印模型,_记录}
├─ 订单/<YYYYMMDD>/<订单号>/...     ← 多款式时加一层 <款式>
├─ _实验/                           ← 探针、对比、print/test
└─ _归档/                           ← 历史件、_archive、无法归类件
```

- 分类目录用中文；批次名、订单号、款式名用 ASCII，空格换 `_`。
- 打样单款式：`项目名/{原始图,打印模型,_记录}`；多款式在 `打印模型/`、`_记录/` 下加 `<款式>/`，原始图平铺。
- 订单单款式省略款式层；多款式加 `订单号/<款式>/`。
- `打印模型/` 只放可打印 STL；预览、`validation.json`、`job.json`、report 放同级 `_记录/`。
- 同名目标自动 `_v2`、`_v3`；不覆盖、不移动用户原图。
- `print/standard` 与 `out/handles` 是长期标准件，不迁。

## 执行流程

1. **归类计划**：读收件箱与可选 `manifest.csv`，运行
   `.venv\Scripts\python.exe .qoder\skills\3d-mold-maker\scripts\workspace.py plan ...`
   把源→目标、镜像结论、冲突项列给你确认；此步不写盘。
2. **建目录并复制原图**：确认后运行 `workspace.py apply --plan <plan.json>`。只复制，不移动；写入各单/款式的 `manifest.json`。
3. **预览**：按路线跑 preview，把真实文件给你看；印章线单套出 `preview.png`/`report.json`，要 `model.html` 另跑 `src/viewer/make_viewer.py`（批量 `batch_molds.py` 默认生成）；宠物浮雕出 `annotation_overlay.png`/`relief_front.png`/`relief_oblique.png`。分区/轮廓/镜像不对就改，不跳过。
4. **build**：你确认预览后才生成 STL；用 `workspace.py collect` 把可打印件收进 `打印模型/`，记录收进 `_记录/`。
5. **核验与汇报**：印章线读各件 `report.json`（水密/尺寸/体积/细线风险）；合盘 `plate.stl` 是底模同心套在边框内腔（装配间隙默认 0.8mm），导入后应保持这个位置，不要拖动或自动重排成左右分开；`make_print_index.py --check` 只覆盖旧 `print/` 批次，`work/` 订单以 report 与 collect 清单为准。宠物浮雕读 `validation.json`。只报实测值；未做实物打印/压泥就写“未验证”。
6. **打样转订单**：复制打样结果到订单目录并注明来源，不重新生成；除非你要求重做。

## 镜像判定

| 有无文案 | 按压方式 | mirror | 说明 |
|---|---|---|---|
| 有 | 翻压 | true | 默认；`--no-mirror` 禁用 |
| 有 | 正压 | false | 确认后可用 `--no-mirror` |
| 无 | 翻压 | true | 物理上仍会左右反 |
| 无 | 正压 | false | 默认无文案不镜像 |
| 未确认 | — | 默认按文案 | 必须在 build 前问清 |

- 只认一件事：成品是"翻过来压"还是"正面直接按"。文案只是默认值的来源，不是唯一判据。
- 动 `--no-mirror` 前必须得到本次确认；确认结果写进 manifest。
- 宠物浮雕 lid 的镜像由几何保证，不在此表内。

## 外轮廓花瓣规整

- 默认 `--frame-regularize auto`：只对“实心度 ≥0.92、圆度 ≥0.60、8–24 瓣、振幅 2–12%”的花瓣框生效；动物/异形剪影不动。
- 触发条件：角间距变异 ≥10% 或峰半径变异 ≥1.5%；否则保留原轮廓。
- 预览必须看 `frame_check.png`（绿=原轮廓、红/蓝=峰谷、橙=规整后）；切到图案会自动回退并记 `pattern_conflict`。
- 手动覆盖：`--frame-regularize off|force`、`--frame-petals N`；规整会把花瓣改成等距同大小，原图大小瓣不再保留。

## 线宽与源稿口径

- 蜂窝/直线观感的根因在**源稿线宽**：≈2×喷嘴线宽（0.4→0.9mm）时 Arachne 2 条变宽墙填实整条线，15% 填充也不蜂窝；1.3–3.0mm 粗线只能靠切片 100% 填充 + 8 墙实心。
- 细线观感首选**代码中心线归一** `src/tools/monoline_normalize.py`（骨架+剪毛刺+定半径重建，忠实原图中心线）；目标线宽受源稿最密特征间距限制（santa 实测上限 0.6mm）。禁止生图模型重新创作订单图案；`--stroke-cap` 量产禁用。验收测试 `tests/test_monoline_normalize.py`。
- 外框只取剪影：单闭合环、与图案分离、环自身面积 ≥2% 图幅（可单独加粗外框，不影响细线观感）；不满足会退化圆底。AI 稿多余内环按填充比 >3 删除，只涂白删除区保留灰度。
- 细则、核验落点与实测见 `references/monoline-source.md`。

## 迁移历史件

- 先出 dry-run：`workspace.py migrate-plan --repo . --root work`
- 报告核对后再 `migrate-apply --plan ...`；只复制，不删旧件。
- 无法确认打样/订单属性的历史件统一进 `_归档/历史件`，保留原相对路径。
- 探针/对比/`print/test` 进 `_实验`；`_archive` 进 `_归档`；标准件留原地。

## 核验红线

- 水密、单实体、体积为正、尺寸符合请求；框盖干涉 ≤ 0.01 mm³（宠物浮雕）。
- 合盘 `plate.stl` 是两个互不相连的水密壳：底模同心套在边框内腔，间隙 = `--cutter-clearance`（默认 0.8mm），面数 = 两件之和；不能焊在一起。
- 切片口径按线宽路线：粗线存量件 Arachne + **100% 填充（底线）** + 顶壳 ≥6，熨烫关，0.4 喷嘴再加 **8 墙**（0.42×8=3.36mm ≥ 最大笔画 2.8–3.0mm），0.2 喷嘴以 100% 填充为准；monoline 细线件（max ≤1.3mm）默认 2–3 墙 + Arachne 即可，填充随意。
- 源稿有外框但 `report.json` 的 `frame.reason == "no_frame"` ⇒ 停，修源稿外框（加粗/分离），不交圆底件；monoline 件 `stroke_stats_mm.max > 1.3` ⇒ 停，重画。预览缺部件时以 STL 剖切为准（双环源稿有预览渲染 bug）。
- 失败就停，交付错误信息与已生成文件路径，不强行输出。
- 不把试模授权当客户审稿；不宣称实物打印、脱模、收缩已验证。

## 资源

- `references/folder-layout.md`：目录树、命名、manifest、迁移映射。
- `references/pipeline-commands.md`：两条路线的命令与参数。
- `references/frame-regularize.md`：花瓣检测阈值、重建算法、report 字段与实测。
- `references/monoline-source.md`：细线源稿线宽/外框/prep 要求、report 核验落点与实测。
- `scripts/workspace.py`：plan / apply / collect / migrate-plan / migrate-apply。
