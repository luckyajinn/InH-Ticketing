#!/bin/sh
# Copy the stress-test branch to the private test server over SSH, then set it
# up there. STRESS-TEST BRANCH ONLY. Run from your PC (Git Bash), in the repo.
#
#   sh stress/push-to-server.sh <ssh-target> [remote-folder] [hostname]
#
#   <ssh-target>    how you SSH to the server, e.g. admin@inh-stress (tailnet name)
#   remote-folder   default: /srv/inh-stress
#   hostname        the test site's name, used on first setup (default inh-stress.test)
#
# Sends the last COMMIT of this branch (git archive): uncommitted changes and
# untracked files such as .env never leave your PC. On the server, an existing
# stress-test .env, certificate, data and reports are kept.

set -eu

TARGET=${1:-}
DIR=${2:-/srv/inh-stress}
SITE=${3:-inh-stress.test}
[ -n "$TARGET" ] || { sed -n '2,14p' "$0"; exit 2; }
case $DIR$SITE in *"'"* | *" "*) echo "The folder and hostname can't contain quotes or spaces." >&2; exit 2 ;; esac

cd "$(dirname "$0")/.."
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = stress-test ] || { echo "Check out the stress-test branch first (you're on $BRANCH)." >&2; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
	echo "Note: you have uncommitted changes. They are NOT sent; only the last commit is."
fi
COMMIT=$(git rev-parse --short HEAD)

echo "Sending stress-test @ $COMMIT to $TARGET:$DIR"
# Linux line endings in every file, whatever this PC's Git does on checkout.
git -c core.autocrlf=false -c core.eol=lf archive --format=tar HEAD |
	ssh "$TARGET" "mkdir -p '$DIR' && tar -xf - -C '$DIR' && echo 'stress-test @ $COMMIT, sent $(date -u +%Y-%m-%dT%H:%MZ)' > '$DIR/stress/.deployed-version'"

echo "Setting it up on the server"
ssh -t "$TARGET" "cd '$DIR' && sh stress/server-setup.sh '$SITE'"
echo
echo "Next, on the server:  cd $DIR && sh stress/run.sh expected"
