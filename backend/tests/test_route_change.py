from __future__ import annotations
import json
import threading

import pytest


def _load_scan(client, barcode):
    rows = client.get("/api/扫描").json()
    return next(r for r in rows if r["barcode"] == barcode)


def _route(client, barcode, dest, chute_code, ids):
    assert client.post("/api/扫描", json={"条码": barcode, "目的地码": dest}).status_code == 200
    scan = _load_scan(client, barcode)
    r = client.post(f"/api/扫描/{scan['id']}/路由")
    assert r.status_code == 200, r.text
    return _load_scan(client, barcode)


def _receipts(client):
    return client.get("/api/改表回执").json()


# ---------------------------------------------------------------------------
# 1) 有在途已路由件时改表：强制回流、事件、回执、扫描册、总览、审计同刷
# ---------------------------------------------------------------------------
def test_change_route_with_inflight_forces_divert_everywhere(client, ids):
    scan = _route(client, "T-INFLIGHT-1", "110", "A01", ids)
    assert scan["status"] == "已路由" and scan["chute_id"] == ids["chutes"]["A01"]

    resp = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 改表结局：强制回流并留可重放回执
    assert body["是否触发回流"] is True
    assert body["强制回流件数"] == 1
    assert body["路由"]["chute_id"] == ids["chutes"]["A02"]

    # 在途件已被强制回流、脱离旧口门
    s = _load_scan(client, "T-INFLIGHT-1")
    assert s["status"] == "错分回流"
    assert s["chute_id"] is None
    assert s["bag_id"] is None
    assert s["divert_batch_id"] == body["回流批次"][0]["id"]

    # 路由表新映射已生效
    rules = {r["dest_code"]: r for r in client.get("/api/路由表").json()}
    assert rules["110"]["chute_id"] == ids["chutes"]["A02"]

    # 口门在口：旧口门不再挂着这件
    chutes = {c["code"]: c for c in client.get("/api/口门").json()}
    assert chutes["A01"]["在口件数"] == 0

    # 总览：已路由计数不假装仍挂旧口
    ov = client.get("/api/总览").json()
    assert ov["分布"]["已路由"] == 0
    assert ov["分布"]["错分回流"] == 1
    old = next(c for c in ov["口门"] if c["code"] == "A01")
    assert old["在口件数"] == 0

    # 回流批次落库
    batches = client.get("/api/回流批次").json()
    assert any(b["id"] == body["回流批次"][0]["id"] for b in batches)

    # 审计有“改路由并强制回流”
    audit = client.get("/api/审计").json()
    assert any(a["action"] == "改路由并强制回流" for a in audit)

    # 回执可重放：payload 记录旧/新口门与逐件动作
    rec = client.get(f"/api/改表回执/{body['回执编号']}").json()
    p = rec["payload"]
    assert p["old_chute"]["code"] == "A01"
    assert p["new_chute"]["code"] == "A02"
    assert p["forced"][0]["scan_id"] == s["id"]
    assert p["forced"][0]["from_status"] == "已路由"
    assert p["forced"][0]["final_status"] == "错分回流"


# ---------------------------------------------------------------------------
# 2) 无在途件时改表：不建回流批次、回执 forced_count=0、映射生效
# ---------------------------------------------------------------------------
def test_change_route_without_inflight_no_divert(client, ids):
    before = len(client.get("/api/回流批次").json())
    resp = client.post("/api/路由表", json={"目的地码": "210", "口门编号": ids["chutes"]["B01"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["是否触发回流"] is False
    assert body["强制回流件数"] == 0
    assert len(client.get("/api/回流批次").json()) == before
    assert body["回执"]["forced_count"] == 0
    rules = {r["dest_code"]: r for r in client.get("/api/路由表").json()}
    assert rules["210"]["chute_id"] == ids["chutes"]["B01"]


# ---------------------------------------------------------------------------
# 3) 在途件已在袋里（已入袋，未封袋）同样被强制回流、脱离原袋
# ---------------------------------------------------------------------------
def test_inflight_in_unsealed_bag_is_forced_diverted(client, ids):
    _route(client, "T-BAG-1", "110", "A01", ids)
    s = _load_scan(client, "T-BAG-1")
    bag = client.post("/api/封袋/开袋", json={"口门编号": ids["chutes"]["A01"]}).json()
    assert client.post(f"/api/封袋/{bag['id']}/入袋", json={"扫描编号": s["id"]}).status_code == 200
    s = _load_scan(client, "T-BAG-1")
    assert s["status"] == "已入袋" and s["bag_id"] == bag["id"]

    resp = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]})
    assert resp.status_code == 200
    assert resp.json()["强制回流件数"] == 1
    s = _load_scan(client, "T-BAG-1")
    assert s["status"] == "错分回流" and s["bag_id"] is None and s["chute_id"] is None


