#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
backup_file="backups/channelradar-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
temporary_file="$(mktemp backups/.backup-XXXXXX)"
trap 'rm -f -- "$temporary_file"' EXIT
docker compose exec -T db pg_dump -U channelradar -d channelradar | gzip > "$temporary_file"
mv -- "$temporary_file" "$backup_file"
printf 'Saved %s\n' "$backup_file"
