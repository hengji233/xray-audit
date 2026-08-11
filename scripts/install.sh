#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=xray-audit
SERVICE=xray-audit-api.service
SERVICE_USER=audituser
VERSION=latest
INSTALL_ROOT=/opt/xray-audit
DATA_DIR=/var/lib/xray-audit
LISTEN_HOST=127.0.0.1
LISTEN_PORT=8088
XRAY_LOG_DIR=/var/log/xray
START_SERVICE=1
UNATTENDED=0
REPOSITORY=${XRAY_AUDIT_REPOSITORY:-hengji233/xray-audit}
ENV_DIR=/etc/xray-audit
ENV_FILE=$ENV_DIR/xray-audit.env
UNIT_FILE=/etc/systemd/system/$SERVICE

usage() {
  cat <<'EOF'
Install a released Xray Audit wheel as a versioned systemd service.

Usage: sudo scripts/install.sh [options]

  --version VERSION       Release version, with or without v (default: latest)
  --install-root PATH     Version/current root (default: /opt/xray-audit)
  --data-dir PATH         Writable application data (default: /var/lib/xray-audit)
  --listen-host HOST      API bind address (default: 127.0.0.1)
  --listen-port PORT      API port (default: 8088)
  --xray-log-dir PATH     Directory containing access.log and error.log
  --no-start              Install and enable without starting or health checking
  --unattended            Never prompt; accept installation summary
  -h, --help              Show this help

Set XRAY_AUDIT_WHEEL to install a local wheel. Set XRAY_AUDIT_REPOSITORY to
override the GitHub owner/repository used for release downloads.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
log() { printf '==> %s\n' "$*"; }
need_value() { [[ $# -ge 2 && -n ${2:-} ]] || die "$1 requires a value"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) need_value "$@"; VERSION=$2; shift 2 ;;
    --install-root) need_value "$@"; INSTALL_ROOT=${2%/}; shift 2 ;;
    --data-dir) need_value "$@"; DATA_DIR=${2%/}; shift 2 ;;
    --listen-host) need_value "$@"; LISTEN_HOST=$2; shift 2 ;;
    --listen-port) need_value "$@"; LISTEN_PORT=$2; shift 2 ;;
    --xray-log-dir) need_value "$@"; XRAY_LOG_DIR=${2%/}; shift 2 ;;
    --no-start) START_SERVICE=0; shift ;;
    --unattended) UNATTENDED=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ $(id -u) -eq 0 ]] || die "run this installer as root"
