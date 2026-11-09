#!/bin/sh
# Back up InH-Ticketing: the database and the uploaded attachments.
#
#   scripts/backup.sh [label]
#
# Run it on the server, as the admin user. cron runs it every night (see
# docs/deployment.md, "Backups"); also run it by hand before every update,
# with a label such as before-v0.7.0. The app must be running (at least `db`).
#
# Each backup is one folder in $BACKUP_DIR, named after when it started:
#
#   2026-11-06_023000[_label]/
#     db.dump        the database (pg_dump custom format)
#     media/         a copy of every uploaded attachment (the `media` volume)
#     manifest.txt   when, app version, database version, sizes
#     SHA256SUMS     checksums of all of the above; restore.sh checks them first
#
# Attachments are stored as incremental snapshots. Each backup's media/ starts
# as hard links to the previous backup's files, which take no extra disk space.
# Only attachments added since are fetched, and deleted ones are dropped. Every
# backup still looks like, and restores as, a complete copy. This is exact
# because the app writes each attachment once, under a random name, and never
# changes it. So 14 days of backups cost about one copy of the attachments,
# plus 14 database dumps.
#
# The database is dumped first and the attachments second, so every attachment
# the dump refers to is in the snapshot. Both are read back to check them.
# A backup is written to "<name>.partial" and renamed only once complete.
# Then backup folders older than $KEEP_DAYS days are deleted.
#
# Backups contain every ticket, so they are readable by their owner only.
# Not included: .env (keep its values in IT's password vault) and the
# certificate's private key.
#
# Optional environment variables:
#   BACKUP_DIR   where backups go       (default /srv/inh-ticketing/backups)
#   KEEP_DAYS    days of backups kept   (default 14; 0 = delete nothing)
#
# Exit status 0 means the backup is complete and checked.

set -eu
umask 077

BACKUP_DIR=${BACKUP_DIR:-/srv/inh-ticketing/backups}
KEEP_DAYS=${KEEP_DAYS:-14}

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "BACKUP FAILED: $*" >&2; exit 1; }
dc() { docker compose -f compose.yaml -f compose.prod.yaml "$@"; }

usage() {
	echo "Usage: $0 [label]"
	echo "  label: letters, digits, '.', '_' and '-' only, e.g. before-v0.7.0"
}

case ${1:-} in
	-h | --help) usage; exit 0 ;;
	-*) usage >&2; exit 2 ;;
esac
[ $# -le 1 ] || { usage >&2; exit 2; }
LABEL=${1:-}
case $LABEL in
	*[!A-Za-z0-9._-]*) die "the label may only contain letters, digits, '.', '_' and '-'" ;;
esac
case $KEEP_DAYS in
	'' | *[!0-9]*) die "KEEP_DAYS must be a whole number of days (got '$KEEP_DAYS')" ;;
esac

# Work from the app folder (this script's parent), wherever it was run from.
APP_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$APP_DIR"

command -v docker > /dev/null 2>&1 || die "docker isn't installed or isn't on the PATH"
[ -d "$BACKUP_DIR" ] || die "$BACKUP_DIR doesn't exist; create it first (docs/deployment.md)"
[ -w "$BACKUP_DIR" ] || die "can't write to $BACKUP_DIR"
dc exec -T db pg_isready -q -U inh -d inh ||
	die "the database isn't running. Start the app first: docker compose -f compose.yaml -f compose.prod.yaml up -d"

NOW=$(date '+%Y-%m-%d_%H%M%S|%Y-%m-%d %H:%M:%S %Z')
NAME=${NOW%%|*}${LABEL:+_$LABEL}
STARTED=${NOW#*|}
FINAL=$BACKUP_DIR/$NAME
WORK=$FINAL.partial

mkdir "$WORK" || die "couldn't create $WORK"
# On any failure or interruption, remove the unfinished backup.
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

log "Backing up to $FINAL"

# 1. The database. pg_dump runs inside the db container, so it is always the
#    same version as the server. -T: no terminal, so binary output is intact.
dc exec -T db pg_dump -U inh -d inh -Fc > "$WORK/db.dump" || die "pg_dump failed"
[ -s "$WORK/db.dump" ] || die "the database dump is empty"
dc exec -T db pg_restore --list < "$WORK/db.dump" > /dev/null ||
	die "the database dump can't be read back"
log "Database dumped and checked"

# 2. The attachments, as an incremental snapshot. A throwaway container from
#    the web image reads the media volume, so this works even while web itself
#    is stopped (as during a restore). Lists are "size path", one file per line;
#    attachment paths never contain spaces or newlines (see tickets/models.py).
listing() { find . -type f -printf '%s %p\n' | LC_ALL=C sort; }

# The newest complete backup with a media/ folder, if any, to link against.
PREV=
for d in "$BACKUP_DIR"/[0-9]*; do
	case $d in *.partial) continue ;; esac
	[ -d "$d/media" ] && [ -f "$d/SHA256SUMS" ] && PREV=$d
done

mkdir "$WORK/media"
if [ -n "$PREV" ]; then
	# Hard links: instant, and no extra disk space for unchanged attachments.
	cp -al "$PREV/media/." "$WORK/media/" || die "couldn't link to the previous backup $PREV"
fi

