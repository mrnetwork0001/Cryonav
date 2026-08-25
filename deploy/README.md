# Deploying Cryonav to a VPS

One command from a machine that has the repo, your `.env`, and SSH access:

```bash
./deploy/deploy.sh user@your-vps-ip              # HTTP on the bare IP
./deploy/deploy.sh user@your-vps-ip cryonav.example.com   # HTTPS via Caddy auto-TLS
```

Requirements on the VPS: Debian/Ubuntu, `sudo`, ports 80/443 open. **No Node, no git
credentials** - the frontend is built locally and shipped as static files.

What lands where:

| Path | Contents |
|---|---|
| `/opt/cryonav` | the app tree (rsynced; `cryonav` system user) |
| `/etc/cryonav/env` | `FORTYGUARD_API_KEY` - root-owned, 0600, copied from your local `.env` **only if absent**; never overwritten, never in the repo |
| `/etc/systemd/system/cryonav-api.service` | uvicorn on `127.0.0.1:8008`, 2 workers |
| `/etc/systemd/system/cryonav-calibrate.{service,timer}` | daily 05:30 UTC FortyGuard pull (`env_params` + `heatmap`), then API restart to load it |
| `/etc/caddy/Caddyfile` | serves `frontend/dist`, proxies `/api/*`, `/docs*`, `/openapi.json` |

Design notes:

- **No request-time upstream calls.** Public traffic can never burn FortyGuard quota: the
  API serves the calibrated field; upstream is touched only by the daily timer (a handful
  of async jobs per day).
- Routing: `/` landing page, `/app` dashboard (SPA fallback), `/docs` FastAPI swagger.
- Re-running `deploy.sh` is the update path: rsync, reinstall units, restart. State that
  survives updates: `/etc/cryonav/env` and the current `data/calibration/` (shipped fresh
  from the repo each deploy, then refreshed daily by the timer).

Operations:

```bash
ssh user@vps sudo systemctl status cryonav-api caddy cryonav-calibrate.timer
ssh user@vps sudo systemctl start cryonav-calibrate.service   # refresh calibration now
ssh user@vps sudo journalctl -u cryonav-api -n 50             # backend logs
```
