# Oracle Cloud Always Free VPS — relay node for demo stack

**Cost:** $0/month (Always Free: up to **2 OCPU / 12 GB RAM** Ampere A1, or 2× AMD Micro)  
**You must sign up yourself:** [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) (card verify, no charge if stay in Always Free limits)

## What this VPS is for (not your AI brain)

| On Mac (keep) | On VPS (optional relay) |
|---------------|-------------------------|
| LM Studio, :8501, Jarvis :8686, FIELD :8790 | TradingView webhook inbox |
| IB / Aether / Aster | Tailscale subnet router / funnel |
| LaunchAgent KeepAlive | Uptime probe → Telegram |

**Do not** expose :8501 / :8686 / :8790 on public internet.

## 1. Create instance (Oracle Console)

1. Sign up → pick **home region** (US: Phoenix / San Jose; Asia: Tokyo if available)
2. **Compute → Instances → Create**
3. Shape: **Ampere A1 Flex** — **1 OCPU, 6 GB RAM** (leaves headroom under 2/12 cap)
4. Image: **Ubuntu 24.04** (aarch64)
5. Boot volume: **50 GB** (within 200 GB free block storage)
6. **Networking:** assign public IPv4
7. **SSH key:** paste your Mac public key (`cat ~/.ssh/id_ed25519.pub`)
8. Create

## 2. Open port 22 only (Security List / NSG)

- Ingress: TCP 22 from your IP (or use **OCI Bastion** and close 22 later)
- After Tailscale: **close public 22**, SSH via `100.x.x.x` only

## 3. Bootstrap (first SSH)

```bash
ssh ubuntu@YOUR_PUBLIC_IP
curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/...  # or scp from Mac:

# From Mac (after clone):
scp scripts/vps/oracle_free_bootstrap.sh ubuntu@YOUR_IP:/tmp/
ssh ubuntu@YOUR_IP 'sudo bash /tmp/oracle_free_bootstrap.sh'
```

Or paste script from `scripts/vps/oracle_free_bootstrap.sh`.

## 4. Tailscale (recommended)

On VPS (script installs tailscale):

```bash
sudo tailscale up --ssh --advertise-tags=tag:demo-relay
```

On Mac: approve in [Tailscale admin](https://login.tailscale.com/admin/machines).  
Then SSH: `ssh ubuntu@demo-relay` (MagicDNS name you pick).

## 5. TradingView webhook (optional)

Mac side (no VPS needed if Mac online):

```bash
bash scripts/tv_tunnel_cloudflared.sh   # cloudflare quick tunnel
```

VPS side: forward HTTPS → Tailscale → Mac `:8000` webhook (configure after Tailscale mesh).

## 6. Verify

```bash
systemctl is-active demo-relay-health.timer
tailscale status
sudo ufw status
```

## Limits (2026)

Oracle cut Always Free Ampere to **2 OCPU + 12 GB RAM** total per tenancy.  
Use **one** small instance (1 OCPU / 6 GB), not two big ones.

## Security

- Never paste root passwords in chat or commit `.env` to git
- Use SSH keys only; enable `fail2ban` + `unattended-upgrades` (bootstrap does this)
- Join Tailscale; close public ports except 443 if you add Caddy later
