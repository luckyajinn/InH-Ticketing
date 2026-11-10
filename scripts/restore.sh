#!/bin/sh
# Restore InH-Ticketing from a backup made by scripts/backup.sh.
#
#   scripts/restore.sh                         list the backups
#   scripts/restore.sh <backup>                restore the database and the attachments
#   scripts/restore.sh --db-only <backup>      restore the database only
#   scripts/restore.sh --media-only <backup>   restore the attachments only
#
# <backup> is a folder name from the list, such as 2026-11-06_023000, or the
# path of a backup folder (one copied from another server, say).
#
# Run it on the server, as the admin user, in a terminal. It asks before it
# changes anything, then:
#   1. checks the backup's checksums and shows what's in it;
#   2. asks you to type the backup's name to confirm;
#   3. stops web and worker, so nothing changes while it works (the database
#      keeps running);
#   4. takes a safety backup of the current data (labelled before-restore);
#   5. database: restores into a separate new database first, and swaps it in
#      only if that worked, so a failed restore leaves the current one alone;
#   6. attachments: empties the media volume, copies the backup's media/
#      snapshot in, then checks the volume matches it file by file;
#   7. leaves web and worker stopped, and says how to start them.
#
# To roll back an update, check out the version the backup was made with
# BEFORE running this (docs/deployment.md, "Rolling back").
#
# Optional environment variable:
#   BACKUP_DIR   where backups are (default /srv/inh-ticketing/backups)

set -eu
umask 077

BACKUP_DIR=${BACKUP_DIR:-/srv/inh-ticketing/backups}
START_CMD="docker compose -f compose.yaml -f compose.prod.yaml up -d --build"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "RESTORE FAILED: $*" >&2; exit 1; }
dc() { docker compose -f compose.yaml -f compose.prod.yaml "$@"; }
# psql as the database owner, connected to the maintenance database "postgres".
psql_admin() { dc exec -T db psql -U inh -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
ask() { printf '%s' "$1"; answer=; read -r answer || answer=; }

usage() {
	echo "Usage: $0 [--db-only | --media-only] <backup>"
	echo "       $0            (lists the backups)"
}

list_backups() {
	echo "Backups in $BACKUP_DIR, oldest first:"
	found=
	for d in "$BACKUP_DIR"/[0-9]*; do
		[ -f "$d/SHA256SUMS" ] || continue
		found=yes
		printf '  %-45s %6s\n' "${d##*/}" "$(du -sh "$d" | cut -f1)"
	done
	[ -n "$found" ] || echo "  (none)"
}

DB=yes
MEDIA=yes
case ${1:-} in
	'') usage; echo; list_backups; exit 0 ;;
	-h | --help) usage; exit 0 ;;
	--db-only) MEDIA=no; shift ;;
	--media-only) DB=no; shift ;;
	-*) usage >&2; exit 2 ;;
esac
[ $# -eq 1 ] || { usage >&2; exit 2; }

case $1 in
	*/*) SRC=${1%/} ;;
	*) SRC=$BACKUP_DIR/$1 ;;
esac
[ -d "$SRC" ] || die "there's no backup folder $SRC (run $0 on its own to list them)"
SRC=$(CDPATH='' cd -- "$SRC" && pwd)
NAME=${SRC##*/}
for f in db.dump manifest.txt SHA256SUMS; do
	[ -f "$SRC/$f" ] || die "$SRC/$f is missing: this isn't a complete backup"
done
[ -d "$SRC/media" ] || die "$SRC/media is missing: this isn't a complete backup"

# Work from the app folder (this script's parent), wherever it was run from.
APP_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$APP_DIR"
command -v docker > /dev/null 2>&1 || die "docker isn't installed or isn't on the PATH"
[ -t 0 ] || die "run this in a terminal: it asks you to confirm before changing anything"

log "Checking the backup's checksums"
(cd "$SRC" && sha256sum -c SHA256SUMS) || die "the backup is damaged (checksums don't match). Don't use it."

BACKUP_VERSION=$(sed -n 's/^App version: *\([^ ]*\).*/\1/p' "$SRC/manifest.txt")
CODE_VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' config/__init__.py)
GIT_VERSION=$(git describe --tags --always --dirty 2> /dev/null || echo unknown)
if [ "$DB" = yes ] && [ "$MEDIA" = yes ]; then
	WHAT="the database AND the attachments"
elif [ "$DB" = yes ]; then
	WHAT="the database only (the attachments are left as they are)"
else
	WHAT="the attachments only (the database is left as it is)"
fi