# Each docker step writes to a file and is checked on its own. In a pipeline
# its failure would be hidden, and an empty listing would look like "no attachments".
dc run --rm --no-deps -T web sh -c "cd /app/media && find . -type f -printf '%s %p\n'" \
	> "$WORK/media.raw" || die "couldn't list the attachments"
LC_ALL=C sort "$WORK/media.raw" > "$WORK/media.now"
(cd "$WORK/media" && listing) > "$WORK/media.have"
# In the volume but not (identically) in the snapshot: fetch. The reverse: drop.
LC_ALL=C comm -23 "$WORK/media.now" "$WORK/media.have" | cut -d' ' -f2- > "$WORK/media.fetch"
LC_ALL=C comm -13 "$WORK/media.now" "$WORK/media.have" | cut -d' ' -f2- > "$WORK/media.drop"
# rm only removes this snapshot's link; older backups keep their copy.
while IFS= read -r f; do rm -f "$WORK/media/$f"; done < "$WORK/media.drop"
NEW=$(wc -l < "$WORK/media.fetch" | tr -d ' ')
if [ "$NEW" -gt 0 ]; then
	dc run --rm --no-deps -T web tar -cf - -C /app/media -T - < "$WORK/media.fetch" \
		> "$WORK/media.new.tar" || die "copying the new attachments out of the volume failed"
	tar -xf "$WORK/media.new.tar" -C "$WORK/media" || die "unpacking the new attachments failed"
fi
# Read back: the snapshot must now match the volume exactly.
(cd "$WORK/media" && listing) | cmp -s - "$WORK/media.now" ||
	die "the attachments snapshot doesn't match the media volume"
FILES=$(wc -l < "$WORK/media.now" | tr -d ' ')
rm -f "$WORK/media.raw" "$WORK/media.now" "$WORK/media.have" "$WORK/media.fetch" \
	"$WORK/media.drop" "$WORK/media.new.tar"
if [ -n "$PREV" ]; then SINCE="since ${PREV##*/}"; else SINCE="(first backup)"; fi
log "Attachments snapshot checked ($FILES files, $NEW new $SINCE)"

# 3. What this backup is, for whoever restores it.
size() { wc -c < "$1" | tr -d ' '; }
APP_VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' config/__init__.py)
GIT_VERSION=$(git describe --tags --always --dirty 2> /dev/null || echo unknown)
PG_VERSION=$(dc exec -T db psql -U inh -d inh -Atc 'show server_version' || echo unknown)
MIGRATIONS=$(dc exec -T db psql -U inh -d inh -At -F ' ' \
	-c 'select app, max(name) from django_migrations group by app order by app' ||
	echo unknown)
{
	echo "InH-Ticketing backup"
	echo "Name:          $NAME"
	echo "Started:       $STARTED"
	echo "Finished:      $(date '+%Y-%m-%d %H:%M:%S %Z')"
	echo "Server:        $(uname -n)"
	echo "App version:   ${APP_VERSION:-unknown} (git: $GIT_VERSION)"
	echo "PostgreSQL:    $PG_VERSION"
	echo "db.dump:       $(size "$WORK/db.dump") bytes"
	echo "media/:        $FILES files ($NEW new $SINCE)"
	echo "Latest database migration of each app:"
	printf '%s\n' "$MIGRATIONS" | sed 's/^/  /'
} > "$WORK/manifest.txt"

(cd "$WORK" && {
	sha256sum db.dump manifest.txt
	find media -type f | LC_ALL=C sort | xargs -r sha256sum
} > SHA256SUMS) || die "couldn't write the checksums"

mv "$WORK" "$FINAL" || die "couldn't rename $WORK to $FINAL"
trap - EXIT HUP INT TERM
# du counts hard-linked files once per run, so the total is the real disk use.
log "Backup OK: $FINAL. All backups together use $(du -sh "$BACKUP_DIR" | cut -f1)."

# 4. Delete backups older than KEEP_DAYS days (find's -mtime +N means "N+1
#    days old or more"), and anything left over from a failed run. Only
#    folders named like a backup are touched. restore.sh sets KEEP_DAYS=0 for
#    its safety backup, so the backup being restored can't be deleted.
if [ "$KEEP_DAYS" -gt 0 ]; then
	find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
		-name '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]*' \
		! -name '*.partial' -mtime +"$((KEEP_DAYS - 1))" \
		-exec sh -c 'for d; do echo "$(date "+%Y-%m-%d %H:%M:%S") Deleting old backup $d"; rm -rf "$d"; done' sh {} +
	find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '*.partial' -mtime +0 \
		-exec sh -c 'for d; do echo "$(date "+%Y-%m-%d %H:%M:%S") Deleting unfinished backup $d"; rm -rf "$d"; done' sh {} +
fi

# 5. Warn early if the disk is filling up (see docs/server-requirements.md).
#    Deleting an old backup frees only what no newer backup still links to.
USED=$(df -P "$BACKUP_DIR" | awk 'NR == 2 { sub("%", "", $5); print $5 }')
case $USED in
	'' | *[!0-9]*) ;;
	*) [ "$USED" -lt 80 ] || log "WARNING: the disk holding $BACKUP_DIR is ${USED}% full. See docs/server-requirements.md (Disk)." ;;
esac
