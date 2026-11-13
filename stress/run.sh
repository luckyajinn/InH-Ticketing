#!/bin/sh
# Run stress tests against the stress-test copy and write a report for each.
# STRESS-TEST BRANCH ONLY. Run on the test server, after stress/server-setup.sh.
#
#   sh stress/run.sh [scenario...] [--quick] [--keep-data] [--save-baseline]
#
# Scenarios (see stress/locustfile.py):
#   expected   normal busy period: 30 staff + 5 IT agents active, 10 minutes  (default)
#   peak       very busy: 100 people, 3x faster than normal, 10 minutes
#   stress     add 25 people a minute up to 400, to find the limit, 16 minutes
#   soak       normal load for 2 hours
#   all        expected, peak, then stress
# --quick          every stage 10x shorter (a ~1-minute trial run; not for reporting)
# --keep-data      don't reset the data first (normally every run starts from
#                  the same saved data, so runs can be compared)
# --save-baseline  save the data as it is now as the new starting point (after
#                  generating different data); runs any scenarios named after it
#
# Each run writes stress/reports/<date>_<scenario>/ containing report.html (for
# sharing, e.g. with the CFO), summary.json, summary.md, and the raw data.

set -eu
cd "$(dirname "$0")/.."

die() { log "RUN FAILED: $*" >&2; exit 1; }
. stress/lib.sh

SCALE=1
SCENARIOS=
KEEP_DATA=no
SAVE=no
for arg in "$@"; do
	case $arg in
		--quick) SCALE=0.1 ;;
		--keep-data) KEEP_DATA=yes ;;
		--save-baseline) SAVE=yes ;;
		all) SCENARIOS="$SCENARIOS expected peak stress" ;;
		expected | peak | stress | soak) SCENARIOS="$SCENARIOS $arg" ;;
		-h | --help) sed -n '2,23p' "$0"; exit 0 ;;
		*) die "unknown option or scenario '$arg' (expected, peak, stress, soak, all)" ;;
	esac
done

[ -f .env ] && grep -q '^STRESS_TEST_MODE=1' .env || die "this isn't a stress-test setup; run stress/server-setup.sh first"
HOST=$(env_value HELPDESK_HOSTNAME)
check_cpus
dc exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" ||
	die "the app isn't running; start it with sh stress/server-setup.sh"

if [ "$SAVE" = yes ]; then
	save_baseline
	[ -n "$SCENARIOS" ] || exit 0
elif ! has_baseline; then
	save_baseline  # set up before saving starting points existed
fi
[ -n "$SCENARIOS" ] || SCENARIOS=expected

APP_CPUS=$(app_cpus)
LOADGEN_CPUS=$(loadgen_cpus)

run_one() {
	scenario=$1
	[ "$KEEP_DATA" = yes ] || restore_baseline

	name="$(date '+%Y-%m-%d_%H%M%S')_$scenario"
	out="stress/reports/$name"
	mkdir -p "$out"
	chmod 777 "$out"   # the loadgen container writes here as its own user

	log "=== $scenario: writing $out"
	started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
	counts=$(dc exec -T web python manage.py stress_counts)
	cpu_model=$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo 2> /dev/null | head -n 1)
	cat > "$out/meta.json" <<EOF
{
  "scenario": "$scenario",
  "scale": $SCALE,
  "started_utc": "$started",
  "fresh_data": $([ "$KEEP_DATA" = yes ] && echo false || echo true),
  "host": "$HOST",
  "deployed_version": "$(cat stress/.deployed-version 2> /dev/null || echo unknown)",
  "app_version": "$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' config/__init__.py)",
  "server": {"cpus": $(nproc), "memory_mb": $(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo), "cpu_model": "${cpu_model:-unknown}", "kernel": "$(uname -r)"},
  "cpus": {"app": "$APP_CPUS", "app_count": $(cpu_count "$APP_CPUS"), "loadgen": "$LOADGEN_CPUS"},
  "limits": {
    "web":    {"memory": "$(setting STRESS_WEB_MEM 1536m)"},
    "db":     {"memory": "$(setting STRESS_DB_MEM 1536m)"},
    "worker": {"memory": "$(setting STRESS_WORKER_MEM 512m)"},
    "proxy":  {"memory": "$(setting STRESS_PROXY_MEM 256m)"}
  },
  "data": $counts
}
EOF

	# Sample container CPU and memory every 2 seconds while the test runs.
	(
		while :; do
			docker stats --no-stream --format '{{json .}}' 2> /dev/null | sed "s/^/$(date +%s) /" >> "$out/resources.log"
			sleep 2
		done
	) &
	sampler=$!

	log "Running the load (Locust). Progress is quiet; this takes a while."
	# --no-deps: the app is already running (checked above); leave it untouched.
	dc --profile loadgen run --rm -T --no-deps \
		-e STRESS_SCENARIO="$scenario" -e STRESS_DURATION_SCALE="$SCALE" \
		loadgen -f /mnt/stress/locustfile.py --headless --host "https://$HOST" \
		--csv "/mnt/reports/$name/locust" --csv-full-history \
		--html "/mnt/reports/$name/locust-report.html" --only-summary \
		> "$out/locust-console.log" 2>&1 || true   # Locust exits 1 if any request failed

	kill "$sampler" 2> /dev/null || true
	wait "$sampler" 2> /dev/null || true
	# The proxy's own timing of every request (time inside the server, no network).
	dc logs proxy --since "$started" --no-log-prefix > "$out/caddy-access.log" 2>&1 || true

	log "Building the report"
	dc --profile loadgen run --rm -T --no-deps --entrypoint python3 loadgen \
		/mnt/stress/make_report.py "/mnt/reports/$name" || die "building the report failed"
	verdict=$(sed -n 's/.*"overall": "\([A-Z]*\)".*/\1/p' "$out/summary.json" | head -n 1)
	log "=== $scenario: $verdict. Report: $out/report.html"
}

for s in $SCENARIOS; do
	run_one "$s"
done
echo
echo "Copy the reports to your PC (in the repository folder, git ignores them):"
echo "  scp -r <server>:$(pwd)/stress/reports stress/"
echo "Open report.html in a browser; print it to PDF to send it on."
