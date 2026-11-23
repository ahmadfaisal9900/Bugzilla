# Deployment

One tag push builds the images, deploys the API, chat and dashboard to the host, and rolls back
automatically if the post-deploy smoke query fails.

```
git tag v0.1.0 && git push origin v0.1.0
  └─ .github/workflows/cd.yml
       1. smoke   compose.ci.yaml (fixture bundle, mock LLM) + scripts/smoke.sh
       2. images  api, chat, dashboard → ghcr.io/<owner>/bugzilla-<service>:<tag>  (amd64 + arm64)
       3. deploy  ssh → docker compose pull && up -d → R0 smoke query (0 LLM calls)
                  pass: write .last_good    fail: redeploy the tag in .last_good
```

| Piece | File |
|---|---|
| API image (CPU torch, models baked in, `HF_HUB_OFFLINE=1`, non-root, healthcheck) | `docker/api.Dockerfile` |
| Chat image (`.[ui]` only) | `docker/chat.Dockerfile` |
| Dashboard image | `docker/dashboard.Dockerfile` (dashboard stream) |
| Production stack | `compose.yaml` |
| CI and local smoke stack | `compose.ci.yaml` |
| Local full stack (your bundle and `.env`) | `compose.local.yaml`, `scripts/run_local.ps1` |
| Smoke checks | `scripts/smoke.sh` |
| Model download for CI | `scripts/fetch_models.py` |
| Pipeline | `.github/workflows/cd.yml` |

## Host: Oracle Always Free A1 VM

ARM (Ampere A1), 2 OCPU and 12 GB RAM, free. The API needs about 2 GB; the rest is headroom.
Oracle asks for a card at sign-up to verify identity; Always Free resources are not charged. The
account can belong to any teammate: CD only needs the VM's IP and an SSH key.

### 1. Create the VM (once)

1. Oracle Cloud console → Compute → Instances → Create instance.
2. Image: **Canonical Ubuntu 24.04**. Shape: **VM.Standard.A1.Flex**, 2 OCPU, 12 GB.
   If it says "out of capacity", try another availability domain or retry later.
3. Add your SSH public key, create, and note the public IP.
4. Open ports 8501 (chat) and 8502 (dashboard): Networking → the VCN → Security list →
   Add ingress rules, source `0.0.0.0/0`, TCP. Keep 8000 (API) closed to the internet; the chat
   reaches it inside Docker.

### 2. Prepare the VM (once)

```bash
ssh ubuntu@<public-ip>
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu && exit          # log in again for the group to apply
ssh ubuntu@<public-ip>
# Ubuntu images on OCI also filter with iptables; open the two UI ports there too.
sudo iptables -I INPUT -p tcp --dport 8501 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 8502 -j ACCEPT
sudo netfilter-persistent save
mkdir -p ~/bugzilla/scripts
```

### 3. Copy the serving bundle (from your PC, Git Bash)

The bundle is not in git or in the images. It is copied once, and again whenever it changes:

```bash
scp -r serving_bundle ubuntu@<public-ip>:~/bugzilla/
```

`compose.yaml` mounts it read-only at `/bundle`.

### 4. Create `~/bugzilla/.env` on the VM

Start from this template and fill in the values. Never commit this file.

```dotenv
# Required
SERVING_API_KEY=<long random string: python -c "import secrets; print(secrets.token_urlsafe(32))">
GROQ_API_KEY=<your Groq key>
LLM_PROVIDER=groq

# Optional: tracing and the experiment registry
LANGSMITH_API_KEY=
TRACE_SAMPLE=0.2
TRACE_DAILY_CAP=150
MLFLOW_TRACKING_URI=
MLFLOW_TRACKING_USERNAME=
MLFLOW_TRACKING_PASSWORD=

# Dashboard
DASHBOARD_PASSWORD=<choose one>
DASHBOARD_LAB_ENABLED=false
```

`chmod 600 ~/bugzilla/.env`. `BUNDLE_DIR` and `API_URL` are set by `compose.yaml`.