echo
echo "=== Restore InH-Ticketing from a backup ==="
echo
sed 's/^/  /' "$SRC/manifest.txt"
echo
echo "  Code checked out here: ${CODE_VERSION:-unknown} (git: $GIT_VERSION)"
echo
echo "This replaces $WHAT on this server with the copy in this backup."
echo "Everything changed since the backup was made will be lost. A safety backup"
echo "of the current data is taken first. The help desk is unavailable until you"
echo "start it again at the end."
if [ "$BACKUP_VERSION" != "$CODE_VERSION" ]; then
	echo
	echo "WARNING: this backup was made by version ${BACKUP_VERSION:-unknown}, but version"
	echo "${CODE_VERSION:-unknown} is checked out. To roll back an update, cancel now, check out"
	echo "the backup's version first (git checkout v$BACKUP_VERSION), then run this again."
fi
echo
ask "Type the backup's name ($NAME) to restore it, or press Enter to cancel: "
[ "$answer" = "$NAME" ] || { echo "Cancelled. Nothing was changed."; exit 1; }

log "Starting the database (if it isn't running) and stopping web and worker"
dc up -d --wait db || die "couldn't start the database"
# From here on, if anything stops the script, say how to bring the app back.
trap 'echo; echo "web and worker are stopped. To start them again: $START_CMD" >&2' EXIT
dc stop web worker || die "couldn't stop web and worker"

log "Taking a safety backup of the current data"
# KEEP_DAYS=0: the safety backup must not delete old backups (such as this one).
if ! BACKUP_DIR=$BACKUP_DIR KEEP_DAYS=0 sh "$APP_DIR/scripts/backup.sh" before-restore; then
	echo
	echo "The safety backup failed (see above). Without it, today's data can't be"
	echo "got back if this restore turns out to be the wrong one."
	ask "Type CONTINUE to restore anyway, or press Enter to stop: "
	[ "$answer" = CONTINUE ] || { log "Stopped. Nothing was changed."; exit 1; }
fi

if [ "$DB" = yes ]; then
	log "Restoring the database into a new database, inh_restore"
	# Leftovers from an earlier restore that stopped half-way, if any.
	dc exec -T db dropdb -U inh --if-exists inh_restore &&
		dc exec -T db dropdb -U inh --if-exists inh_before_restore &&
		dc exec -T db createdb -U inh -O inh inh_restore ||
		die "couldn't create the database inh_restore. The current database hasn't been changed."
	if ! dc exec -T db pg_restore -U inh -d inh_restore --no-owner --exit-on-error \
		--single-transaction < "$SRC/db.dump"; then
		dc exec -T db dropdb -U inh --if-exists inh_restore || true
		die "the database restore failed (see above). The current database hasn't been changed."
	fi

	log "Swapping the restored database in"
	psql_admin \
		-c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'inh' AND pid <> pg_backend_pid()" \
		-c 'ALTER DATABASE inh RENAME TO inh_before_restore' \
		-c 'ALTER DATABASE inh_restore RENAME TO inh' > /dev/null ||
		die "couldn't swap the databases. List them with: docker compose -f compose.yaml -f compose.prod.yaml exec db psql -U inh -d postgres -c '\\l'. If 'inh' is missing, rename inh_before_restore back to inh."
	dc exec -T db dropdb -U inh inh_before_restore ||
		log "Warning: couldn't remove the old database inh_before_restore; it's harmless, remove it later with dropdb"
	log "Database restored"
fi

if [ "$MEDIA" = yes ]; then
	log "Restoring the attachments (emptying the media volume, then copying the snapshot in)"
	MEDIA_FAILED="restoring the attachments failed (see above); they may be incomplete. Run this again, or restore the before-restore backup."
	tar -cf - -C "$SRC/media" . |
		dc run --rm --no-deps -T web sh -c 'find /app/media -mindepth 1 -delete && tar -xf - -C /app/media' ||
		die "$MEDIA_FAILED"
	# A failure early in that pipeline could go unnoticed, so compare the volume
	# with the backup file by file ("size path" lists, as backup.sh makes them).
	EXPECTED=$(cd "$SRC/media" && find . -type f -printf '%s %p\n' | LC_ALL=C sort)
	ACTUAL=$(dc run --rm --no-deps -T web sh -c "cd /app/media && find . -type f -printf '%s %p\n'") ||
		die "$MEDIA_FAILED"
	ACTUAL=$(printf '%s\n' "$ACTUAL" | LC_ALL=C sort)
	[ "$EXPECTED" = "$ACTUAL" ] || die "$MEDIA_FAILED (the media volume doesn't match the backup)"
	log "Attachments restored and checked ($(printf '%s' "$EXPECTED" | grep -c . || true) files)"
fi

trap - EXIT
echo
echo "Restore from $NAME finished. web and worker are still stopped."
echo
echo "Before starting them, check the code matches the backup: backup ${BACKUP_VERSION:-unknown},"
echo "checked out ${CODE_VERSION:-unknown}. When web starts it applies any database migrations"
echo "the code has and the backup doesn't."
echo
echo "Start the help desk:"
echo "  $START_CMD"
echo
echo "Then run the checks in docs/deployment.md. The safety backup is in"
echo "$BACKUP_DIR, in the newest folder ending _before-restore."
