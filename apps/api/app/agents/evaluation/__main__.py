"""Run evaluations: `python -m app.agents.evaluation --models baseline,qwen3-4b --split test`."""

import argparse
import json

from app.agents.evaluation.gate_eval import write_gates_report
from app.agents.evaluation.report import write_report
from app.agents.evaluation.runner import ALL_TASKS, BASELINE, run
from app.agents.llm import ModelRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", default=BASELINE, help="Comma-separated model keys and/or 'baseline'"
    )
    parser.add_argument("--tasks", default=",".join(ALL_TASKS))
    parser.add_argument("--split", default="test", choices=["train", "test"])
    parser.add_argument("--limit", type=int, default=None, help="Items per task (smoke runs)")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--status", action="store_true", help="Show which models can run, then exit"
    )
    parser.add_argument("--report", action="store_true", help="Write REPORT.md from past runs")
    parser.add_argument("--gates", action="store_true", help="Write GATES.md; --models runs live")
    args = parser.parse_args()

    if args.report:
        print(write_report(args.split))
        return

    if args.gates:
        models = [m.strip() for m in args.models.split(",") if m.strip() and m.strip() != BASELINE]
        print(write_gates_report(args.split, models))
        return

    if args.status:
        for s in ModelRegistry().status():
            print(f"{s.key:14} {'available' if s.available else 'UNAVAILABLE: ' + str(s.reason)}")
        return

    summary = run(
        [m.strip() for m in args.models.split(",") if m.strip()],
        [t.strip() for t in args.tasks.split(",") if t.strip()],
        split=args.split,
        limit=args.limit,
        run_id=args.run_id,
    )
    print(json.dumps({"run_id": summary["run_id"], "duration_s": summary["duration_s"]}))


if __name__ == "__main__":
    main()
