# 3D 印章流水线（凸版 / 粘土）

一张线稿 → 可直接切片的粘土饼干模具 STL。换图案只改 `--input`，其余参数复用。

三件分体：边框（切粘土外形）/ 底模（压图案）/ 手柄（定尺寸批量打）。尺寸链与依据见 [guides/parts.md](guides/parts.md)。

输出怎么找：能打印的 `.stl` 全在 `print/`，其余看 `out/<图案>/`，总表是根目录 `PRINT.md`（自动生成）。约定见 [guides/output-layout.md](guides/output-layout.md)。

整套流程也打包成了 Skill：`clay-stamp-mold`（装在 workspace 的 `.user_skills` 下），一条 `scripts/run_job.py --input 图 --job 名字` 就能跑完出件、3D 预览、手柄补料和打印清单体检。

## 凸模还是凹模

默认出凸模（印章）：图案凸起，压到粘土上得到凹线。加 `--relief-mode sink` 就出凹模：图案沉成带 5° 脱模锥度的槽，压出来的成品图案是**凸**的。边框和手柄两套共用，只换底模；原理、锥度取值、深度上限与坑见 [guides/cavity.md](guides/cavity.md)。

```
python stamp_pipeline.py --input inputs\bakers_framed.png --out out\bakers_cav --size 85 --relief 1.8 --relief-mode sink
```

## 版本与备份