# ---------------------------------------------------------------------------
# 4) 已封袋件不受改表影响（不在“已路由未封袋”集合内）
# ---------------------------------------------------------------------------
def test_sealed_scan_not_affected_by_route_change(client, ids):
    _route(client, "T-SEALED-1", "110", "A01", ids)
    s = _load_scan(client, "T-SEALED-1")
    bag = client.post("/api/封袋/开袋", json={"口门编号": ids["chutes"]["A01"]}).json()
    client.post(f"/api/封袋/{bag['id']}/入袋", json={"扫描编号": s["id"]})
    assert client.post(f"/api/封袋/{bag['id']}/封口").status_code == 200
    s = _load_scan(client, "T-SEALED-1")
    assert s["status"] == "已封袋"

    resp = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]})
    assert resp.status_code == 200
    assert resp.json()["强制回流件数"] == 0
    assert _load_scan(client, "T-SEALED-1")["status"] == "已封袋"


# ---------------------------------------------------------------------------
# 5) 半截回滚：改表事务中途失败 -> 路由表与在途都保持原样（不双终态）
# ---------------------------------------------------------------------------
def test_half_way_failure_rolls_back_route_and_inflight(client, ids, monkeypatch):
    _route(client, "T-ROLLBACK-1", "110", "A01", ids)
    before_rule = {r["dest_code"]: r for r in client.get("/api/路由表").json()}["110"]
    before_scan = _load_scan(client, "T-ROLLBACK-1")
    before_receipts = len(_receipts(client))
    before_batches = len(client.get("/api/回流批次").json())

    import app.services.routing as routing

    real_now = routing.now_str

    calls = {"n": 0}

    def boom(*a, **k):
        # 在强制回流写完扫描后、落回执前制造异常
        calls["n"] += 1
        if calls["n"] == 2:  # 第二次调用 now_str 已在回流更新之后
            raise RuntimeError("模拟半截故障")
        return real_now(*a, **k)

    monkeypatch.setattr(routing, "now_str", boom)

    with pytest.raises(RuntimeError):
        client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]})

    # 事务回滚：路由表不变、在途不变、无新回执、无新回流批次
    after_rule = {r["dest_code"]: r for r in client.get("/api/路由表").json()}["110"]
    assert after_rule["chute_id"] == before_rule["chute_id"] == ids["chutes"]["A01"]
    after_scan = _load_scan(client, "T-ROLLBACK-1")
    assert after_scan["status"] == before_scan["status"] == "已路由"
    assert after_scan["chute_id"] == before_scan["chute_id"] == ids["chutes"]["A01"]
    assert len(_receipts(client)) == before_receipts
    assert len(client.get("/api/回流批次").json()) == before_batches


# ---------------------------------------------------------------------------
# 6) 改表与封袋对撞：并发下不得出现“既已封袋又被强制回流”的双终态
# ---------------------------------------------------------------------------
def test_concurrent_route_change_and_seal_no_double_terminal(client, ids):
    _route(client, "T-RACE-1", "110", "A01", ids)
    s = _load_scan(client, "T-RACE-1")
    bag = client.post("/api/封袋/开袋", json={"口门编号": ids["chutes"]["A01"]}).json()
    client.post(f"/api/封袋/{bag['id']}/入袋", json={"扫描编号": s["id"]})

    barrier = threading.Barrier(2)
    results = {}

    def do_change():
        barrier.wait()
        results["change"] = client.post(
            "/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]}
        ).status_code

    def do_seal():
        barrier.wait()
        results["seal"] = client.post(f"/api/封袋/{bag['id']}/封口").status_code

    t1 = threading.Thread(target=do_change)
    t2 = threading.Thread(target=do_seal)
    t1.start(); t2.start(); t1.join(); t2.join()

    final = _load_scan(client, "T-RACE-1")
    bag_after = next(b for b in client.get("/api/封袋").json() if b["id"] == bag["id"])

    # 直接查事件表：是否真发生过“改表强制回流”，以它判定走了哪种串行结局。
    import sqlite3
    from app import config
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM route_events WHERE scan_id=? ORDER BY id", (final["id"],)
        ).fetchall()]
    finally:
        conn.close()
    was_forced = "改表强制回流" in actions

    # 两种合法串行结局之一：
    #  A) 改表先：件被强制回流，封袋因袋内已空而失败 -> 终态 错分回流
    #  B) 封袋先：件已封袋，改表不再强制回流 -> 终态 已封袋
    # 非法：件既 已封袋 又 被强制回流（双终态）。
    if was_forced:
        assert final["status"] == "错分回流"
        assert final["chute_id"] is None and final["bag_id"] is None
        assert final["divert_batch_id"] is not None
        assert results["seal"] == 400  # 袋已空，不可封
        assert bag_after["status"] == "集包中"
    else:
        assert final["status"] == "已封袋"
        assert final["chute_id"] == ids["chutes"]["A01"]
        assert final["divert_batch_id"] is None
        assert results["change"] == 200

    # 双终态的显式反断言：绝不允许“已封袋”同时留有强制回流事件。
    assert not (final["status"] == "已封袋" and was_forced)


