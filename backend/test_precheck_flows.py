"""发布预检回归测试：用 TestClient 直接驱动服务，不依赖外部进程。"""
from __future__ import annotations

import copy
import sys

from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store


def fresh() -> TestClient:
    """每个用例把内存表重置回种子数据，模块引用保持不变。"""
    store._tables = {name: [copy.deepcopy(row) for row in rows] for name, rows in SEED_ROWS.items()}
    return TestClient(app)


FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def run() -> int:
    c = fresh()

    print("A. 评审中的策略只进入候选")
    r = c.post("/api/recommend/2/precheck", json={}).json()
    check("结论=候选", r["entry"]["预检结论"] == "候选", r["entry"]["预检结论"])
    check("不进入上线列表", r["entry"]["是否进入上线列表"] is False)
    launchable = c.get("/api/precheck/launchable").json()["items"]
    check("上线列表为空", launchable == [], str([x["推荐策略编号"] for x in launchable]))

    print("B. 上线策略生成唯一场景命中结果（TACT-0003 契约样本）")
    c.post("/api/recommend/2/actions", json={"action": "评审通过策略"})
    r = c.post("/api/recommend/2/precheck", json={}).json()
    e = r["entry"]
    check("结论=通过", e["预检结论"] == "通过")
    check("唯一命中 TACT-0003", e["命中策略编号"] == "TACT-0003", e["命中策略编号"])
    check("同优先级候选存在", e["同优先级候选数"] == 2, e["同优先级候选"])
    check(
        "按评分裁决会换人",
        "TACT-0004" in e["备选裁决差异"],
        e["备选裁决差异"],
    )
    prec_id = e["id"]
    r = c.post(f"/api/precheck/{prec_id}/launch", json={}).json()
    check("上线成功", r["ok"] is True, r["message"])
    strategy = c.get("/api/recommend/2").json()
    check("推荐策略已上线", strategy["status"] == "已上线")
    check("复用策略写回 TACT-0003", strategy["复用策略编号"] == "TACT-0003")
    tactic = next(x for x in c.get("/api/tacticlib?size=50").json()["items"] if x["策略编号"] == "TACT-0003")
    check("TACT-0003 复用次数 +1", tactic["使用次数"] == 3, str(tactic["使用次数"]))
    check("数据集已闭环", r["entry"]["闭环状态"] == "已闭环")

    print("C. 重复登记只收敛为单个数据集")
    r = c.post("/api/recommend/2/precheck", json={}).json()
    check("重复登记不新增", r["message"].startswith("推荐策略已上线") or "不新增" in r["message"], r["message"])
    total = c.get("/api/precheck?size=100").json()["total"]
    check("数据集只 1 条", total == 1, str(total))

    print("D. 同一场景两个策略只允许一个动作来源")
    c.post("/api/recommend/4/precheck", json={})
    c.post("/api/recommend/5/precheck", json={})
    ids = {x["推荐策略编号"]: x["id"] for x in c.get("/api/precheck?size=50").json()["items"]}
    r1 = c.post(f"/api/precheck/{ids['RECO-0004']}/launch", json={}).json()
    check("先提交者上线", r1["ok"] is True, r1["message"])
    r2 = c.post(f"/api/precheck/{ids['RECO-0005']}/launch", json={}).json()
    check("后提交者被拦", r2["ok"] is False, r2["message"])
    check("后提交数据集结论=未通过", r2["entry"]["预检结论"] == "未通过")
    online = [x for x in c.get("/api/recommend?size=50").json()["items"] if x["推荐场景"] == "流失挽回" and x["status"] == "已上线"]
    check("同场景只有一个上线来源", len(online) == 1, str([x["策略编号"] for x in online]))
    usage_before = next(x for x in c.get("/api/tacticlib?size=50").json()["items"] if x["策略编号"] == "TACT-0006")["使用次数"]
    check("落选策略复用次数不变", usage_before == 0, str(usage_before))

    print("E. 复用次数只随实际推荐动作增长")
    strategy = c.get("/api/recommend/4").json()
    usage = next(x for x in c.get("/api/tacticlib?size=50").json()["items"] if x["策略编号"] == "TACT-0005")["使用次数"]
    check("上线时已计一次", usage == 1, str(usage))
    r = c.post("/api/precheck/execute", json={"strategy_id": 4}).json()
    usage = next(x for x in c.get("/api/tacticlib?size=50").json()["items"] if x["策略编号"] == "TACT-0005")["使用次数"]
    check("执行推荐后 +1", usage == 2, str(usage))
    r = c.post("/api/precheck/execute", json={"strategy_id": 5}).json()
    check("未上线策略不能执行", r["ok"] is False, r["message"])

    print("F. 多样性权重越界")
    r = c.post("/api/recommend/8/precheck", json={}).json()
    check("权重 1.4 未通过", r["ok"] is False and r["entry"]["预检结论"] == "未通过", r["entry"]["预检说明"])

    print("G. 批次追溯与待处理明细")
    rows = c.get("/api/precheck?size=50").json()["items"]
    check("每条都有业务批次", all(x["业务批次"] for x in rows))
    batch = rows[0]["业务批次"]
    found = c.get(f"/api/precheck?batch={batch}").json()["items"]
    check("按批次可追溯", len(found) >= 1, batch)
    pending = c.get("/api/tacticlib/pending").json()["items"]
    check("策略库待处理明细承接数据集", len(pending) == len(rows))
    check(
        "同一记录可核对三项",
        all(k in pending[0] for k in ("场景命中结果", "策略复用次数", "预计推荐结果")),
    )

    print("H. 权限边界")
    for path, body in [
        ("/api/recommend/4/precheck", {}),
        ("/api/tacticlib/1/actions", {"action": "发布策略"}),
    ]:
        resp = c.post(path, json=body, headers={"X-Role": "auditor"})
        check(f"只读角色写 {path} 被拦", resp.status_code == 403, str(resp.status_code))
    readonly_pending = c.get("/api/tacticlib/pending", headers={"X-Role": "auditor"}).json()["items"]
    check("只读共享字段受限", len(readonly_pending[0]) < len(pending[0]), str(len(readonly_pending[0])))

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项: {FAILURES}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(run())