本地 git 仓库，远端私有仓库 [raomy637/3d-stamp-print](https://github.com/raomy637/3d-stamp-print)（SSH，`origin/main` 已跟踪）。跑完一轮留档：`git add -A` → `git commit -m "改了什么"` → `git push`。

`.gitignore` 只排除缓存与探针副本（`__pycache__`、`_p_*.html`）和切片产物（`*.gcode`、`*.3mf`）；STL 与 `model.html` 都入库，克隆即得完整可打状态。

## 文件



| 路径                              | 作用                                                      |
| ------------------------------- | ------------------------------------------------------- |
| `stamp_pipeline.py`             | 线稿 → 底模 STL + 边框 STL + 清单 + 预览图 + 可选 SVG                |
| `make_handle.py`                | 手柄 STL（可 `--count` 联排，一次打一批）                            |
| `make_print_index.py`           | 扫 `print/` 生成根目录 `PRINT.md`（打印总表）                       |
| `print/`                        | 唯一能直接拿去切片的地方，只放 `.stl`                                  |
| `out/<图案>/`                     | 每次运行的全部记录（清单 / 报告 / 预览 / SVG / 3D）                      |
| `out/handles/` `out/_archive/`  | 手柄体检图 / 淘汰件留档                                           |
| `viewer/make_viewer.py`         | 把 STL 打包成单文件离线 HTML 预览（可带边框 / 手柄）                       |
| `tools/preview_handle_batch.py` | 画手柄联排俯视图                                                |
| `guides/`                      | `parts.md` 尺寸链・`cavity.md` 凹模・`printing.md` 切片・`output-layout.md` 输出约定 |
| `inputs/`                       | 源图                                                      |
| `CHANGELOG.md`                  | 版本变更与决策记录                                               |

## 它做的事



```
线稿 PNG ─► 二值化/去噪 ─► 外框识别 ─► 线宽体检 ─► 矢量化(含孔洞) ─► 镜像 X ─► 缩放到 --size ─► 居中
              └─► 外框 → 底面轮廓（异形边自动继承）
                            ├─► 底面/图案 2D 布尔 ─► 拉伸 ─► 底模 STL（水密）
                            └─► 同轮廓 buffer(墙/翼缘) ─► 外表面收成刃口 ─► 边框 STL（水密）
```



| 关键点    | 说明                                                |
| ------ | ------------------------------------------------- |
| 外框自动分离 | 闭合的边框连通块会变成底面轮廓（扇贝边 / 圆 / 异形都继承），框体本身丢弃，不再留一道多余凸筋 |
| 细线安全   | 先统计每个部件实际线宽，只把本来印不出来的部件按骨架加粗，粗笔画一个字不动             |
| 默认镜像   | 凸印章必须镜像压出来才正读，`--no-mirror` 可关                    |
| 水密单体   | 底板与浮雕先在 2D 布尔再梯形拉伸、manifold 并集，导出单一封闭网格，切片器不用修面   |
| 边框同源   | 边框内腔用同一个底面轮廓（不缩），底模按环隙内缩，切出来的粘土和压上去的图案严格对位        |

## 安装依赖



```
python -m pip install numpy pillow scipy scikit-image shapely trimesh mapbox-earcut manifold3d
```

## 用法



```
# 1) 底模 + 边框：成品 85mm，浮雕 1.8mm，附带分层 SVG 和预览图
python stamp_pipeline.py --input inputs\bakers_framed.png --out out\bakers_v3 --size 85 --relief 1.8 --svg
#    → print\bakers_v3_base.stl（底模，可打印）  print\bakers_v3_cutter.stl（边框，可打印）
#    → out\bakers_v3\（MANIFEST.md / report.json / preview.png / lines.svg）
# 只要底模不要边框
python stamp_pipeline.py --input 图案.png --out out\xxx --no-cutter
# 没有外框的图：底面自动变成圆
python stamp_pipeline.py --input 图案.png --out out\xxx --size 80
# 只有 0.4 喷嘴：把所有细线统一拉到 0.9mm
python stamp_pipeline.py --input 图案.png --out out\xxx --min-stroke 0.9
# 不要外框、强制圆底
python stamp_pipeline.py --input 图.png --out out\xxx --frame-mode ignore

# 2) 手柄（只在换尺寸时才重跑，平时直接打 print\ 里现成的）
python make_handle.py                      # 单个 -> print\handle_slim.stl
python make_handle.py --count 6            # 一排 -> print\handle_x6.stl（124×14）
python make_handle.py --count 12 --cols 6  # 一盘 -> print\handle_x12.stl（124×36）

# 3) 看总表 / 体检 print\ 里能不能直接打
python make_print_index.py                 # 刷新 PRINT.md
python make_print_index.py --check         # 只查不改，退出码 0 = 全部可打
```

产出分两处。`print/` 只放可打印 `.stl`（`<图案>_base` / `<图案>_cutter` / `handle_*`）；`out/<图案>/` 放给人看的东西（MANIFEST.md 清单、report.json 体检、preview.png 三栏预览、lines.svg、model.html）。布局细节见 [guides/output-layout.md](guides/output-layout.md)。

## 参数



| 参数                     | 默认         | 说明                                                    |
| ---------------------- | ---------- | ----------------------------------------------------- |
| `--size`               | 85         | 成品外形 = 边框内腔 mm；底模自动内缩 2×`cutter_clearance`            |
| `--base-thickness`     | 3.0        | 底板厚度 mm                                               |
| `--relief`             | 1.8        | 图案凸起高度 / 凹模槽深 mm。粘土 1.5–2.0 最合适，再高压变形            |
| `--relief-mode`        | raise      | `raise`=印章（成品凹线）；`sink`=凹模（成品凸起，带脱模锥度）                  |
| `--cavity-draft`       | 5.0        | 凹模槽壁外张锥度 °；0 = 垂直墙（脱模会拽断细线）                            |
| `--cavity-segments`    | 4          | 凹模锥面阶梯段数；8 更顺、面数翻倍                                |
| `--margin`             | 1.2        | 底面轮廓相对图案外扩的边距 mm                                      |
| `--cutter-wall`        | 1.2        | 边框墙厚 mm（0.4 喷嘴下正好 3 圈实心）                              |
| `--cutter-height`      | 12         | 边框总高 mm（行业 12–15，粘土取 12）                              |
| `--cutter-edge`        | 0.4        | 刃口厚度 mm（0.4–0.5 才切得动）                                 |
| `--cutter-edge-h`      | 3.0        | 刃口锥段高度 mm（外表面向上收窄）                                    |
| `--cutter-flange-w/-t` | 4.0 / 1.6  | 底部翼缘宽 / 厚 mm（贴床防翘 + 翻过来当握边）                           |
| `--cutter-clearance`   | 0.4        | 底模与边框内腔的单边间隙 mm（行业标准值）                                |
| `--no-cutter`          | 关          | 不出边框 STL                                              |
| `--print-dir`          | print      | 可打印 STL 落到哪个目录                                        |
| `--rim-w` / `--rim-h`  | 0 / 0.4    | 旧的一体式凸边缘（淘汰写法，>0 时与独立边框互斥）                            |
| `--min-stroke`         | 0          | 最小线宽 mm。0.4 喷嘴填 0.9，0.2 喷嘴填 0.55                      |
| `--grow`               | 0          | 图案整体外扩 mm，慎用（会让字糊在一起）                                 |
| `--frame-mode`         | silhouette | `silhouette`= 框→底轮廓并丢弃；`keep`= 框保留成浮雕；`ignore`= 丢框用圆底 |
| `--scale`              | 1          | 先放大原图（低分辨率细线补救）                                       |
| `--no-mirror`          | 关          | 关掉镜像（只做摆件时用）                                          |
| `--thr` / `--invert`   | 自动 / 关     | 手动二值阈值 0–255 / 白线黑底时打开                                |
| `--simplify`           | 0.02       | 曲线简化容差 mm，越大面数越少、越硬                                   |
| `--svg`                | 关          | 同时导出分层 SVG                                            |

## 输入图要求

单色线稿、黑白对比清晰、线条最好闭合；带扇贝边或圆框的图直接可用，框会被吃掉。不适合照片、渐变灰度、需要多色分层的插画（那种应该走 "图像→浮雕高度贴图"，不是本工具）。

## 手柄：独立标准件，一次打一批

手柄不跟底模一起出。底模是每张图都要重做的，手柄是一套配所有的零件，所以由 `make_handle.py` 单独出、尺寸定死、批量打印：



| 项  | 值                                 |
| -- | --------------------------------- |
| 底盘 | φ14 × 1.4mm（粘接面 154mm²，502 一薄圈就够） |
| 握柄 | φ9.8–11，轻微腰形（拇指食指捏）               |
| 总高 | 25mm（小把手，捏着按，不占地方）                |
| 网格 | 1,728 面，水密，2.03 cm³/ 个            |

为什么必须分件：一体打印且图案朝上时，手柄在底面一侧必然悬空、要支撑；主流做法（MakerWorld 的 Cat Paw 印章、Instructables 曲奇模）都是手柄站立打印 + 502 粘背面。分件的额外好处是换图案不用重打手柄，坏一个只补一个。

粘接：两个平面用酒精擦净 → 底模背面中心涂一圈 502 → 手柄底盘压上，保持 30 秒。

要换款式就改 `make_handle.py` 里的 `HANDLE_PROFILE`（一串 `(半径, 高度)`），重跑脚本即可，底模一行不用动。现成件：`print\handle_slim.stl`（单个）、`print\handle_x6.stl`（一排）、`print\handle_x12.stl`（一盘）。

## 边框：独立切模

边框不跟底模连在一起。它只有一圈 1.2mm 的墙 + 0.4mm 刃口，负责切出粘土外形；底模负责压图案。两件靠 0.4mm 环隙对位。



| 项       | 值                                     |
| ------- | ------------------------------------- |
| 内腔      | `--size`（= 切出来的粘土尺寸）                  |
| 墙厚 / 总高 | 1.2 / 12mm（翼缘 1.6 → 主体到 9 → 刃口锥段到 12） |
| 刃口      | 0.4mm，外表面收窄，内腔全程不缩                    |
| 翼缘      | 4.0 × 1.6mm，贴床防翘 + 翻过来当握边             |
| 网格      | 95.4×95.4×12mm、58.9k 面、水密、5.6 cm³     |

使用顺序：边框扣在粘土上压到底 → 底模图案朝下滑进内腔 → 手掌压手柄 → 连边框一起拿起，粘土留桌上。参数出处见 [guides/parts.md](guides/parts.md)。

## 打印朝向与切片

底模平板贴床、图案（或凹槽）朝上、追求平整印面用光面/玻璃板（纹理 PEI 会把纹路翻印到印面）；边框翼缘贴床、刃口朝上，打完翻过来用；手柄底盘贴床直立。三件都免支撑。切片：底模 0.2 喷嘴 / 0.10 层高 / 4 墙 / 顶面熨烫，只有 0.4 喷嘴时先加 `--min-stroke 0.9`；边框与手柄的层高、brim、后处理见 [guides/printing.md](guides/printing.md)。

旧的一体式 `--rim-w`（外沿凸起一道随底板走的墙）保留但默认关闭：它和独立边框互斥，换图案就得重打那道墙，属于被淘汰的写法。

## 3D 预览（HTML，离线可转）

`viewer/make_viewer.py` 把 STL 打包成一个单文件 HTML：three.js 与轨道控制器全部内联、网格量化成 uint16 内嵌，双击即开、不联网。

```
python viewer\make_viewer.py --stl print\bakers_v3_base.stl --cutter print\bakers_v3_cutter.stl `
    --handle print\handle_slim.stl --report out\bakers_v3\report.json --out out\bakers_v3\model.html
```

当前两套都已生成：双击 `out\bakers_v3\model.html`（凸模）、`out\bakers_cav\model.html`（凹模）。界面左上角是参数面板（尺寸 / 槽深 / 是否镜像），底部按钮：分离 / 装配 / 自动旋转 / 俯视 / 侧视 / 背面（俯视验镜像、侧视看厚度、背面看粘接面）。

## 已知限制

| 限制         | 现状                                                          |
| ---------- | ----------------------------------------------------------- |
| 边框与底模无机械限位 | 靠人手对位 + 0.4mm 环隙；要 "扣上就对齐" 得加定位环或卡爪，尚未做                     |
| 刃口锥段是台阶近似  | 8 段分层而非真斜面，0.16 层高下能看出轻微台阶，不影响切割                            |
| 手柄无定位销     | φ14 平面粘接，手涂 502 容易粘偏（粘接面只有 154mm²，别把胶涂到边缘外）                 |
| 外框识别是启发式   | 靠 "铺满整图 + 闭合环"，四边都有装饰且不闭合的构图可能判错，用 `--frame-mode ignore` 兜底 |
| 重叠部件会被合并   | `unary_union` 合并重叠图案；相距很近但不接触的保留为独立浮雕                       |