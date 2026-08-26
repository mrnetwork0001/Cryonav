# Deploying Cryonav to a VPS

There are two paths, and **which one you want depends on whether the box already runs
something on ports 80/443.**

| Situation | Path |
|---|---|
| Dedicated box, nothing on :80/:443 | `./deploy/deploy.sh user@host domain` - installs Caddy and manages the whole edge |
| **Box already running other services** | the manual path below - nginx keeps the edge, Cryonav is added beside it |

cryonav.xyz is the second case: nginx 1.24 owns the edge and serves other vhosts alongside
Cryonav. Everything here is written so that a Cryonav failure cannot reach them.

Requirements on the VPS: Debian/Ubuntu, `sudo`, ports 80/443 reachable. **No Node, no git
credentials** - the frontend is built locally and shipped as static files.

## What lands where

| Path | Contents |
|---|---|
| `/opt/cryonav` | the app tree (`cryonav` system user) |
| `/opt/cryonav/frontend/dist` | the built site - **nginx serves this directly**, so a frontend update is a file copy, not a vhost change |
| `/etc/cryonav/env` | `FORTYGUARD_API_KEY`, `CRYONAV_NTFY_TOPIC` - root-owned, 0600, **never overwritten if present**, never in the repo |
| `/etc/systemd/system/cryonav-api.service` | uvicorn on `127.0.0.1:8008`, **1 worker**, `MemoryMax=1200M`, `TasksMax=256` |
| `/etc/systemd/system/cryonav-calibrate.{service,timer}` | daily 05:30 UTC FortyGuard pull (`env_params` + `heatmap`), then API restart to load it |
| `/etc/nginx/sites-available/cryonav` | written by `nginx-publish.sh`; additive, touches no other vhost |

## Routing

- `/` landing, `/app` dashboard, `/docs` **the product manual** - all served by the SPA
- `/api/*` proxied to `127.0.0.1:8008`
- `/api/docs` Swagger, `/api/openapi.json` the schema. `/docs` has not been Swagger since the
  manual took that path; anything still proxying `/docs*` to the backend shadows a real page
  with a 404.

## Updating an existing install (the nginx host)

The vhost does not change when only the app changes, so **this touches nginx not at all.**
Run `nginx-publish.sh` only when the vhost itself needs rewriting.

```bash
# 0. Confirm what is running now, and that there is room to back up.
systemctl is-active cryonav-api nginx
sudo ss -tlnp | grep -E ':(80|443|8008)\b'
df -h /opt | tail -1

# 1. Back up the current tree and the unit. This is the rollback.
TS=$(date +%s)
sudo cp -a /opt/cryonav /opt/cryonav.bak.$TS
sudo cp -a /etc/systemd/system/cryonav-api.service /root/cryonav-api.service.$TS.bak
echo "backup: /opt/cryonav.bak.$TS"

# 2. Fetch the release and check the archive before it goes anywhere near /opt.
curl -fsSL https://github.com/mrnetwork0001/Cryonav/releases/latest/download/cryonav-bundle.tar.gz \
  -o /tmp/cryonav-bundle.tar.gz
tar tzf /tmp/cryonav-bundle.tar.gz >/dev/null && echo "archive intact"
rm -rf /tmp/Cryonav && tar xzf /tmp/cryonav-bundle.tar.gz -C /tmp
test -f /tmp/Cryonav/frontend/dist/index.html && echo "frontend present"

# 3. Sync into place. rsync --delete, NOT cp -a: cp merges, so a file deleted upstream
#    would live on the server forever. The excludes are the state that must survive:
#    the venv is built on the server, and calibration is refreshed there daily.
sudo rsync -a --delete \
  --exclude 'backend/.venv' \
  --exclude 'data/calibration' \
  /tmp/Cryonav/ /opt/cryonav/
sudo chown -R cryonav:cryonav /opt/cryonav

# 4. Install the unit only if it changed, then reload systemd.
sudo cp /opt/cryonav/deploy/cryonav-api.service /etc/systemd/system/cryonav-api.service
sudo systemctl daemon-reload

# 5. Restart ONLY our unit, then wait for it to actually answer.
#    `systemctl restart` returns success for a service that never comes up, so gate on health.
sudo systemctl restart cryonav-api
for i in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8008/api/v1/health >/dev/null 2>&1 && { echo "API up"; break; }
  sleep 2
  [ "$i" = 20 ] && echo "API DID NOT COME UP - see rollback below"
done

# 6. Prove the new build is the one being served.
curl -s https://cryonav.xyz/api/v1/facts | python3 -m json.tool | grep -E '"tests"|assumed_constants'
systemctl show cryonav-api -p MemoryMax -p TasksMax

# 7. Prove nothing else was disturbed.
systemctl is-active nginx
systemctl --failed --no-legend
pm2 list 2>/dev/null | head
```

Nginx is never restarted, and never reloaded, by this procedure. `index.html` is served
`no-cache` and assets are content-hashed, so browsers pick the new build up immediately with
no cache purge.

### Rollback

```bash
sudo systemctl stop cryonav-api
sudo mv /opt/cryonav /opt/cryonav.failed.$(date +%s)
sudo mv /opt/cryonav.bak.$TS /opt/cryonav              # $TS from step 1
sudo cp /root/cryonav-api.service.$TS.bak /etc/systemd/system/cryonav-api.service
sudo systemctl daemon-reload && sudo systemctl start cryonav-api
curl -fsS http://127.0.0.1:8008/api/v1/health && echo " restored"
```

The backup is a full copy including the venv, so this is a true restore rather than a
re-install. Delete `/opt/cryonav.bak.*` once the new version has run for a day.

## Design notes

- **No request-time upstream calls by default.** Public traffic cannot burn FortyGuard quota:
  the API serves the calibrated field, and upstream is touched only by the daily timer.
  `prefer_live=true` opts a single request in, capped at four points.
- **One worker, deliberately.** uvicorn workers are separate processes, so a second one
  doubled resident memory for an I/O-light workload and ran the startup calibration hook
  twice - two sets of upstream jobs, and two unsynchronised writers on the same files.
- **The unit is capped.** `MemoryMax`/`TasksMax` exist so a Cryonav fault is paid for by
  Cryonav's cgroup rather than by whatever else has the largest RSS on the box.
- State that survives an update: `/etc/cryonav/env` and `data/calibration/`.

## Operations

```bash
sudo systemctl status cryonav-api cryonav-calibrate.timer
sudo systemctl start cryonav-calibrate.service   # refresh calibration now
sudo journalctl -u cryonav-api -n 50             # backend logs
sudo systemctl show cryonav-api -p MemoryCurrent # memory in use right now
```
