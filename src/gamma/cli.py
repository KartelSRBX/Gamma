"""`gamma`: the command line of the platform."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from . import analyze as analysis
from . import bench, ch, marts, plan, report, segments, status, store, verdict
from .assign import assign, bucket
from .config import load_catalog
from .migrate import migrate
from .simulate import load, load_scenario, simulate


def _check(_: argparse.Namespace) -> int:
    cat = load_catalog()
    print(f"{len(cat.metrics)} metrics, {len(cat.experiments)} experiments, all consistent")
    print(f"{'experiment':<16}{'layer':<8}{'buckets':<14}{'traffic':<9}{'primary':<20}hypothesis")
    for e in cat.experiments.values():
        buckets = f"{e.buckets[0]}-{e.buckets[1]}"
        print(
            f"{e.key:<16}{e.layer:<8}{buckets:<14}{e.traffic:<9.0%}{e.primary:<20}"
            f"{' '.join(e.hypothesis.split())[:60]}..."
        )
    return 0


def _migrate(_: argparse.Namespace) -> int:
    done = migrate(ch.connect())
    print("applied: " + ", ".join(done) if done else "schema is up to date")
    return 0


def _simulate(args: argparse.Namespace) -> int:
    scenario = load_scenario()
    if args.players:
        scenario.players = args.players
    if args.seed is not None:
        scenario.seed = args.seed
    cat = load_catalog()
    t = time.time()
    data = simulate(scenario, cat)
    print(f"generated in {time.time() - t:.1f}s: {data.sizes}")
    t = time.time()
    load(ch.connect(), data)
    print(f"loaded in {time.time() - t:.1f}s")
    return 0


def _mart(args: argparse.Namespace) -> int:
    cat = load_catalog()
    keys = [args.experiment] if args.experiment else list(cat.experiments)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    client = ch.connect()
    for key in keys:
        t = time.time()
        n = marts.build(client, cat.experiments[key], as_of)
        print(f"{key:<16}{n:>9} players  ({time.time() - t:.1f}s)")
    return 0


def _status(_: argparse.Namespace) -> int:
    client = ch.connect()
    for table, n in status.counts(client).items():
        print(f"{table:<20}{n:>12,}")
    for key in load_catalog().experiments:
        rows = status.arms(client, key)
        if not rows:
            continue
        print(f"\n{key}")
        for variant, n, conv, dep, multi in rows:
            extra = f"  {multi} saw several variants" if multi else ""
            print(
                f"  {variant:<12}{n:>8} players  conversion {conv:7.2%}  "
                f"deposit/player {dep:7.2f}{extra}"
            )
    return 0


def _analyze(args: argparse.Namespace) -> int:
    cat = load_catalog()
    exp = cat.experiments[args.experiment]
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    print(analysis.render(analysis.analyze(ch.connect(), exp, cat.metrics, as_of)))
    return 0


def _report(args: argparse.Namespace) -> int:
    from pathlib import Path

    cat = load_catalog()
    client = ch.connect()
    keys = list(cat.experiments) if args.all else [args.experiment]
    if not keys or keys == [None]:
        raise ValueError("name an experiment or pass --all")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    for key in keys:
        exp = cat.experiments[key]
        a = analysis.analyze(client, exp, cat.metrics, as_of)
        v = verdict.decide(a)
        segs = segments.by_dimension(client, exp, cat.metrics[exp.primary])
        text = report.render(a, v, segs)
        if args.save:
            store.save(client, a, v, segs)
        if args.out:
            out = Path(args.out)
            if args.all:
                out.mkdir(parents=True, exist_ok=True)
                out = out / f"{key}.md"
            out.write_text(text)
            print(f"{key:<16}{v.decision:<14}-> {out}")
        else:
            print(text)
    return 0


def _bench(args: argparse.Namespace) -> int:
    from pathlib import Path

    text = bench.run(args.sizes)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _export(args: argparse.Namespace) -> int:
    import csv
    from pathlib import Path

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    client = ch.connect()
    for name, sql in (
        (
            "experiment_results",
            "SELECT * EXCEPT run_id FROM v_latest_results ORDER BY experiment, role, metric",
        ),
        (
            "mart_user_metrics",
            "SELECT * EXCEPT built_at FROM mart_user_metrics ORDER BY experiment, player_id",
        ),
    ):
        res = client.query(sql)
        with (out / f"{name}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(res.column_names)
            w.writerows(res.result_rows)
        print(f"{name}.csv  {len(res.result_rows):,} rows")
    return 0


def _plan(args: argparse.Namespace) -> int:
    cat = load_catalog()
    print(plan.render(ch.connect(), cat.experiments[args.experiment], cat.metrics, args.mde))
    return 0


def _validate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .stats import validation_report

    text = validation_report.run(ch.connect(), load_catalog(), trials=args.trials)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _assign(args: argparse.Namespace) -> int:
    exp = load_catalog().experiments[args.experiment]
    print(
        f"player {args.player}: layer `{exp.layer}` bucket {bucket(exp.layer, args.player)} -> "
        f"{assign(exp, args.player) or 'not in the experiment'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gamma", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="validate experiments and the metric catalog").set_defaults(
        fn=_check
    )
    sub.add_parser("migrate", help="apply schema migrations").set_defaults(fn=_migrate)
    p = sub.add_parser("simulate", help="generate the synthetic casino and load it")
    p.add_argument("--players", type=int)
    p.add_argument("--seed", type=int)
    p.set_defaults(fn=_simulate)
    p = sub.add_parser("mart", help="build the per-player metrics of experiments")
    p.add_argument("experiment", nargs="?")
    p.add_argument(
        "--as-of", help="analysis date, ISO format; default is the end of the experiment"
    )
    p.set_defaults(fn=_mart)
    sub.add_parser("status", help="row counts and arms").set_defaults(fn=_status)
    p = sub.add_parser("analyze", help="checks and estimates of one experiment")
    p.add_argument("experiment")
    p.add_argument("--as-of", help="analysis date, ISO format; an early date is flagged")
    p.set_defaults(fn=_analyze)
    p = sub.add_parser("report", help="verdict and report of one experiment, or of all")
    p.add_argument("experiment", nargs="?")
    p.add_argument("--all", action="store_true")
    p.add_argument("--as-of", help="analysis date, ISO format")
    p.add_argument("--out", help="file, or a directory with --all")
    p.add_argument("--save", action="store_true", help="also store the run in ClickHouse")
    p.set_defaults(fn=_report)
    p = sub.add_parser("bench", help="scaling benchmarks in a scratch database")
    p.add_argument("--sizes", type=int, nargs="+", default=[50_000, 100_000, 200_000, 400_000])
    p.add_argument("--out", help="write Markdown here, e.g. docs/benchmarks.md")
    p.set_defaults(fn=_bench)
    p = sub.add_parser(
        "export", help="CSV of the latest results and the player marts, for BI tools"
    )
    p.add_argument("--out", default="export")
    p.set_defaults(fn=_export)
    p = sub.add_parser("plan", help="sample size and duration of an experiment")
    p.add_argument("experiment")
    p.add_argument("--mde", type=float, help="relative change to detect; default: the definition's")
    p.set_defaults(fn=_plan)
    p = sub.add_parser("validate", help="check the statistics by simulation (minutes)")
    p.add_argument("--trials", type=int, default=2000)
    p.add_argument("--out", help="write Markdown here, e.g. docs/validation.md")
    p.set_defaults(fn=_validate)
    p = sub.add_parser("assign", help="which variant does a player get")
    p.add_argument("experiment")
    p.add_argument("player", type=int)
    p.set_defaults(fn=_assign)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
