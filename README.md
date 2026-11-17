# 智能运营决策分析平台

面向用户行为序列分析、RFM分层、流失预警、智能推荐、归因建模、活动效果评估与实时运营决策的数据分析工程平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   ├── app/permissions.py    智能推荐权限归属（角色码 → 读写边界）
│   ├── app/store.py          内存数据仓库与示例数据
│   └── test_precheck_flows.py 发布预检回归测试
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 行为序列 | `sequence` | 序列模式 | 模式编号、用户分群、事件序列 |
| RFM分层 | `rfm` | 分层规则 | 规则编号、最近消费天界、消费频次界 |
| 流失预警 | `churn` | 预警模型 | 模型编号、模型名称、特征变量 |
| 智能推荐 | `recommend` | 推荐策略 | 策略编号、推荐场景、召回算法 |
| 归因建模 | `attrmodel` | 归因模型 | 模型编号、模型名称、归因逻辑 |
| 活动评估 | `activity` | 活动方案 | 方案编号、活动名称、活动类型 |
| 实时决策 | `realtime` | 决策规则 | 规则编号、触发事件、决策条件 |
| 预算分配 | `budget` | 预算方案 | 方案编号、预算总额、渠道分配比例 |
| LTV估算 | `lifetime` | LTV模型 | 模型编号、模型名称、估算方法 |
| 实验变体 | `abvariant` | 变体方案 | 变体编号、关联实验、变体名称 |
| 运营看板 | `dashboard` | 看板视图 | 视图编号、视图名称、指标组合 |
| 评分卡 | `scorecard` | 评分卡 | 评分编号、评分对象、特征变量组 |
| 聚类分群 | `cluster` | 聚类任务 | 任务编号、聚类算法、特征维度 |
| 对比分析 | `comparison` | 对比组 | 对比编号、对比名称、实验组筛选 |
| 数据漂移 | `datadrift` | 漂移检测 | 检测编号、监控数据集、基线版本 |
| 推送计划 | `pushplan` | 推送方案 | 方案编号、推送内容、目标人群 |
| 指标归因 | `metricdrill` | 归因分析 | 分析编号、目标指标、波动方向 |
| 策略库 | `tacticlib` | 运营策略 | 策略编号、策略名称、策略类型 |
| 发布预检 | `precheck` | 预检明细数据集 | 数据集编号、推荐策略编号、场景命中结果 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 推荐策略发布预检

新增推荐能力上线前必须走独立预检，不允许在推荐策略上直接上线。

1. 从智能推荐动作触达：`POST /api/recommend/{id}/precheck`（页面：智能推荐 → 发布预检）。
2. 预检读取该策略的 `推荐场景` 配置与策略库中 `status=已发布` 且 `适用场景` 相同的记录，
   按 `优先级升序 → 更早发布 → 策略编号` 裁决出**唯一**场景命中结果；同一场景命中两项
   同优先级策略时，结果里会同时给出改按更高评分裁决的差异，方便复核。
3. 预检结论分三种：`候选`（策略仍在草稿/评审中）、`通过`、`未通过`（场景归属、复用声明、
   多样性权重 0~1 等任一不满足）。只有 `通过` 才 `是否进入上线列表=true`。
4. `POST /api/precheck/{id}/launch` 在同一次写入里完成：预检数据集闭环、推荐策略转 `已上线`、
   策略库 `使用次数+1` 与最近使用批次回写。同一场景只允许一个已上线来源，并发提交也只放行一个。
5. 重复登记同一策略的预检只会收敛到同一个数据集（原业务批次保留），不会新增记录。
6. 复用次数只随**实际推荐动作**增长：上线计 1 次，之后每次 `POST /api/precheck/execute`
   才继续累加；预检重算不会增加次数。
7. 数据集登记到策略库待处理明细：`GET /api/tacticlib/pending`（页面：策略库 → 运营策略库待处理明细）。
   批次追溯用 `GET /api/precheck/batches` 或 `?batch=` 过滤。

`TACT-0003` 是契约验证样本（新品推荐场景，与 TACT-0004 同优先级、发布更早），
`RECO-0002` 是配套的推荐策略样本。

### 权限归属

请求头 `X-Role` 取 `admin` / `ops_lead` / `auditor` / `analyst`，缺省 `admin`。
只读角色可以看预检列表和策略库待处理明细（共享字段收敛为核对所需字段），
任何写动作返回 403。前端顶栏可切换角色，只读角色下写按钮不可点。

### 回归测试

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python test_precheck_flows.py
```

领域：数据工程
子方向：数据分析与数据应用
