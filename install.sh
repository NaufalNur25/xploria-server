#!/usr/bin/env bash
#
# Installer Xploria RPi Daemon sebagai service systemd.
#
# Pemakaian (dari root repo, di Raspberry Pi):
#   sudo ./install.sh
#
# Override opsional via environment variable:
#   sudo APP_USER=xploria APP_DIR=/home/xploria/xploria-server ./install.sh
#
# Script ini idempotent: aman dijalankan ulang untuk update kode.

set -euo pipefail

APP_USER="${APP_USER:-xploria}"
APP_DIR="${APP_DIR:-/home/${APP_USER}/xploria-server}"
SERVICE_NAME="xploria-daemon"
SERVICE_SRC="$(dirname "$(readlink -f "$0")")/${SERVICE_NAME}.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"
SRC_DIR="$(dirname "$(readlink -f "$0")")"
HW_GROUPS=(gpio i2c spi)

log()  { echo -e "\033[1;32m[install]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*" >&2; }
die()  { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Jalankan dengan sudo: sudo ./install.sh"
[[ -f "$SERVICE_SRC" ]] || die "File service tidak ditemukan: $SERVICE_SRC"
command -v systemctl >/dev/null || die "systemd tidak tersedia di sistem ini."

# ---------------------------------------------------------------------------
# 1. Dependency sistem
# ---------------------------------------------------------------------------
log "Install dependency sistem (apt)..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev \
    rsync swig liblgpio-dev python3-lgpio libgpiod-dev >/dev/null \
    || warn "Sebagian paket apt gagal di-install; pip akan mencoba build sendiri."

# ---------------------------------------------------------------------------
# 2. User & grup hardware
# ---------------------------------------------------------------------------
for g in "${HW_GROUPS[@]}"; do
    if ! getent group "$g" >/dev/null; then
        # Tanpa grup ini systemd gagal start (status=216/GROUP).
        warn "Grup '$g' belum ada, dibuat. Pastikan udev rule memberi akses device ke grup ini."
        groupadd --system "$g"
    fi
done

if ! id "$APP_USER" >/dev/null 2>&1; then
    log "Membuat user '$APP_USER'..."
    useradd --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
usermod -aG "$(IFS=,; echo "${HW_GROUPS[*]}")" "$APP_USER"

# ---------------------------------------------------------------------------
# 3. Salin kode aplikasi
# ---------------------------------------------------------------------------
log "Sinkronisasi kode ke $APP_DIR ..."
mkdir -p "$APP_DIR"
if [[ "$SRC_DIR" != "$(readlink -f "$APP_DIR")" ]]; then
    # pin_config.db sengaja di-exclude agar konfigurasi pin di target tidak tertimpa.
    rsync -a --delete \
        --exclude '.git/' --exclude '.venv/' --exclude 'venv/' \
        --exclude '__pycache__/' --exclude '*.pyc' --exclude '.test-deps/' \
        --exclude 'pin_config.db' --exclude '*.log' \
        "$SRC_DIR/" "$APP_DIR/"
fi

# ---------------------------------------------------------------------------
# 4. Virtualenv
# ---------------------------------------------------------------------------
# --system-site-packages agar python3-lgpio dari apt bisa dipakai tanpa compile.
if [[ ! -x "$APP_DIR/.venv/bin/python3" ]]; then
    log "Membuat virtualenv..."
    python3 -m venv --system-site-packages "$APP_DIR/.venv"
fi
log "Install dependency Python..."
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ---------------------------------------------------------------------------
# 5. Ownership (penting untuk SQLite pin_config.db + file journal-nya)
# ---------------------------------------------------------------------------
log "Set ownership $APP_DIR -> $APP_USER ..."
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"

# ---------------------------------------------------------------------------
# 6. Pasang service systemd
# ---------------------------------------------------------------------------
log "Memasang $SERVICE_DST ..."
sed -e "s|^User=.*|User=${APP_USER}|" \
    -e "s|^Group=.*|Group=${APP_USER}|" \
    -e "s|/home/xploria/xploria-server|${APP_DIR}|g" \
    "$SERVICE_SRC" > "$SERVICE_DST"
chmod 644 "$SERVICE_DST"

if command -v systemd-analyze >/dev/null; then
    systemd-analyze verify "$SERVICE_DST" || warn "systemd-analyze melaporkan peringatan (lihat di atas)."
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"

sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Service '$SERVICE_NAME' berjalan. ✅"
else
    warn "Service belum aktif. Cek log:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    exit 1
fi

cat <<EOF

Selesai. Perintah berguna:
  sudo systemctl status ${SERVICE_NAME}
  sudo journalctl -u ${SERVICE_NAME} -f

Jalankan CLI pin config sebagai user '${APP_USER}' (JANGAN pakai sudo biasa,
agar pin_config.db tetap dimiliki '${APP_USER}'):
  sudo -u ${APP_USER} ${APP_DIR}/.venv/bin/python3 ${APP_DIR}/pin_config_cli.py list
EOF
