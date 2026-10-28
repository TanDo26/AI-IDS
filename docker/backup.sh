#!/bin/sh
# The `backup` service (docker-compose.yml): pg_dump of the app database into /backups (./backups).
#
# One dump a day: at the first check at or after BACKUP_HOUR (UTC), or as soon as the newest dump is
# more than a day old, so a PC that was off at that hour catches up when it is back. The newest
# BACKUP_KEEP dumps are kept. `sh /backup.sh now` takes one immediately.
#
# Custom format (pg_restore); restore steps in README "Backups". The files hold password hashes
# and e-mail addresses, so only their owner may read them.
set -u
umask 077

DIR=/backups
HOUR=${BACKUP_HOUR:-2}
KEEP=${BACKUP_KEEP:-7}

backup() {
    name="ids-$(date -u +%Y%m%d-%H%M%S).dump"
    if pg_dump --format=custom --file="$DIR/.$name.part" && mv "$DIR/.$name.part" "$DIR/$name"; then
        rm -f /tmp/backup-failed
        echo "backup: wrote $name ($(du -h "$DIR/$name" | cut -f1))"
        ls -1 "$DIR"/ids-*.dump | sort -r | tail -n "+$((KEEP + 1))" | while read -r old; do
            rm -f "$old" && echo "backup: removed $(basename "$old")"
        done
    else
        rm -f "$DIR/.$name.part"
        touch /tmp/backup-failed
        echo "backup: pg_dump failed; next attempt in 5 minutes" >&2
        return 1
    fi
}

if [ "${1:-}" = now ]; then
    backup
    exit
fi

echo "backup: daily at ${HOUR}:00 UTC (or when the newest dump is a day old), keeping $KEEP"
while :; do
    touch /tmp/backup-alive
    done_today=$(find "$DIR" -name "ids-$(date -u +%Y%m%d)-*.dump" | head -n 1)
    recent=$(find "$DIR" -name 'ids-*.dump' -mmin -1440 | head -n 1)
    if { [ "$(date -u +%H)" -ge "$HOUR" ] && [ -z "$done_today" ]; } || [ -z "$recent" ]; then
        backup
    fi
    sleep 300
done
