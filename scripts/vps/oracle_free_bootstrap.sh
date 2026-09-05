#!/usr/bin/env bash
# Oracle Cloud Always Free — minimal secure relay (Ubuntu 24.04 aarch64/amd64).
# Run as root on fresh instance: curl -fsSL ... | sudo bash
# Or: sudo bash oracle_free_bootstrap.sh
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== demo VPS bootstrap $(date -u +%FT%TZ) ==="

apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
  jq htop git

# --- SSH hardening (keep key auth) ---
if [[ -f /etc/ssh/sshd_config ]]; then
  sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config || true
  sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config || true
  systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
fi

# --- firewall: SSH only until Tailscale ---
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH bootstrap'
ufw --force enable

# --- auto security updates ---
cat >/etc/apt/apt.conf.d/51demo-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
EOF
dpkg-reconfigure -plow unattended-upgrades 2>/dev/null || true

# --- fail2ban ssh ---
cat >/etc/fail2ban/jail.d/demo-sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban

# --- Tailscale ---
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
echo ""
echo ">>> Run manually (needs browser/auth key):"
echo "    sudo tailscale up --ssh --hostname=demo-relay"
echo ">>> Then: sudo ufw delete allow 22/tcp && sudo ufw reload"
echo ""

# --- health probe timer (optional: edit URL to your Mac Tailscale IP) ---
install -d -m 0755 /opt/demo-relay
cat >/opt/demo-relay/health_probe.sh <<'PROBE'
#!/usr/bin/env bash
# Probes Mac gateway via Tailscale when configured.
MAC_GW="${DEMO_MAC_GW:-}"
OUT="/var/log/demo-relay-health.log"
ts="$(date -u +%FT%TZ)"
if [[ -z "${MAC_GW}" ]]; then
  echo "${ts} skip (set DEMO_MAC_GW=100.x.x.x:8501 in /etc/demo-relay.env)" >>"${OUT}"
  exit 0
fi
code="$(curl -sf --max-time 5 -o /dev/null -w '%{http_code}' "http://${MAC_GW}/health" 2>/dev/null || echo 000)"
echo "${ts} mac_gateway http=${code}" >>"${OUT}"
PROBE
chmod +x /opt/demo-relay/health_probe.sh

cat >/etc/demo-relay.env <<'ENV'
# Tailscale IP:port of Mac grid gateway, e.g. 100.64.0.1:8501
DEMO_MAC_GW=
ENV
chmod 0600 /etc/demo-relay.env

cat >/etc/systemd/system/demo-relay-health.service <<'UNIT'
[Unit]
Description=Probe Mac demo gateway via Tailscale

[Service]
Type=oneshot
EnvironmentFile=-/etc/demo-relay.env
ExecStart=/opt/demo-relay/health_probe.sh
UNIT

cat >/etc/systemd/system/demo-relay-health.timer <<'TIMER'
[Unit]
Description=Every 5 min demo relay health probe

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable --now demo-relay-health.timer

# --- metadata ---
cat >/etc/demo-relay-bootstrap.json <<META
{
  "role": "demo-relay",
  "bootstrap": "$(date -u +%FT%TZ)",
  "tailscale": "run: sudo tailscale up --ssh --hostname=demo-relay",
  "notes": "Do not expose 8501/8686/8790 publicly"
}
META

echo ""
echo "=== BOOTSTRAP DONE ==="
echo "1. sudo tailscale up --ssh --hostname=demo-relay"
echo "2. Edit /etc/demo-relay.env → DEMO_MAC_GW=100.x.x.x:8501"
echo "3. Optional: close public SSH after Tailscale works"
echo "4. Log: /var/log/demo-relay-health.log"
