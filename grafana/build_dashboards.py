"""Dashboards as code: builds grafana/dashboards/*.json.

Run ``python grafana/build_dashboards.py`` after changing a panel. Grafana picks the JSON up
through file provisioning; nobody edits dashboards by hand in the UI. CI fails if the committed
JSON differs from what this script produces.

The dashboard reads conclusions (experiment_runs, experiment_results, written by
`gamma report --save`) and monitors the enrollment from the mart. It does not recompute any
statistics: one place decides what the numbers are.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
CH = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}
TIMESERIES, TABLE = 0, 1

GREEN, RED, ORANGE, BLUE = "#73BF69", "#F2495C", "#FF9830", "#5794F2"
LINE = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}
TS_OPTS = {
    "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
    "tooltip": {"mode": "multi", "sort": "desc"},
}
STAT = {
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    "colorMode": "background",
    "graphMode": "none",
    "textMode": "value",
    "justifyMode": "center",
}

DECISION_COLORS = {
    "SHIP": GREEN,
    "DO_NOT_SHIP": RED,
    "INVALID": RED,
    "WAIT": ORANGE,
    "HOLD": ORANGE,
    "INCONCLUSIVE": ORANGE,
    "NO_EFFECT": BLUE,
}


def ch(sql: str, fmt: int = TABLE, ref: str = "A") -> dict:
    return {
        "datasource": CH,
        "editorType": "sql",
        "format": fmt,
        "queryType": "timeseries" if fmt == TIMESERIES else "table",
        "rawSql": " ".join(sql.split()),
        "refId": ref,
    }


class Board:
    def __init__(self, uid: str, title: str):
        self.uid, self.title = uid, title
        self.panels: list[dict] = []
        self._id = 1
        self._x = self._y = self._row_h = 0

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._x, self._y, self._row_h = 0, self._y + self._row_h, 0
        pos = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._row_h = max(self._row_h, h)
        return pos

    def row(self, title: str) -> None:
        if self._x:
            self._x, self._y = 0, self._y + self._row_h
        self.panels.append(
            {
                "id": self._id,
                "type": "row",
                "title": title,
                "collapsed": False,
                "gridPos": {"x": 0, "y": self._y, "w": 24, "h": 1},
                "panels": [],
            }
        )
        self._id += 1
        self._y += 1
        self._row_h = 0

    def add(
        self,
        kind: str,
        title: str,
        targets: list[dict],
        w: int,
        h: int,
        *,
        description: str = "",
        unit: str | None = None,
        decimals: int | None = None,
        options: dict | None = None,
        custom: dict | None = None,
        mappings: list | None = None,
        overrides: list | None = None,
        thresholds: list | None = None,
        color_mode: str | None = None,
        minv: float | None = None,
        maxv: float | None = None,
    ) -> None:
        defaults: dict = {"custom": custom or {}}
        if unit:
            defaults["unit"] = unit
        if decimals is not None:
            defaults["decimals"] = decimals
        if mappings:
            defaults["mappings"] = mappings
        if thresholds:
            defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
        defaults["color"] = {"mode": color_mode or "palette-classic"}
        if color_mode == "fixed":
            defaults["color"]["fixedColor"] = BLUE
        if minv is not None:
            defaults["min"] = minv
        if maxv is not None:
            defaults["max"] = maxv
        self.panels.append(
            {
                "id": self._id,
                "type": kind,
                "title": title,
                "description": description,
                "datasource": CH,
                "gridPos": self._place(w, h),
                "targets": targets,
                "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
                "options": options or {},
            }
        )
        self._id += 1

    def json(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.title,
            "tags": ["gamma"],
            "timezone": "utc",
            "schemaVersion": 39,
            "version": 1,
            "editable": True,
            "graphTooltip": 1,
            "refresh": "",
            # The simulated experiments run in September 2026; with real data this would be
            # "now-30d".
            "time": {"from": "2026-08-31T00:00:00.000Z", "to": "2026-09-23T00:00:00.000Z"},
            "panels": self.panels,
            "templating": {
                "list": [
                    {
                        "name": "experiment",
                        "label": "Experiment",
                        "type": "query",
                        "datasource": CH,
                        "definition": "SELECT DISTINCT experiment FROM gamma.experiment_runs ORDER BY experiment",
                        "query": "SELECT DISTINCT experiment FROM gamma.experiment_runs ORDER BY experiment",
                        "refresh": 1,
                        "sort": 1,
                        "current": {"text": "welcome_bonus", "value": "welcome_bonus"},
                    }
                ]
            },
            "annotations": {"list": []},
            "links": [],
        }


def experiment() -> Board:
    b = Board("gamma-experiment", "Gamma · Experiment")
    E = "'$experiment'"

    b.row("Decision")
    b.add(
        "stat",
        "Decision",
        [ch(f"SELECT decision FROM gamma.v_latest_run WHERE experiment = {E}")],
        6,
        5,
        description="The verdict of the latest run of `gamma report --save`. Rules: gamma/verdict.py.",
        options={**STAT, "reduceOptions": {**STAT["reduceOptions"], "fields": "/^decision$/"}},
        color_mode="fixed",
        mappings=[
            {
                "type": "value",
                "options": {
                    k: {"color": c, "text": k.replace("_", " ")} for k, c in DECISION_COLORS.items()
                },
            }
        ],
    )
    b.add(
        "stat",
        "Why",
        [ch(f"SELECT headline FROM gamma.v_latest_run WHERE experiment = {E}")],
        10,
        5,
        options={
            **STAT,
            "colorMode": "none",
            "reduceOptions": {**STAT["reduceOptions"], "fields": "/^headline$/"},
        },
        color_mode="fixed",
        description="One sentence from the verdict; the report has the reasons.",
    )
    b.add(
        "stat",
        "Players analysed",
        [
            ch(
                f"""SELECT n_control + n_treatment FROM gamma.v_latest_results
                WHERE experiment = {E} AND role = 'primary'"""
            )
        ],
        4,
        5,
        options={**STAT, "colorMode": "value"},
        thresholds=[{"color": BLUE, "value": None}],
        color_mode="thresholds",
    )
    b.add(
        "stat",
        "Sample ratio check, p",
        [ch(f"SELECT srm_p FROM gamma.v_latest_run WHERE experiment = {E}")],
        4,
        5,
        options={**STAT, "colorMode": "value"},
        decimals=4,
        thresholds=[
            {"color": RED, "value": None},
            {"color": GREEN, "value": 0.001},
        ],
        color_mode="thresholds",
        description="Chi-square p of the arm sizes against the planned split. Below 0.001 the "
        "experiment is invalid whatever else it shows.",
    )

    b.row("Is the enrollment healthy?")
    b.add(
        "timeseries",
        "Treatment share of players enrolled so far",
        [
            ch(
                f"""SELECT day AS time, sum(treated) OVER (ORDER BY day) / sum(total) OVER (ORDER BY day) AS share
                FROM (
                    SELECT toStartOfDay(exposed_at) AS day, countIf(variant != 'control') AS treated,
                           count() AS total
                    FROM gamma.mart_user_metrics WHERE experiment = {E} GROUP BY day
                )
                ORDER BY day""",
                TIMESERIES,
            )
        ],
        12,
        8,
        unit="percentunit",
        minv=0.4,
        maxv=0.6,
        custom=LINE,
        options=TS_OPTS,
        description="Cumulative over the enrollment. It should sit on the planned split from the "
        "first day; a drift is a sampling or logging bug.",
    )
    b.add(
        "timeseries",
        "Players enrolled per day",
        [
            ch(
                f"""SELECT toStartOfDay(exposed_at) AS time, variant, count() AS players
                FROM gamma.mart_user_metrics WHERE experiment = {E}
                GROUP BY time, variant ORDER BY time""",
                TIMESERIES,
            )
        ],
        12,
        8,
        custom={**LINE, "fillOpacity": 25},
        options=TS_OPTS,
        description="Players by day of first exposure and arm. Falls fast: most players visit in "
        "the first days.",
    )

    b.row("Results of the latest run (change vs control, 95% interval)")
    b.add(
        "table",
        "Metrics",
        [
            ch(
                f"""SELECT role AS Role, metric AS Metric, mean_control AS Control, mean_treatment AS Treatment,
                    rel_diff AS Change, rel_ci_low AS Low, rel_ci_high AS High,
                    if(p < 0.0001, '<0.0001', toString(round(p, 4))) AS p,
                    if(p_adjusted IS NULL, '', if(p_adjusted < 0.0001, '<0.0001', toString(round(p_adjusted, 4)))) AS `Holm p`,
                    guardrail AS Guardrail
                FROM gamma.v_latest_results
                WHERE experiment = {E} AND dimension = 'all'
                ORDER BY multiIf(role = 'primary', 0, role = 'secondary', 1, 2), metric"""
            )
        ],
        24,
        8,
        options={"showHeader": True},
        overrides=[
            {
                "matcher": {"id": "byRegexp", "options": "Change|Low|High"},
                "properties": [
                    {"id": "unit", "value": "percentunit"},
                    {"id": "decimals", "value": 1},
                ],
            },
            {
                "matcher": {"id": "byRegexp", "options": "Control|Treatment"},
                "properties": [{"id": "decimals", "value": 3}],
            },
        ],
        description="Metrics with CUPED are shown as covariate-adjusted means. Guardrail 'inconclusive' "
        "is not a pass.",
    )
    b.add(
        "barchart",
        "Change by metric",
        [
            ch(
                f"""SELECT metric, rel_diff AS change FROM gamma.v_latest_results
                WHERE experiment = {E} AND dimension = 'all' AND metric NOT IN ('ggr_per_player')
                ORDER BY metric"""
            )
        ],
        24,
        7,
        unit="percentunit",
        decimals=1,
        color_mode="fixed",
        options={"legend": {"showLegend": False}, "xTickLabelRotation": 0, "showValue": "auto"},
        description="Point estimates only (intervals are in the table). GGR is left out: its interval "
        "is tens of percent wide, which flattens everything else.",
    )

    b.row("Where is the effect? (exploratory)")
    b.add(
        "table",
        "Primary metric by segment",
        [
            ch(
                f"""SELECT dimension AS Dimension, value AS Segment, n_control AS `Control n`,
                    n_treatment AS `Treatment n`, rel_diff AS Change, rel_ci_low AS Low,
                    rel_ci_high AS High,
                    if(p_adjusted < 0.0001, '<0.0001', toString(round(p_adjusted, 4))) AS `Holm p`
                FROM gamma.v_latest_results
                WHERE experiment = {E} AND role = 'segment'
                ORDER BY dimension, value"""
            )
        ],
        14,
        10,
        options={"showHeader": True},
        overrides=[
            {
                "matcher": {"id": "byRegexp", "options": "Change|Low|High"},
                "properties": [
                    {"id": "unit", "value": "percentunit"},
                    {"id": "decimals", "value": 1},
                ],
            },
            {
                "matcher": {"id": "byName", "options": "Holm p"},
                "properties": [{"id": "decimals", "value": 3}],
            },
        ],
        description="Leads for the next experiment, never a reason to ship to a segment alone.",
    )
    b.add(
        "barchart",
        "Change by player segment",
        [
            ch(
                f"""SELECT value AS segment, rel_diff AS change FROM gamma.v_latest_results
                WHERE experiment = {E} AND role = 'segment' AND dimension = 'segment' ORDER BY value"""
            )
        ],
        10,
        10,
        unit="percentunit",
        decimals=1,
        color_mode="fixed",
        options={"legend": {"showLegend": False}, "showValue": "auto"},
    )
    return b


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for board in (experiment(),):
        name = board.uid.removeprefix("gamma-")
        (OUT / f"{name}.json").write_text(json.dumps(board.json(), indent=2) + "\n")
        print(f"wrote {OUT / name}.json ({len(board.panels)} panels)")


if __name__ == "__main__":
    main()