### 5. Deploy key and GitHub secrets (once)

On your PC, make a key used only by CI:

```bash
ssh-keygen -t ed25519 -f deploy_key -N "" -C "bugzilla-cd"
ssh-copy-id -i deploy_key.pub ubuntu@<public-ip>     # or append it to ~/.ssh/authorized_keys
```

GitHub → the repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | the VM's public IP |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | the whole contents of `deploy_key` (the private key) |

Then delete the local `deploy_key` files or keep them somewhere safe.

### 6. First runs

1. Actions → **cd** → Run workflow, leave "Deploy" unticked. This checks the compose smoke test
   and pushes `sha-<commit>` images without touching the VM. It must be green.
2. Tag and push: `git tag v0.1.0 && git push origin v0.1.0`. This deploys `v0.1.0`, runs the R0
   smoke query on the VM and writes `~/bugzilla/.last_good`.
3. Open `http://<public-ip>:8501`.

## Rollback

Automatic: if the R0 smoke query fails after a deploy, the workflow redeploys the tag stored in
`~/bugzilla/.last_good` and the run is marked failed.

By hand, on the VM:

```bash
cd ~/bugzilla
cat .last_good                                   # the last tag that passed
IMAGE_TAG=v0.1.0 docker compose pull && IMAGE_TAG=v0.1.0 docker compose up -d
```

Any pushed tag works, because every image stays in GHCR (Packages on the repo page).

## Key rotation

| Key | How |
|---|---|
| `SERVING_API_KEY` | Edit `~/bugzilla/.env`, then `IMAGE_TAG=$(cat .last_good) docker compose up -d`. The API and chat both read it from `.env`, so they change together. |
| `GROQ_API_KEY`, `LANGSMITH_API_KEY`, MLflow | Revoke the old key with the provider, put the new one in `.env`, restart as above. |
| Deploy SSH key | Make a new key pair, add the new public key to `~/.ssh/authorized_keys`, update the `DEPLOY_SSH_KEY` secret, run cd once, then remove the old line from `authorized_keys`. |
| GHCR access | Nothing to rotate: the workflow logs in with its own short-lived `GITHUB_TOKEN` and logs out after each pull. |

## Run the whole app locally

With your `serving_bundle/` and `.env` (real data, Groq), either of these starts the API, chat
and dashboard together:

| How | Command | Stop |
|---|---|---|
| Your venv, one PowerShell terminal | `.\scripts\run_local.ps1` (`-NoDashboard` to skip it) | Ctrl+C |
| Docker Desktop, built from this checkout | `docker compose -f compose.local.yaml up --build` | Ctrl+C, then `docker compose -f compose.local.yaml down` |

Chat http://localhost:8501, dashboard http://localhost:8502. The venv needs
`pip install ".[serving,ui,dashboard]"` once. The Docker build needs `models/` (run
`python scripts/fetch_models.py` if it is missing) and takes a while the first time.

## Test locally first

Docker Desktop, from the repo root in Git Bash:

```bash
python scripts/fetch_models.py      # only if models/ is missing
docker compose -f compose.ci.yaml up --build -d
SMOKE_DASHBOARD=0 bash scripts/smoke.sh
docker compose -f compose.ci.yaml down -v
```

The CI stack builds a synthetic 20-bug bundle and uses the mock LLM, so it needs no keys. Drop
`SMOKE_DASHBOARD=0` and add `--profile dashboard` to `up` once `docker/dashboard.Dockerfile`
exists.

## Alternative host: your PC with a Cloudflare tunnel

Run `compose.yaml` on your PC (`IMAGE_TAG=v0.1.0 docker compose up -d`) and publish the chat
with `cloudflared tunnel --url http://localhost:8501`. Build for `linux/amd64` only (change
`PLATFORMS` in `cd.yml`). The PC must stay on, and the SSH deploy step
needs the PC reachable over SSH (for example through a Cloudflare Access SSH tunnel), so most
people deploy by hand there with the same two commands.
