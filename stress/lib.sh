# Shared by stress/server-setup.sh and stress/run.sh. STRESS-TEST BRANCH ONLY.
# Sourced from the repository folder; the caller defines die().

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
dc() { docker compose -f compose.yaml -f compose.prod.yaml -f compose.stress.yaml "$@"; }
env_value() { [ -f .env ] && sed -n "s/^$1=//p" .env | tail -n 1; }
# A Compose setting as Compose sees it: the shell first, then .env, then the default.
setting() { eval "v=\${$1:-}"; [ -n "$v" ] || v=$(env_value "$1"); echo "${v:-$2}"; }

# Which CPUs the app shares, and which the load generator uses (compose.stress.yaml).
app_cpus() { setting STRESS_APP_CPUS 0,1; }
loadgen_cpus() { setting STRESS_LOADGEN_CPUS 2,3; }

# How many CPUs a list like "0,1" or "0-3" names.
cpu_count() {
	n=0
	for part in $(echo "$1" | tr ',' ' '); do
		case $part in
			*-*) n=$((n + ${part#*-} - ${part%-*} + 1)) ;;
			*) n=$((n + 1)) ;;
		esac
	done
	echo "$n"
}

# The machine must have every CPU the two lists name.
check_cpus() {
	have=$(nproc)
	for list in "$(app_cpus)" "$(loadgen_cpus)"; do
		highest=$(echo "$list" | tr ',-' '\n\n' | sort -n | tail -n 1)
		[ "$highest" -lt "$have" ] ||
			die "this machine has $have CPUs, but CPU $highest is named in STRESS_APP_CPUS / STRESS_LOADGEN_CPUS (give the VM at least 4 cores, 6 recommended)"
	done
}

wait_ready() {
	i=0
	until dc exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" > /dev/null 2>&1; do
		i=$((i + 1))
		[ "$i" -lt 60 ] || die "the app didn't become ready within 2 minutes: docker compose logs web"
		sleep 2
	done
}

# psql as the database owner, on the maintenance database (so "inh" itself can be replaced).
psql_admin() { dc exec -T db psql -U inh -d postgres -v ON_ERROR_STOP=1 -q "$@"; }

has_baseline() { [ "$(psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname = 'inh_baseline'")" = 1 ]; }

# Keep a copy of the database as it is now: the starting point for every run.
save_baseline() {
	log "Saving the current data as the starting point for every run"
	dc stop web worker > /dev/null 2>&1
	psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'inh' AND pid <> pg_backend_pid()" > /dev/null
	psql_admin -c "DROP DATABASE IF EXISTS inh_baseline" -c "CREATE DATABASE inh_baseline TEMPLATE inh" ||
		{ dc start web worker > /dev/null 2>&1; die "couldn't save the starting point"; }
	dc start web worker > /dev/null 2>&1
	wait_ready
}

# Put the database back to the saved starting point, so every run starts from
# the same data, and delete the files earlier runs uploaded.
restore_baseline() {
	log "Resetting the data to the saved starting point"
	dc stop web worker > /dev/null 2>&1
	psql_admin -c "DROP DATABASE IF EXISTS inh WITH (FORCE)" -c "CREATE DATABASE inh TEMPLATE inh_baseline" ||
		die "couldn't reset the data; run sh stress/server-setup.sh to check the setup"
	dc start web worker > /dev/null 2>&1
	wait_ready
	dc exec -T web python manage.py stress_prune_files
}
