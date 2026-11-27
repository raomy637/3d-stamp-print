# 目录与清单规范

数据根默认 `D:\opencode\3D-stamp-print\work`，不纳入 git。所有路径以该根为基准。

## 目录树

```
work/
├─ _inbox/<批次名>/                    用户丢图；只读
├─ 打样/
│  └─ <项目名>/
│     ├─ 原始图/                       用户原图，复制进来，不移动
│     ├─ 打印模型/                     只放可打印 STL
│     ├─ _记录/                        预览、validation、job、report
│     └─ manifest.json
├─ 订单/
│  └─ <YYYYMMDD>/
│     ├─ INDEX.md                      该日期下本批次总表
│     ├─ batch.json                    机器读：批次参数、耗时、结果
│     └─ <订单号>/
│        ├─ 原始图/
│        ├─ 打印模型/
│        ├─ _记录/
│        └─ manifest.json
├─ _实验/                              探针、对比、print/test
└─ _归档/                              历史件、_archive、无法归类件
```

- 订单单款式：`订单/<日期>/<订单号>/{原始图,打印模型,_记录}`。
- 订单多款式：`订单/<日期>/<订单号>/<款式>/{原始图,打印模型,_记录}`；`manifest.json` 放款式目录。
- 打样单款式：`打样/<项目名>/{原始图,打印模型,_记录}`。
- 打样多款式：`原始图/` 平铺；`打印模型/<款式>/`、`_记录/<款式>/`；避免多套 `base.stl` 重名。
- `打印模型/` 只放 `base.stl`、`cutter.stl`、`plate.stl`（合盘）或 `outline.stl`、`lid.stl`；`positive_reference.stl`、`detail_coupon.stl` 放 `_记录/`。
- 标准件 `print/standard`、`out/handles` 留原位，不进 work。

## 命名

| 对象 | 规则 | 例子 |
|---|---|---|
| 批次名 | ASCII，无空格 | `20261126_pets` |
| 打样项目名 | 可中文；空格换 `_` | `天使狗`、`angel_dog` |
| 订单号 | ASCII；只保留字母数字 `_-.` | `ORD123`、`ETSY-10086` |
| 款式名 | ASCII；默认取图片 stem | `A_snowman` |
| 日期目录 | `YYYYMMDD`，取开工确认当天 | `20261126` |

- 批次名、订单号、款式名禁止空格与中文，避免切片器和命令行引号问题。
- 同名目标自动 `_v2`、`_v3`；只对叶子业务目录（项目/订单/款式）加版本，不分裂上层日期。
- 不覆盖、不删除；需要替换时新建版本并在 manifest 记 `supersedes`。

## manifest 字段

CSV 输入（UTF-8）最少两列：

```
item,input
A_snowman,inputs/snowman.png
```

订单批次额外需要订单号：

```
order,item,input,size,relief,mode,text,press,quantity
ORD123,angel_dog,path/angel_dog.png,95,4,sink,yes,flip,1
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `order` | 订单必填 | 订单号；打样忽略 |
| `item` | 是 | 款式/图案 slug，批次内唯一 |
| `input` | 是 | 相对收件箱或绝对路径 |
| `size` | 否 | 成品最长边 mm；印章默认 85（脚本上限 300，4 英寸 = 101.6），宠物浮雕默认 95 且 ≤100 |
| `relief` | 否 | 凸起高度/槽深 mm；印章默认 2.5（凹模要 2.5 时底板设 4.0），宠物默认 4 |
| `mode` | 否 | `raise`（凸模）/ `sink`（凹模）；宠物忽略 |
| `text` | 否 | `yes`/`no`；决定默认镜像 |
| `press` | 否 | `flip`（翻压）/ `direct`（正压）；印章必填 |
| `quantity` | 否 | 打印份数，默认 1；只记清单，不复制 STL |

JSON `manifest.json` 至少包含：

```json
{
  "kind": "order",
  "batch": "20261126_pets",
  "project": null,
  "order": "ORD123",
  "date": "20261126",
  "items": [
    {
      "item": "angel_dog",
      "source": "…/input.png",
      "size": 95,
      "relief": 4,
      "mode": "sink",
      "text": false,
      "press": "direct",
      "mirror": false,
      "quantity": 1,
      "models": [],
      "records": []
    }
  ]
}
```

## 收件箱与归类

- 默认 `<root>\_inbox\<批次名>\`；可附 `manifest.csv`，没有清单时按图片 stem 生成 item。
- 归类顺序：先判打样/订单，再判项目名或日期+订单号，最后建款式。
- 打样转订单：复制 `打印模型/` 与 `_记录/` 到订单目录，`manifest.json` 记 `source_sample`；不重新生成。
- `_inbox` 只读；任何情况下不移动、不改名、不删除用户原图。

## 历史迁移映射

| 来源 | 目标 | 说明 |
|---|---|---|
| `out/<正式job>`、`out/<批次>/<单号>` | `_归档/历史件/out/...` | 无法确认打样/订单属性，统一归档 |
| `out/_archive` | `_归档/历史件/out/_archive/...` | 保留原相对路径 |
| `out/_cmp`、`_diag*`、`_edge*`、`_e_*`、`_es_*`、`_opt*`、`_ref*`、`_prep`、`_sec*`、`_t*`、`_v_*`、`_void*`、`_user*`、`_pat*`、`_mask*`、`_ink*` | `_实验/out/...` | 探针与对比件 |
| `print/jobs/**` | `_归档/历史件/print/jobs/...` | 历史可打印件 |
| `print/test/**`、`print/_tmp/**` | `_实验/print/...` | 实验件 |
| `print/standard/**`、`out/handles/**` | 留原地 | 长期标准件，不迁 |
| `inputs/**` | 留原地 | 源图暂存；历史 job 的 `source.png` 随 `out/...` 归档 |

迁移只复制、不删除；目标已存在则跳过并列入冲突表，等人工决定 `_v2` 或合并。
