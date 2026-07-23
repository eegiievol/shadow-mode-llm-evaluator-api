# Deploying to a DigitalOcean Droplet

The service runs on a plain Ubuntu Droplet and calls the Serverless Inference
API over the public internet using a **Model Access Key**. No VPC or private
networking is required — the Droplet only needs outbound HTTPS (open by
default) plus an inbound rule for the app port.

```
[ client ] --HTTP:8000--> [ Droplet: FastAPI (systemd) ] --HTTPS + Bearer key--> inference.do-ai.run
```

## Provisioning (doctl)

```bash
# Authenticate
doctl auth init -t <PERSONAL_ACCESS_TOKEN>

# Register your SSH public key
doctl compute ssh-key import shadow-deploy-key --public-key-file ~/.ssh/id_ed25519.pub

# Create the Droplet (Ubuntu 24.04, 1GB)
doctl compute droplet create shadow-evaluator \
  --image ubuntu-24-04-x64 --size s-1vcpu-1gb --region nyc1 \
  --ssh-keys <KEY_ID> --tag-name shadow-evaluator --wait

# Firewall: allow SSH + app port, all outbound
doctl compute firewall create --name shadow-evaluator-fw --tag-names shadow-evaluator \
  --inbound-rules "protocol:tcp,ports:22,address:0.0.0.0/0 protocol:tcp,ports:8000,address:0.0.0.0/0" \
  --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0 protocol:udp,ports:all,address:0.0.0.0/0"
```

## Deploy (on the Droplet)

```bash
apt-get update && apt-get install -y python3-venv python3-pip git
useradd --system --create-home --shell /usr/sbin/nologin appuser
git clone https://github.com/eegiievol/shadow-mode-llm-evaluator-api.git /opt/shadow-evaluator
cd /opt/shadow-evaluator
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# Secrets: create /opt/shadow-evaluator/.env from .env.example and set
# DO_INFERENCE_API_KEY. Lock it down:
chmod 600 .env && chown -R appuser:appuser /opt/shadow-evaluator

# Install and start the service
cp deploy/shadow-evaluator.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now shadow-evaluator
```

## Verify

```bash
curl http://<DROPLET_IP>:8000/healthz
curl -X POST http://<DROPLET_IP>:8000/v1/chat -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Reply ONLY {\"action\":\"buy\"}"}]}'
curl http://<DROPLET_IP>:8000/metrics
```

## Production hardening (beyond this demo)

- **Auth**: the app port is currently open to the world with no authentication —
  anyone who finds the IP can spend your inference credits. Restrict the inbound
  firewall to your IP, and/or put an API key / reverse proxy in front.
- **TLS**: terminate HTTPS with nginx + Let's Encrypt (or a DO Load Balancer).
- **Secrets**: prefer a secrets manager or systemd credentials over a plaintext
  `.env` for real production.

## Tear down (stop billing)

```bash
doctl compute droplet delete shadow-evaluator -f
doctl compute firewall delete <FIREWALL_ID> -f
```