# ---------------------------------------------------------------------------
# 7) 同一目的地连续改两次：第二次以第一次后的在途集合为准（无残留）
# ---------------------------------------------------------------------------
def test_repeated_change_route_no_stale_inflight(client, ids):
    _route(client, "T-REPEAT-1", "110", "A01", ids)
    r1 = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]}).json()
    assert r1["强制回流件数"] == 1

    # 再路由这同一件（它现在按新映射落到 A02）
    s = _load_scan(client, "T-REPEAT-1")
    assert client.post(f"/api/扫描/{s['id']}/路由").status_code == 200
    s = _load_scan(client, "T-REPEAT-1")
    assert s["status"] == "已路由" and s["chute_id"] == ids["chutes"]["A02"]

    r2 = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["B01"]}).json()
    assert r2["强制回流件数"] == 1
    s = _load_scan(client, "T-REPEAT-1")
    assert s["status"] == "错分回流" and s["chute_id"] is None


# ---------------------------------------------------------------------------
# 8) 强制回流必须逐件留 route_event（不得“强制回流无事件”）
# ---------------------------------------------------------------------------
def test_forced_divert_writes_route_event_per_scan(client, ids):
    _route(client, "T-EVT-1", "110", "A01", ids)
    _route(client, "T-EVT-2", "110", "A01", ids)
    resp = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]}).json()
    assert resp["强制回流件数"] == 2

    # 通过回执 payload + 数据库直查事件，确认每件都有“改表强制回流”
    import sqlite3
    from app import config
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        for f in resp["受影响件"]:
            evs = conn.execute(
                "SELECT action, chute_id FROM route_events WHERE scan_id=? ORDER BY id",
                (f["scan_id"],),
            ).fetchall()
            actions = [e["action"] for e in evs]
            assert "路由落入" in actions
            assert "改表强制回流" in actions
            # 回流事件记录的是原口门，可追溯
            divert_ev = next(e for e in evs if e["action"] == "改表强制回流")
            assert divert_ev["chute_id"] == ids["chutes"]["A01"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 9) 设置开启“回流自动再路由”：臂内同笔再裁决，终态与回执自洽
# ---------------------------------------------------------------------------
def test_auto_reroute_setting_applies_in_same_transaction(client, ids):
    assert client.post("/api/设置", json={"键": "回流自动再路由", "值": "是"}).status_code == 200
    _route(client, "T-AUTO-1", "110", "A01", ids)
    resp = client.post("/api/路由表", json={"目的地码": "110", "口门编号": ids["chutes"]["A02"]}).json()
    assert resp["强制回流件数"] == 1

    s = _load_scan(client, "T-AUTO-1")
    # 臂内再裁决：终态为新映射下的已路由，而不是空口门的错分回流
    assert s["status"] == "已路由"
    assert s["chute_id"] == ids["chutes"]["A02"]

    f = resp["受影响件"][0]
    assert f["from_status"] == "已路由"
    assert f["final_status"] == "已路由"
    assert f["final_chute_id"] == ids["chutes"]["A02"]

    # 回执如实记录 auto_reroute
    assert resp["回执"]["payload"]["auto_reroute"] is True

    # 口门在口：新口门挂上这件，旧口门清零
    ch = {c["code"]: c for c in client.get("/api/口门").json()}
    assert ch["A02"]["在口件数"] == 1
    assert ch["A01"]["在口件数"] == 0
