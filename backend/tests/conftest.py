from __future__ import annotations
import os
import sys
import tempfile
import pathlib

import pytest

# 必须在导入 app 之前指定独立库文件。
# 优先放到 tmpfs（/dev/shm）：WAL + BEGIN IMMEDIATE 会产生大量 fsync，
# 在 WSL2 上落到磁盘会让每个夹具用例慢到数秒。语义不受影响。
_TMP = None
if pathlib.Path("/dev/shm").is_dir():
    try:
        _TMP = pathlib.Path(tempfile.mkdtemp(prefix="sortbay-test-", dir="/dev/shm"))
    except OSError:
        _TMP = None
if _TMP is None:
    _TMP = pathlib.Path(tempfile.mkdtemp(prefix="sortbay-test-"))
os.environ["SORTBAY_DB"] = str(_TMP / "sortbay.db")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402


@pytest.fixture()
def client():
    # 每个用例一份全新库
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    config.DB_PATH = _TMP / "sortbay.db"
    seed_if_empty()
    with TestClient(app) as c:
        yield c

    # 每用例结束清掉库，避免 WAL 残留累积到下一用例。
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture()
def ids(client):
    chutes = {c["code"]: c["id"] for c in client.get("/api/口门").json()}
    shift = client.get("/api/班次").json()[0]
    return {"chutes": chutes, "shift": shift}


def _load_scan(client, barcode):
    rows = client.get("/api/扫描").json()
    return next(r for r in rows if r["barcode"] == barcode)


def _create_routed(client, barcode, dest, chute_code, ids):
    """装载并在指定口门完成一次正常路由裁决。"""
    assert client.post("/api/扫描", json={"条码": barcode, "目的地码": dest}).status_code == 200
    scan = _load_scan(client, barcode)
    assert client.post(f"/api/扫描/{scan['id']}/路由").status_code == 200
    scan = _load_scan(client, barcode)
    assert scan["status"] == "已路由"
    assert scan["chute_id"] == ids["chutes"][chute_code]
    return scan
