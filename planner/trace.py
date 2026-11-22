"""Trace: numbered model calls + [code] events. One source for terminal, trace.txt, trace.jsonl and UI."""
from datetime import datetime

try:
    from rich.console import Console
    _C = Console(highlight=False)
    _out = lambda s, style=None: _C.print(s, style=style, markup=False, soft_wrap=True)
except ImportError:
    _out = lambda s, style=None: print(s)


def line(e, short=False):
    cut = lambda s: s if not short or len(s or "") < 300 else s[:300] + f" ... [{len(s)} chars; full in out/trace.txt]"
    if e["t"] == "call":
        u = e.get("usage")
        tok = (f"prompt {u['prompt']} · completion {u['completion']} · total {u['total']}   (reported by API)"
               if u else "not reported")
        head = f"[#{e['n']}] model={e['model']}  area={e['area']}  ({e.get('secs', 0)} s)"
        if e.get("error"):
            return f"{head}  FAILED: {e['error']}\n  INPUT : {cut(e['input'])}\n  TOKENS: not reported (no response)"
        return f"{head}\n  INPUT : {cut(e['input'])}\n  OUTPUT: {cut(e['output'])}\n  TOKENS: {tok}"
    return f"[code] {e['text']}" if e["t"] == "code" else e["text"]


class Trace:
    def __init__(self, st, mode, info, echo=True):
        self.st, self.echo, self.calls, self.tokens = st, echo, 0, 0
        self.run = len(st["runs"]) + 1
        self.ev(dict(t="head", text=f"=== RUN {self.run} · {mode} · {info} · {datetime.now():%d %b %H:%M:%S} ==="))

    def ev(self, e):
        from .guardian import redact                       # Guardian E: no secrets in traces
        for k in ("input", "output", "error", "text"):
            if isinstance(e.get(k), str):
                e[k] = redact(e[k])
        e["run"] = self.run
        self.st["trace"].append(e)
        if self.echo:
            _out(line(e, short=True), {"call": "bold cyan", "head": "bold", "foot": "bold"}.get(e["t"], "dim"))

    def call(self, n, model, area, inp, out, usage, err=None, secs=0):
        if usage:
            p, c = usage.get("prompt"), usage.get("completion")
            t = usage.get("total") or (p + c if p is not None and c is not None else None)
            usage = dict(prompt=p, completion=c, total=t)
            if t:
                self.tokens += t
                self.st["tokens"] += t
        self.calls += 1
        self.ev(dict(t="call", n=n, model=model, area=area, input=inp, output=out, usage=usage,
                     error=err, secs=round(secs, 1)))

    def code(self, text):
        self.ev(dict(t="code", text=text))

    def end(self):
        self.ev(dict(t="foot", text=f"--- run tokens {self.tokens:,} · calls {self.calls} · cumulative tokens "
                                    f"{self.st['tokens']:,} · cumulative calls {self.st['calls']} ---"))
