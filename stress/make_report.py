#!/usr/bin/env python3
"""
Turn one stress-test run into a report. STRESS-TEST BRANCH ONLY.

    python3 stress/make_report.py stress/reports/<run-folder>

Reads what stress/run.sh collected (meta.json, Locust's CSVs, resources.log,
caddy-access.log) and writes, in the same folder:

    report.html    one printable page: plain-English summary, verdict against the
                   targets, charts, slowest pages, server resources, test setup
    summary.json   the key numbers, for tracking runs over time
    summary.md     the same, short, to paste into an email or chat

Standard library only, so it runs anywhere Python 3 does.
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET_AVG_MS = 20.0       # average response time
TARGET_P99_MS = 1000.0     # 99th percentile response time
TARGET_FAIL_PCT = 1.0      # share of requests that failed

# scenario: (short name, details)
SCENARIOS = {
    "expected": ("a normal busy period", "30 staff and all 5 IT agents active at the same time, for 10 minutes"),
    "peak": ("a very busy period, such as a company-wide outage",
             "100 people at once, acting about three times faster than normal, for 10 minutes"),
    "stress": ("a search for the limit", "the number of people grows by 25 every minute up to 400, all acting very quickly"),
    "soak": ("an endurance run", "a normal busy period held for 2 hours"),
}


def describe(scenario: str) -> str:
    label, detail = SCENARIOS.get(scenario, (scenario, ""))
    return f"{label} ({detail})" if detail else label


def memory_mb(value: str) -> float:
    m = re.fullmatch(r"\s*([\d.]+)\s*([kmg]?)b?\s*", str(value).lower())
    if not m:
        return 0.0
    return float(m.group(1)) * {"k": 1 / 1024, "m": 1, "g": 1024, "": 1 / 1024 ** 2}[m.group(2)]


def size_limit(meta: dict) -> str:
    """The app's total CPU and memory allowance, in words."""
    limits = meta.get("limits") or {}
    if not limits:
        return "none recorded (trial run, results not representative)"
    cpus = sum(number(str(v.get("cpus"))) or 0 for v in limits.values())
    mem = sum(memory_mb(v.get("memory", "")) for v in limits.values())
    text = f"{cpus:g} CPUs and {mem / 1024:.3g} GB of memory for the app in total"
    if round(cpus, 3) <= 2 and mem <= 4096:
        return text + ", within the planned production server (2 CPUs, 4 GB)"
    return text + ": MORE than the planned production server (2 CPUs, 4 GB)"


COLORS = ["#2f5bd3", "#d97706", "#b91c1c", "#0f766e", "#6d28d9", "#5a6371"]


# --------------------------------------------------------------------------- reading
def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_stats(folder: Path):
    rows = read_csv(folder / "locust_stats.csv")
    total = next((r for r in rows if r.get("Name") == "Aggregated"), None)
    pages = [r for r in rows if r.get("Name") != "Aggregated"]
    return total, pages


def read_history(folder: Path) -> list[dict]:
    rows = [r for r in read_csv(folder / "locust_stats_history.csv") if r.get("Name") == "Aggregated"]
    if not rows:
        return []
    t0 = int(rows[0]["Timestamp"])
    out = []
    for r in rows:
        out.append({
            "t": int(r["Timestamp"]) - t0,
            "users": number(r.get("User Count")) or 0,
            "rps": number(r.get("Requests/s")) or 0,
            "fps": number(r.get("Failures/s")) or 0,
            "p50": number(r.get("50%")),
            "p95": number(r.get("95%")),
            "p99": number(r.get("99%")),
        })
    return out


