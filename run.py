"""The one command: python run.py <messages.txt>   (paste new messages at the end, run again)."""
import sys

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python run.py <messages.txt>")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    from planner.engine import run
    run(sys.argv[1])