[[ $INSTALL_ROOT =~ ^/[A-Za-z0-9._/-]+$ && $INSTALL_ROOT != *'/../'* ]] || die "--install-root must be a simple absolute path"
[[ $DATA_DIR =~ ^/[A-Za-z0-9._/-]+$ && $DATA_DIR != *'/../'* ]] || die "--data-dir must be a simple absolute path"
[[ $XRAY_LOG_DIR =~ ^/[A-Za-z0-9._/-]+$ && $XRAY_LOG_DIR != *'/../'* ]] || die "--xray-log-dir must be a simple absolute path"
[[ $LISTEN_HOST =~ ^[A-Za-z0-9:._-]+$ ]] || die "invalid listen host"
[[ $LISTEN_PORT =~ ^[0-9]+$ ]] && (( LISTEN_PORT >= 1 && LISTEN_PORT <= 65535 )) || die "invalid listen port"
[[ $VERSION =~ ^[A-Za-z0-9._+-]+$ ]] || die "invalid version"
[[ $REPOSITORY =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "invalid XRAY_AUDIT_REPOSITORY"

for command in curl python3 systemctl sha256sum; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

if [[ $UNATTENDED -eq 0 ]]; then
  printf 'Install Xray Audit %s under %s and listen on %s:%s? [y/N] ' "$VERSION" "$INSTALL_ROOT" "$LISTEN_HOST" "$LISTEN_PORT"
  read -r answer
  [[ $answer = y || $answer = Y ]] || die "installation cancelled"
fi

TMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

HAD_ENV=0
if [[ -f $ENV_FILE ]]; then
  HAD_ENV=1
  cp -p "$ENV_FILE" "$TMP_DIR/previous.env"
fi

resolve_latest_version() {
  local effective
  effective=$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$REPOSITORY/releases/latest")
  [[ $effective == */tag/* ]] || die "could not resolve latest release"
  printf '%s\n' "${effective##*/tag/}"
}

if [[ -n ${XRAY_AUDIT_WHEEL:-} ]]; then
  [[ -f $XRAY_AUDIT_WHEEL ]] || die "XRAY_AUDIT_WHEEL does not exist: $XRAY_AUDIT_WHEEL"
  WHEEL_NAME=$(basename "$XRAY_AUDIT_WHEEL")
  cp "$XRAY_AUDIT_WHEEL" "$TMP_DIR/$WHEEL_NAME"
  if [[ $VERSION = latest ]]; then
    VERSION=$(printf '%s' "$WHEEL_NAME" | sed -n 's/^xray_audit-\([^-]*\)-.*/\1/p')
    [[ -n $VERSION ]] || die "cannot infer version from local wheel; pass --version"
  fi
else
  [[ $VERSION != latest ]] || VERSION=$(resolve_latest_version)
  TAG=$VERSION
  [[ $TAG == v* ]] || TAG=v$TAG
  RELEASE_URL=https://github.com/$REPOSITORY/releases/download/$TAG
  curl -fL --retry 3 -o "$TMP_DIR/SHA256SUMS" "$RELEASE_URL/SHA256SUMS"
  WHEEL_NAME=$(awk '$2 ~ /^\*?xray_audit-[^-]+-py3-none-any\.whl$/ { sub(/^\*/, "", $2); print $2 }' "$TMP_DIR/SHA256SUMS")
  [[ -n $WHEEL_NAME && $WHEEL_NAME != *$'\n'* ]] || die "SHA256SUMS must identify exactly one universal xray-audit wheel"
  log "Downloading $RELEASE_URL/$WHEEL_NAME"
  curl -fL --retry 3 -o "$TMP_DIR/$WHEEL_NAME" "$RELEASE_URL/$WHEEL_NAME"
  EXPECTED=$(awk -v file="$WHEEL_NAME" '$2 == file || $2 == "*" file { print $1; exit }' "$TMP_DIR/SHA256SUMS")
  [[ $EXPECTED =~ ^[0-9a-fA-F]{64}$ ]] || die "wheel checksum is absent from SHA256SUMS"
  ACTUAL=$(sha256sum "$TMP_DIR/$WHEEL_NAME" | awk '{print $1}')
  [[ $ACTUAL = "$EXPECTED" ]] || die "wheel checksum mismatch"
fi

VERSION=${VERSION#v}
[[ $VERSION =~ ^[A-Za-z0-9._+-]+$ ]] || die "invalid resolved version"
RELEASES_DIR=$INSTALL_ROOT/releases
RELEASE_DIR=$RELEASES_DIR/$VERSION
CURRENT_LINK=$INSTALL_ROOT/current
NEW_LINK=$INSTALL_ROOT/.current.$$
PREVIOUS_TARGET=

if [[ -L $CURRENT_LINK ]]; then
  PREVIOUS_TARGET=$(readlink -f "$CURRENT_LINK")
elif [[ -e $CURRENT_LINK ]]; then
  die "$CURRENT_LINK exists and is not a symbolic link"
fi

if ! getent group "$SERVICE_USER" >/dev/null; then
  groupadd --system "$SERVICE_USER"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_USER" --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_ROOT" "$RELEASES_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
install -d -m 0750 "$ENV_DIR"

if [[ ! -d $RELEASE_DIR/venv ]]; then
  [[ ! -e $RELEASE_DIR ]] || die "incomplete release directory already exists: $RELEASE_DIR"
  install -d -m 0755 "$RELEASE_DIR"
  python3 -m venv "$RELEASE_DIR/venv"
  "$RELEASE_DIR/venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
  "$RELEASE_DIR/venv/bin/python" -m pip install --disable-pip-version-check "$TMP_DIR/$WHEEL_NAME"
fi

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

JWT_SECRET=$(random_secret 32)
ADMIN_PASSWORD=$(random_secret 18)
EXISTING_PASSWORD=

set_env() {
  local key=$1 value=$2 next=$TMP_DIR/env.next
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    $0 ~ "^" key "=" { if (!found) print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_TMP" >"$next"
  mv "$next" "$ENV_TMP"
}

ENV_TMP=$TMP_DIR/xray-audit.env
if [[ $HAD_ENV -eq 1 ]]; then
  cp "$TMP_DIR/previous.env" "$ENV_TMP"
  EXISTING_JWT=$(sed -n 's/^AUDIT_AUTH_JWT_SECRET=//p' "$ENV_FILE" | head -n 1)
  EXISTING_PASSWORD=$(sed -n 's/^AUDIT_ADMIN_BOOTSTRAP_PASSWORD=//p' "$ENV_FILE" | head -n 1)
  [[ -n $EXISTING_JWT ]] || set_env AUDIT_AUTH_JWT_SECRET "$JWT_SECRET"
  [[ -n $EXISTING_PASSWORD ]] || set_env AUDIT_ADMIN_BOOTSTRAP_PASSWORD "$ADMIN_PASSWORD"
  set_env AUDIT_DATA_DIR "$DATA_DIR"
  set_env AUDIT_LOG_PATH "$XRAY_LOG_DIR/access.log"
  set_env AUDIT_ERROR_LOG_PATH "$XRAY_LOG_DIR/error.log"
  set_env AUDIT_API_HOST "$LISTEN_HOST"
  set_env AUDIT_API_PORT "$LISTEN_PORT"
  set_env AUDIT_COLLECTOR_EMBEDDED true
  set_env AUDIT_AUTH_ALLOW_ANONYMOUS_HEALTH true
else
  cat >"$ENV_TMP" <<EOF
AUDIT_STORAGE_BACKEND=memory
AUDIT_DATA_DIR=$DATA_DIR
AUDIT_LOG_PATH=$XRAY_LOG_DIR/access.log
AUDIT_ERROR_LOG_PATH=$XRAY_LOG_DIR/error.log
AUDIT_API_HOST=$LISTEN_HOST
AUDIT_API_PORT=$LISTEN_PORT
AUDIT_COLLECTOR_EMBEDDED=true
AUDIT_REDIS_ENABLED=false
AUDIT_AUTH_ENABLED=true
AUDIT_AUTH_ALLOW_ANONYMOUS_HEALTH=true
AUDIT_AUTH_COOKIE_SECURE=true
AUDIT_AUTH_JWT_SECRET=$JWT_SECRET
AUDIT_ADMIN_BOOTSTRAP_USERNAME=admin
AUDIT_ADMIN_BOOTSTRAP_PASSWORD=$ADMIN_PASSWORD
EOF
fi
install -m 0640 -o root -g "$SERVICE_USER" "$ENV_TMP" "$ENV_FILE"

UNIT_TMP=$TMP_DIR/$SERVICE
cat >"$UNIT_TMP" <<EOF
[Unit]
Description=Xray Audit API with embedded collector
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$CURRENT_LINK
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$CURRENT_LINK/venv/bin/xray-audit-api
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR
ReadOnlyPaths=-$XRAY_LOG_DIR
UMask=0027
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
install -m 0644 "$UNIT_TMP" "$UNIT_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE"
ln -s "$RELEASE_DIR" "$NEW_LINK"
mv -Tf "$NEW_LINK" "$CURRENT_LINK"

if [[ $START_SERVICE -eq 1 ]]; then
  PROBE_HOST=$LISTEN_HOST
  [[ $PROBE_HOST != 0.0.0.0 && $PROBE_HOST != :: ]] || PROBE_HOST=127.0.0.1
  [[ $PROBE_HOST != *:* ]] || PROBE_HOST=[$PROBE_HOST]
  HEALTH_URL=http://$PROBE_HOST:$LISTEN_PORT/api/v1/health
  healthy=0
  if systemctl restart "$SERVICE"; then
    for _ in $(seq 1 30); do
      if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null; then healthy=1; break; fi
      sleep 1
    done
  fi
  if [[ $healthy -ne 1 ]]; then
    systemctl stop "$SERVICE" || true
    if [[ -n $PREVIOUS_TARGET ]]; then
      ln -s "$PREVIOUS_TARGET" "$NEW_LINK"
      mv -Tf "$NEW_LINK" "$CURRENT_LINK"
      if [[ $HAD_ENV -eq 1 ]]; then
        install -m 0640 -o root -g "$SERVICE_USER" "$TMP_DIR/previous.env" "$ENV_FILE"
      fi
      systemctl restart "$SERVICE" || true
    fi
    die "health check failed; previous current link was restored when available"
  fi
fi

log "Installed Xray Audit $VERSION"
log "Environment: $ENV_FILE"
if [[ -z ${EXISTING_PASSWORD:-} ]]; then
  log "Bootstrap credentials: admin / $ADMIN_PASSWORD (rotate after first login)"
fi
[[ $START_SERVICE -eq 0 ]] || log "Health check passed: $HEALTH_URL"
