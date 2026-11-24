# 批量出模（10 / 20 / 40 套）

一次要做几十套完全不同的模具时，怕的不是生成慢，是**配对错**、**找不到哪个文件是哪套**。所以这里只有两条规矩：目录就是配对关系，清单就是唯一入口。

## 目录：两级，配对靠路径保证

```
print/jobs/<批次>/<单号>/base.stl      底模（或凹模）
print/jobs/<批次>/<单号>/cutter.stl    这一套的边框
out/<批次>/<单号>/                     report.json / preview.png / MANIFEST.md / model.html
out/<批次>/INDEX.md                    批次总表
out/<批次>/batch.json                  机器读：参数 + 耗时 + 体检
```

底模和边框**永远同目录同单号**，不存在"A 的底模配 B 的边框"这种可能——配对不靠文件名前缀，靠路径唯一性。拷到 U 盘也只拷一个文件夹。

单层旧结构（`print/jobs/<单号>/`）继续有效：`make_print_index.py` 会先看目录里有没有 `base.stl` / `cutter.stl`，有就当单套，没有就往下遍历一层当批次。两种可以混放，`PRINT.md` 里分别显示 `bakers_v5` 和 `xmas40/snowman_A`。

## 命名

| 对象 | 规则 | 例子 |
|---|---|---|
| 批次 | `日期_主题_数量`，纯 ASCII | `2026-11-24_xmas_40`、`2026-12-01_pets_20` |
| 单号 | 图案 slug，批量时前面加 `A_` / `B_` 便于口头对号 | `A_snowman`、`B_star`、`01_santa` |

批次名会进路径，**别用空格与中文**（Windows 下 PowerShell 与切片器都容易踩引号坑）；中文只放在 `INDEX.md` 的说明列里。单号取文件名 stem 即可，脚本缺省就这么干。

## 清单

一个 CSV（也吃 JSON 数组），五列，后三列可省略：

```
item,input,size,relief,mode
A_snowman,inputs/snowman.png,85,1.8,raise
B_star,inputs/star.png,70,2.0,raise
C_tree,inputs/tree.png,85,1.8,sink
```

- `item` 空则用 `input` 的文件名 stem
- `size` 缺省 85、`relief` 缺省 1.8、`mode` 缺省 `raise`（`sink` = 凹模）
- 以 `#` 开头的行是注释，可以拿来分组
- 同一批次里尺寸可以各不相同（每套独立算），互不影响

## 跑

```
python src\batch_molds.py --batch 2026-11-24_xmas_40 --list inputs\batch_xmas40.csv --jobs 8
python src\batch_molds.py --batch ... --list ... --limit 2      # 先试跑两套，看图对不对
python src\batch_molds.py --batch ... --list ... --no-html      # 不要每套的 3D 预览
python src\batch_molds.py --batch ... --list ... --no-preview   # 不要三栏预览图（省 ~15%）
```

`--jobs` 默认 `min(8, CPU线程/2)`。单套失败不阻塞其他套：失败的那行在 `INDEX.md` 里标「失败」并把最后 800 字错误留在 `batch.json`，其余照跑，退出码 1。

跑完自动刷新 `PRINT.md`（一次，不是每套一次）；单套用 `--no-index` 跳过，避免 40 个进程抢着写同一个文件。

## 性能：40 套 96 秒

i5-13400（10 核 16 线程）/ 8 路并行 / 图案 2048×2048：

| 规模 | 串行估算 | 实测墙钟 | 平均每套 |
|---|---|---|---|
| 10 套 | 2.1 分钟 | **51 s** | 5.1 s（带 html + preview） |
| 40 套 | 8.4 分钟 | **96 s** | 2.4 s（`--no-html`） |

加速来自四层，按贡献排：

1. **OpenSCAD nightly + Manifold 后端**：底模渲染 21.9s → **1.0s**（旧 2021.01 / CGAL）。2025-08-18 起 Manifold 是默认后端，官方只发 nightly（`tools/openscad_nightly/`，224MB，gitignore）。同类实测参考：ModelRift 博客 CGAL 540s → Manifold 27s；Brennen Johnston 的盲文生成器 2021.01 45 分钟 → nightly 1.8s。
2. **进程级并行**：每套一个独立 `stamp_pipeline.py` 子进程，进程间零共享，天然可并行；8 路时单套 10s 变成 2.4s 摊薄。
3. **别每套刷索引**：`PRINT.md` 重建要读全部 STL 的网格（当时 40 件耗 4.1s/次），批量里 `--no-index`，批次结束刷一次。
4. **STL 体检加缓存**：`.cache/probe.json` 按 `mtime+size` 记尺寸/面数/水密/体积，没改过的文件不重复解网格。索引刷新从 4s 掉到 0.4s。

再往下压的余量：单套 10.3s 里约 4.7s 是 Python 导入（numpy/scipy/skimage/trimesh），1s 是 OpenSCAD，其余是轮廓提取与布尔。要再快得让 worker 常驻复用解释器（已否，复杂度不值当——40 套 96s 已在可接受区间）。

## 边界件

| 情况 | 处理 |
|---|---|
| 一套失败 | 该行标失败、留错误尾巴；其余照跑；`batch.json` 里可查 `rc` |
| 想重跑某一套 | 清单里只留那一行，`--limit` 或单独跑 `stamp_pipeline.py --job <批次>/<单号>`（同路径会覆盖） |
| 批次改名 | 直接改清单里的 `item` 重跑；旧目录自己删（脚本不删用户文件） |
| 中途取件打印 | 每套独立落盘，跑完一套就能打；不必等整批（`INDEX.md` 是最后才写，中途看 `print/jobs/<批次>/` 目录即可） |
| 手柄 | **不进批次**：`print/standard/handle_straight.stl` 单独打，一套模具配一个 |
| 多套尺寸外框全同 | 边框 STL 字节完全一致（`2026-11-24_xmas_pair` 实测），`INDEX.md` 会标「同 `A_xmas`，不必重复打」；文件保留，索引仍认配对 |

## 坑

- 批次名里带空格 → 路径要引号，切片器与 PowerShell 都可能截断，别用。
- 同一批次里 `item` 重名 → 后跑的覆盖前面的（`setdefault` 只会留下第一个的 report，STL 被后一个覆盖），清单里保证唯一。
- 一次开 16 路不会更快：单套内部 OpenSCAD Manifold 也吃多核，超过物理核数就是互相抢；8 路在这台机上是最优点附近。
- `--no-html` 只是省掉每套的 3D 预览；**正式批次别关**（Skill 的硬规则是每次出件都要留预览 html）。
