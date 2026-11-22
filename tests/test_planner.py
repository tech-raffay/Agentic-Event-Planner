"""Offline regression: hand-made reader output (tests/fixtures.json) -> resolver -> planner -> checks."""
import copy
import json
from pathlib import Path
import pytest
from planner import engine, state, reader
from planner.trace import Trace

HERE = Path(__file__).parent
FX = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
PACK = (HERE / "sample_pack.txt").read_text(encoding="utf-8")
C = engine.config()


def norm(msgs):
    out = []
    for m in msgs:
        good, bad = reader._facts(m["facts"])
        out.append(dict(frm=m["from"], role=m["role"], date=m["date"], facts=good, dropped=bad, other=[], note=""))
    return out


def feed(st, msgs, text, mode):
    tr = Trace(st, mode, "test", echo=False)
    engine.apply(st, norm(msgs), text, tr, C, None, mode)
    return st


def base():
    return feed(state.fresh("x.txt"), FX["base_reader"]["msgs"], PACK, "full")


def check(st, exp):
    h = engine.headline(st["plan"])
    for k in ("headcount", "judges", "venue", "food", "total", "remaining", "teams"):
        if k in exp:
            assert h[k] == exp[k], (k, h[k], exp[k])
    if exp.get("infeasible"):
        assert st["infeasible"]
    else:
        assert all(c["ok"] for c in st["checks"]), [c for c in st["checks"] if not c["ok"]]


def test_sample_pack():
    st = base()
    e = FX["base_expect"]
    check(st, e)
    assert [m["status"] for m in st["msgs"]] == e["status"]
    blocks = [(b["time"], b["min"]) for b in st["plan"]["schedule"]["blocks"]]
    assert blocks[2] == ("12:15-12:30", 15) and blocks[4] == ("13:00-13:45", 45)


@pytest.mark.parametrize("u", FX["updates"], ids=[u["name"] for u in FX["updates"]])
def test_update(u):
    st = feed(base(), [u["msg"]], u["text"], "update")
    assert st["msgs"][-1]["status"] == u["expect"]["status"], st["msgs"][-1]["reason"]
    check(st, u["expect"])


def test_numbers():
    n = reader.numbers("dedh lakh, pachas hazaar, 50k, Rs. 1.2 lac, 4 hours, Rs 650,000")
    assert {150000, 50000, 120000, 240, 650000} <= n
