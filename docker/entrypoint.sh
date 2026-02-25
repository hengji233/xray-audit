#!/usr/bin/env sh
set -eu

if [ "${AUDIT_AUTO_MIGRATE:-false}" = "true" ]; then
  python -m xray_audit.init_db
fi

exec "$@"