def read_resources(folder: Path, project: str = "inh-stress") -> dict[str, list[tuple[int, float, float]]]:
    """{service: [(seconds since start, CPU % of one core, memory MiB)]} from `docker stats` samples."""
    path = folder / "resources.log"
    if not path.exists():
        return {}
    units = {"B": 1 / 1048576, "KiB": 1 / 1024, "kB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}
    samples: dict[str, list[tuple[int, float, float]]] = {}
    t0 = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stamp, _, raw = line.partition(" ")
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        match = re.fullmatch(rf"{project}-(web|db|worker|proxy)-\d+", item.get("Name", ""))
        if not match:
            continue  # other containers, including the load generator itself
        t0 = t0 if t0 is not None else int(stamp)
        cpu = number(item.get("CPUPerc", "").rstrip("%")) or 0.0
        used = item.get("MemUsage", "0B").split("/")[0].strip()
        m = re.fullmatch(r"([\d.]+)\s*([A-Za-z]+)", used)
        mem = float(m.group(1)) * units.get(m.group(2), 1) if m else 0.0
        samples.setdefault(match.group(1), []).append((int(stamp) - t0, cpu, mem))
    return samples


def read_proxy_timings(folder: Path) -> tuple[list[float], int]:
    """Durations (ms) of each request as the proxy saw it, and how many were server errors."""
    path = folder / "caddy-access.log"
    durations, errors = [], 0
    if not path.exists():
        return durations, errors
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        start = line.find("{")
        if start < 0 or "http.log.access" not in line:
            continue
        try:
            entry = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if "duration" in entry:
            durations.append(float(entry["duration"]) * 1000)
            errors += int(entry.get("status", 0)) >= 500
    return durations, errors


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def cpu_limit(meta: dict, service: str) -> float | None:
    try:
        return float(meta["limits"][service]["cpus"])
    except (KeyError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- analysis
def capacity(history: list[dict]) -> int | None:
    """Highest number of simultaneous users at which every window still met the targets."""
    by_level: dict[int, list[dict]] = {}
    for h in history:
        if h["users"]:
            by_level.setdefault(int(h["users"]), []).append(h)
    best = None
    for level in sorted(by_level):
        windows = [w for w in by_level[level] if w["p99"] is not None]
        if not windows:
            continue
        worst_p99 = max(w["p99"] for w in windows)
        fail_pct = 100 * sum(w["fps"] for w in windows) / max(sum(w["rps"] for w in windows), 1e-9)
        if worst_p99 <= TARGET_P99_MS and fail_pct <= TARGET_FAIL_PCT:
            best = level
        else:
            break
    return best


def fmt_ms(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.0f} ms" if v >= 10 else f"{v:.1f} ms"


# --------------------------------------------------------------------------- charts
def svg_chart(title: str, series: list[tuple[str, list[tuple[float, float]]]], y_unit: str,
              refs: list[tuple[float, str]] = (), width=760, height=230) -> str:
    """A small line chart. series: [(label, [(seconds, value), ...])]."""
    points = [p for _, pts in series for p in pts]
    if not points:
        return ""
    left, right, top, bottom = 56, 16, 52, 34
    x_max = max(p[0] for p in points) or 1
    y_max = max([p[1] for p in points] + [r[0] for r in refs if r[0] <= max(p[1] for p in points) * 3]) * 1.1 or 1
    sx = lambda x: left + (width - left - right) * x / x_max
    sy = lambda y: top + (height - top - bottom) * (1 - y / y_max)
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{html.escape(title)}">',
             f'<text x="{left}" y="16" class="ct">{html.escape(title)}</text>']
    for i in range(5):
        v = y_max * i / 4
        y = sy(v)
        label = f"{v:,.0f}" if y_max >= 10 else f"{v:.1f}"
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{y + 4:.1f}" class="yl">{label}</text>')
    minutes = max(int(x_max // 60), 1)
    step = max(1, minutes // 8)
    for m in range(0, minutes + 1, step):
        x = sx(m * 60)
        parts.append(f'<text x="{x:.1f}" y="{height - 14}" class="xl">{m} min</text>')
    parts.append(f'<text x="4" y="{top - 8}" class="yu">{html.escape(y_unit)}</text>')
    for value, label in refs:
        if value <= y_max:
            y = sy(value)
            parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="ref"/>'
                         f'<text x="{width - right}" y="{y - 4:.1f}" class="refl">{html.escape(label)}</text>')
    legend_x = left  # the legend sits on its own line under the title
    for i, (label, pts) in enumerate(series):
        color = COLORS[i % len(COLORS)]
        if pts:
            path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
            parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<rect x="{legend_x}" y="25" width="10" height="10" fill="{color}"/>'
                     f'<text x="{legend_x + 14}" y="34" class="lg">{html.escape(label)}</text>')
        legend_x += 14 + 6.2 * len(label) + 18
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- report
CSS = """
body{font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1a1d23;margin:0;background:#f5f6f8}
main{max-width:860px;margin:0 auto;padding:28px 20px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:#5a6371;margin:0 0 18px}.card{background:#fff;border:1px solid #e0e4ea;border-radius:10px;padding:18px 20px;margin:0 0 14px}
.verdict{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:14px}
.PASS{background:#dcfce7;color:#166534}.FAIL{background:#fee2e2;color:#991b1b}.INFO{background:#dbeafe;color:#1d4ed8}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e0e4ea}
th{color:#5a6371;font-weight:600;background:#f1f3f6}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:#166534;font-weight:700}.bad{color:#991b1b;font-weight:700}
.chart{width:100%;height:auto;background:#fff}.ct{font-size:13px;font-weight:700;fill:#1a1d23}
.grid{stroke:#e0e4ea}.yl{font-size:10.5px;fill:#5a6371;text-anchor:end}.xl{font-size:10.5px;fill:#5a6371;text-anchor:middle}
.lg{font-size:11px;fill:#1a1d23}.yu{font-size:10.5px;fill:#5a6371}.ref{stroke:#991b1b;stroke-dasharray:5 4}.refl{font-size:10.5px;fill:#991b1b;text-anchor:end}
.small{font-size:12.5px;color:#5a6371}ul{margin:6px 0 0;padding-left:20px}li{margin:3px 0}
@media print{body{background:#fff}.card{break-inside:avoid;border-color:#ccc}main{padding:0}}
"""


def main(folder: Path) -> int:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if (folder / "meta.json").exists() else {}
    total, pages = read_stats(folder)
    if total is None:
        print(f"No Locust results in {folder} (locust_stats.csv is missing or empty).", file=sys.stderr)
        return 1
    history = read_history(folder)
    resources = read_resources(folder)
    proxy_ms, proxy_errors = read_proxy_timings(folder)
    failures = read_csv(folder / "locust_failures.csv")

    scenario = meta.get("scenario", "unknown")
    requests = int(number(total["Request Count"]) or 0)
    failed = int(number(total["Failure Count"]) or 0)
    fail_pct = 100 * failed / max(requests, 1)
    avg = number(total["Average Response Time"])
    p50, p95, p99 = number(total["50%"]), number(total["95%"]), number(total["99%"])
    max_ms = number(total["Max Response Time"])
    rps = number(total["Requests/s"]) or 0
    duration_s = history[-1]["t"] if history else 0
    peak_users = int(max((h["users"] for h in history), default=0))

    checks = [
        ("Average response time", f"under {TARGET_AVG_MS:.0f} ms", fmt_ms(avg), avg is not None and avg <= TARGET_AVG_MS),
        ("99% of responses within", f"{TARGET_P99_MS / 1000:.0f} second", fmt_ms(p99), p99 is not None and p99 <= TARGET_P99_MS),
        ("Failed requests", f"under {TARGET_FAIL_PCT:.0f}%", f"{fail_pct:.2f}%", fail_pct <= TARGET_FAIL_PCT),
    ]
    cap = capacity(history) if scenario == "stress" else None
    overall = "INFO" if scenario == "stress" else ("PASS" if all(c[3] for c in checks) else "FAIL")

    # ---- plain-English summary
    data = meta.get("data", {})
    started = meta.get("started_utc", "")
    try:
        day = datetime.fromisoformat(started.replace("Z", "+00:00"))
        when = f"{day:%B} {day.day}, {day.year}"
    except ValueError:
        when = started or "unknown date"
    quick = " This was a shortened trial run, not a full test." if float(meta.get("scale", 1)) < 1 else ""
    if scenario == "stress":
        headline = (f"The system kept within the targets with up to <strong>{cap} people active at the same time</strong>."
                    if cap else "The system missed the targets even at the lowest load in this run.")
        meaning = [
            f"For comparison, a normal busy period is about 35 people at once (30 staff and 5 IT agents) "
            f"out of 300 staff, so the planned server has room for about <strong>{cap / 35:.0f}x</strong> that." if cap else
            "Look at the slowest pages below to see what to improve first.",
            "Beyond that point responses slow down sharply. That is expected from a deliberately overloaded test, not a fault.",
        ]
    else:
        verdict_text = "met all three performance targets" if overall == "PASS" else "did not meet every performance target"
        headline = (f"In {describe(scenario)}, the help desk <strong>{verdict_text}</strong>: "
                    f"{requests:,} requests, an average response of <strong>{fmt_ms(avg)}</strong>, and 99% of "
                    f"responses within <strong>{fmt_ms(p99)}</strong>.")
        meaning = (["The planned server (2 CPUs, 4 GB of memory) is big enough for this level of use, with room to spare."]
                   if overall == "PASS" else
                   [f"Targets missed: {', '.join(c[0].lower() for c in checks if not c[3])}. "
                    "The slowest pages below show where to improve before go-live."])
    meaning.append(f"Simulated on a private test server with invented data: {data.get('tickets', '?'):,} tickets "
                   f"(about 5 years' worth), {data.get('requesters', '?')} staff accounts and "
                   f"{data.get('agents', '?')} IT agents. No real data or company systems were involved."
                   if isinstance(data.get("tickets"), int) else
                   "Simulated on a private test server with invented data. No real data or company systems were involved.")

    # ---- charts
    rt_series = [(f"{k}", [(h["t"], h[k]) for h in history if h[k] is not None]) for k in ("p50", "p95", "p99")]
    rt_series = [(label.replace("p", "") + "% of responses within", pts) for label, pts in rt_series]
    charts = [
        svg_chart("Response time during the test", rt_series, "ms", refs=[(TARGET_P99_MS, "1-second target")]),
        svg_chart("Load during the test", [("people active", [(h["t"], h["users"]) for h in history]),
                                           ("requests per second", [(h["t"], h["rps"]) for h in history])], "count"),
    ]
    if resources:
        cpu_series = []
        for svc, pts in sorted(resources.items()):
            limit = cpu_limit(meta, svc)
            cpu_series.append((f"{svc} (% of its CPU)",
                               [(t, c / limit if limit else c) for t, c, _ in pts]))
        charts.append(svg_chart("Server CPU use (100% = all the CPU it's allowed)", cpu_series, "%",
                                refs=[(100, "its limit")]))
        charts.append(svg_chart("Server memory use", [(svc, [(t, m) for t, _, m in pts])
                                                      for svc, pts in sorted(resources.items())], "MiB"))

    # ---- tables
    def row_checks():
        return "".join(
            f"<tr><td>{n}</td><td>{t}</td><td class='n'>{r}</td><td class='{'ok' if ok else 'bad'}'>{'Met' if ok else 'Missed'}</td></tr>"
            for n, t, r, ok in checks)

    slowest = sorted(pages, key=lambda r: number(r.get("Average Response Time")) or 0, reverse=True)
    page_rows = "".join(
        f"<tr><td>{html.escape(r['Name'])}</td><td class='n'>{int(number(r['Request Count']) or 0):,}</td>"
        f"<td class='n'>{fmt_ms(number(r['Average Response Time']))}</td><td class='n'>{fmt_ms(number(r['95%']))}</td>"
        f"<td class='n'>{fmt_ms(number(r['99%']))}</td><td class='n'>{int(number(r['Failure Count']) or 0):,}</td></tr>"
        for r in slowest)
    resource_rows = ""
    for svc, pts in sorted(resources.items()):
        limit = cpu_limit(meta, svc)
        cpus = [c / limit if limit else c for _, c, _ in pts]
        mems = [m for _, _, m in pts]
        mem_limit = meta.get("limits", {}).get(svc, {}).get("memory", "?")
        resource_rows += (f"<tr><td>{svc}</td><td class='n'>{sum(cpus) / len(cpus):.0f}%</td><td class='n'>{max(cpus):.0f}%</td>"
                          f"<td class='n'>{max(mems):,.0f} MiB</td><td class='n'>{html.escape(str(mem_limit))}</td></tr>")
    failure_rows = "".join(
        f"<tr><td>{html.escape(f.get('Method', ''))} {html.escape(f.get('Name', ''))}</td>"
        f"<td>{html.escape(f.get('Error', ''))[:160]}</td><td class='n'>{f.get('Occurrences', '')}</td></tr>"
        for f in failures)
    server = meta.get("server", {})
    machine = ", ".join(str(part) for part in (
        server.get("cpu_model"),
        f"{server['cpus']} CPUs" if server.get("cpus") else None,
        f"{server['memory_mb'] / 1024:.0f} GB memory" if server.get("memory_mb") else None,
    ) if part) or "unknown"
    size_text = html.escape(size_limit(meta))
    raw_files = ", ".join(sorted(p.name for p in folder.iterdir()
                                 if p.is_file() and p.name not in ("report.html", "summary.json", "summary.md")))
    proxy_avg = sum(proxy_ms) / len(proxy_ms) if proxy_ms else None
    proxy_p99 = percentile(proxy_ms, 99)

    report = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InH-Ticketing performance test: {html.escape(scenario)} ({html.escape(when)})</title><style>{CSS}</style></head>
<body><main>
<h1>InH-Ticketing performance test</h1>
<p class="sub">{html.escape(when)} · scenario: {html.escape(scenario)} · <span class="verdict {overall}">{overall}</span>{quick}</p>

<div class="card"><p style="margin:0 0 8px;font-size:15.5px">{headline}</p><ul>{"".join(f"<li>{m}</li>" for m in meaning)}</ul></div>

<h2>Against the targets</h2>
<div class="card"><table><tr><th>Measure</th><th>Target</th><th class="n">Result</th><th>Verdict</th></tr>{row_checks()}</table>
<p class="small" style="margin:10px 0 0">Measured from the requester's side, over the whole run, including ramp-up.
Half of all responses took {fmt_ms(p50)} or less; 95% took {fmt_ms(p95)} or less; the slowest single response took {fmt_ms(max_ms)}.
{f"Time inside the server alone (as the web proxy measured it): average {fmt_ms(proxy_avg)}, 99% within {fmt_ms(proxy_p99)}." if proxy_ms else ""}</p></div>

<h2>Charts</h2>
{"".join(f'<div class="card">{c}</div>' for c in charts if c)}

<h2>Pages, slowest first</h2>
<div class="card"><table><tr><th>Page or action</th><th class="n">Requests</th><th class="n">Average</th><th class="n">95%</th><th class="n">99%</th><th class="n">Failed</th></tr>{page_rows}</table></div>

{f'<h2>Server resources</h2><div class="card"><table><tr><th>Part</th><th class="n">Average CPU</th><th class="n">Peak CPU</th><th class="n">Peak memory</th><th class="n">Memory allowed</th></tr>{resource_rows}</table><p class="small" style="margin:10px 0 0">CPU is shown as a share of what each part is allowed. The app as a whole: {size_text}.</p></div>' if resource_rows else ''}

{f'<h2>Failures</h2><div class="card"><table><tr><th>Request</th><th>Error</th><th class="n">Times</th></tr>{failure_rows}</table></div>' if failure_rows else ''}

<h2>Test setup</h2>
<div class="card"><table>
<tr><td>Scenario</td><td>{html.escape(describe(scenario))}</td></tr>
<tr><td>Duration</td><td>{duration_s // 60} min {duration_s % 60} s · up to {peak_users} people at once · {rps:.1f} requests per second on average</td></tr>
<tr><td>Data</td><td>{html.escape(", ".join(f"{v:,} {k.replace('_', ' ')}" for k, v in data.items() if isinstance(v, int)) or "unknown")}</td></tr>
<tr><td>App size limit</td><td>{size_text}</td></tr>
<tr><td>Test machine</td><td>{html.escape(machine)}</td></tr>
<tr><td>Version</td><td>{html.escape(str(meta.get("app_version", "?")))} ({html.escape(str(meta.get("deployed_version", "?")))})</td></tr>
<tr><td>Raw data</td><td>{html.escape(raw_files)} (in the same folder)</td></tr>
</table><p class="small" style="margin:10px 0 0">Private test server with invented data only. No sign-in to Microsoft 365, no email sent or read.</p></div>
</main></body></html>"""
    (folder / "report.html").write_text(report, encoding="utf-8")

    summary = {
        "scenario": scenario, "started_utc": started, "overall": overall,
        "requests": requests, "failed_pct": round(fail_pct, 3), "requests_per_second": round(rps, 2),
        "avg_ms": avg, "p50_ms": p50, "p95_ms": p95, "p99_ms": p99, "max_ms": max_ms,
        "proxy_avg_ms": round(proxy_avg, 2) if proxy_avg else None,
        "proxy_p99_ms": round(proxy_p99, 2) if proxy_p99 else None,
        "peak_users": peak_users, "capacity_users": cap,
        "targets": {"avg_ms": TARGET_AVG_MS, "p99_ms": TARGET_P99_MS, "failed_pct": TARGET_FAIL_PCT},
        "checks": {name: ok for name, _, _, ok in checks},
        "data": data,
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [f"**InH-Ticketing performance test: {scenario}** ({when}): **{overall}**", ""]
    md += [f"- {n}: {r} (target {t}): {'met' if ok else 'missed'}" for n, t, r, ok in checks]
    if cap is not None:
        md.append(f"- Capacity: within targets up to {cap} people active at once")
    sizing = "app capped at 2 CPUs / 4 GB" if meta.get("limits") else "app NOT size-capped (trial run)"
    md.append(f"- {requests:,} requests, up to {peak_users} people at once, {sizing}")
    (folder / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n".join(md))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
