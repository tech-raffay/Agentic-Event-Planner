"""Per-file state (state/<hash of path>.json, gitignored)."""
import hashlib
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "state"


def path_for(p):
    return DIR / (hashlib.sha1(str(Path(p).resolve()).lower().encode()).hexdigest()[:12] + ".json")


def fresh(p):
    return dict(path=str(Path(p).resolve()), text="", msgs=[], facts=[], trace=[], runs=[], calls=0, tokens=0,
                order=0, maxdate="", plan=None, checks=None, infeasible=None)


def load(p):
    f = path_for(p)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(st):
    DIR.mkdir(exist_ok=True)
    path_for(st["path"]).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
