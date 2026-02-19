# Deployment Guide

Complete guide for deploying the Real-Time Voice AI Agent to production.

---

## Prerequisites

Before deploying, ensure you have:

1. ✅ All API keys obtained and tested locally
2. ✅ Google Cloud account with billing enabled
3. ✅ Twilio account with phone number
4. ✅ Domain name (optional, but recommended for SSL)
5. ✅ `gcloud` CLI installed and authenticated

---

## Deployment Options

### Option 1: Google Cloud VM (Recommended)

**Pros:**
- Full control over environment
- Easy to debug and monitor
- Cost-effective (~$50/month)
- Fast deployment

**Cons:**
- Manual SSL certificate setup
- Need to manage VM updates

### Option 2: Google Cloud Run

**Pros:**
- Fully managed
- Auto-scaling
- HTTPS out of the box

**Cons:**
- WebSocket connections can be tricky
- Potentially higher cost at scale
- Less control over environment

**This guide covers Option 1 (VM deployment).**

---

## Step 1: Prepare Google Cloud

### 1.1 Install gcloud CLI

```bash
# macOS
brew install google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash

# Windows
# Download from: https://cloud.google.com/sdk/docs/install
```

### 1.2 Authenticate

```bash
gcloud auth login
gcloud auth application-default login
```

### 1.3 Create Project

```bash
# Create new project
gcloud projects create voice-agent-prod --name="Voice AI Agent"

# Set as active project
gcloud config set project voice-agent-prod

# Enable billing (required)
# Go to: https://console.cloud.google.com/billing
```

### 1.4 Enable Required APIs

```bash
gcloud services enable compute.googleapis.com
gcloud services enable container.googleapis.com
```

---

## Step 2: Deploy VM

### 2.1 Automated Deployment

```bash
# Set environment variables
export GCP_PROJECT_ID=voice-agent-prod
export GCP_REGION=us-central1

# Run deployment script
./scripts/deploy-gcp.sh
```

The script will:
1. Create VM instance (e2-standard-2, 2 vCPU, 8GB RAM)
2. Configure firewall rules
3. Install Docker and Docker Compose
4. Set up application directory
5. Return external IP address

### 2.2 Manual Deployment (if script fails)

```bash
# Create VM instance
gcloud compute instances create voice-agent-vm \
    --zone=us-central1-a \
    --machine-type=e2-standard-2 \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-ssd \
    --tags=http-server,https-server

# Create firewall rule
gcloud compute firewall-rules create allow-voice-agent \
    --allow=tcp:8000 \
    --target-tags=http-server

# Get external IP
gcloud compute instances describe voice-agent-vm \
    --zone=us-central1-a \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

---

## Step 3: Configure VM

### 3.1 SSH into VM

```bash
gcloud compute ssh voice-agent-vm --zone=us-central1-a
```

### 3.2 Install Docker

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install -y docker-compose

# Verify installation
docker --version
docker-compose --version
```

### 3.3 Upload Application Files

**From your local machine:**

```bash
# Create archive
cd realtime-voice-agent
tar -czf voice-agent.tar.gz \
    src/ \
    knowledge/ \
    config/ \
    docker/ \
    requirements.txt \
    .env.example

# Copy to VM
gcloud compute scp voice-agent.tar.gz voice-agent-vm:/tmp/ \
    --zone=us-central1-a

# SSH and extract
gcloud compute ssh voice-agent-vm --zone=us-central1-a

sudo mkdir -p /opt/voice-agent
sudo tar -xzf /tmp/voice-agent.tar.gz -C /opt/voice-agent
cd /opt/voice-agent
```

### 3.4 Configure Environment

```bash
# Create .env file
cd /opt/voice-agent
cp .env.example .env
nano .env  # Edit and add your API keys
```

**Required variables:**
```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890

# Deepgram
DEEPGRAM_API_KEY=your_deepgram_key

# ElevenLabs
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_key

# OpenAI (optional)
OPENAI_API_KEY=your_openai_key

# WebSocket URL (use your VM's external IP)
WEBSOCKET_URL=ws://YOUR_EXTERNAL_IP:8000/ws/media
```

---

## Step 4: Start Application

### 4.1 Build and Run with Docker Compose

```bash
cd /opt/voice-agent

# Build image
sudo docker-compose -f docker/docker-compose.yml build

# Start services
sudo docker-compose -f docker/docker-compose.yml up -d

# Check status
sudo docker-compose -f docker/docker-compose.yml ps

# View logs
sudo docker-compose -f docker/docker-compose.yml logs -f
```

### 4.2 Verify Deployment

```bash
# Health check
curl http://localhost:8000/health

# From outside VM (use external IP)
curl http://EXTERNAL_IP:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "checks": {
    "knowledge_base": true,
    "active_calls": 0,
    "api_keys": {
      "anthropic": true,
      "elevenlabs": true,
      "deepgram": true,
      "twilio": true
    }
  }
}
```

---

## Step 5: Configure Twilio

### 5.1 Get Twilio Phone Number

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to **Phone Numbers** → **Buy a Number**
3. Select a number and purchase it

### 5.2 Configure Webhook

1. Go to your phone number settings
2. Under **Voice & Fax** → **A Call Comes In**:
   - Set to: `Webhook`
   - URL: `http://YOUR_EXTERNAL_IP:8000/webhook/voice`
   - Method: `HTTP POST`
3. Click **Save**

### 5.3 Update WebSocket URL

Edit `.env` on VM:
```bash
WEBSOCKET_URL=ws://YOUR_EXTERNAL_IP:8000/ws/media
```

Restart container:
```bash
sudo docker-compose -f docker/docker-compose.yml restart
```

---

## Step 6: Test Deployment

### 6.1 Make Test Call

1. Call your Twilio phone number
2. Listen for greeting: "Hello! Thanks for calling ByteAI..."
3. Say: "What can you help me with?"
4. Verify AI responds appropriately

### 6.2 Test Tools

**Book Appointment:**
- Say: "I'd like to book an appointment for tomorrow at 2pm"
- Provide name and phone when asked
- Verify confirmation

**Check Appointment:**
- Say: "Check my appointment status"
- Provide phone number
- Verify retrieval

**Escalate:**
- Say: "I need to speak with a human"
- Verify escalation message

---

## Step 7: Production Hardening

### 7.1 Enable HTTPS (Recommended)

**Option A: Use Cloudflare (Easiest)**

1. Add your domain to Cloudflare
2. Create A record pointing to VM IP
3. Enable Cloudflare proxy (orange cloud)
4. Update Twilio webhook to `https://yourdomain.com/webhook/voice`

**Option B: Use Let's Encrypt**

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot certonly --standalone -d yourdomain.com

# Configure nginx as reverse proxy
# (See nginx config example below)
```

### 7.2 Set Up Monitoring

**Install Prometheus:**

```bash
# Add Prometheus exporter to application
# Expose metrics on /metrics endpoint

# Install Prometheus
sudo docker run -d \
    --name prometheus \
    -p 9090:9090 \
    -v /opt/prometheus.yml:/etc/prometheus/prometheus.yml \
    prom/prometheus
```

**Create prometheus.yml:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'voice-agent'
    static_configs:
      - targets: ['voice-agent:8000']
```

### 7.3 Set Up Logging

```bash
# View logs
sudo docker-compose -f docker/docker-compose.yml logs -f

# Set up log rotation
sudo nano /etc/logrotate.d/voice-agent
```

**logrotate config:**
```
/opt/voice-agent/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 7.4 Auto-Restart on Failure

```bash
# Create systemd service
sudo nano /etc/systemd/system/voice-agent.service
```

**Service file:**
```ini
[Unit]
Description=Voice AI Agent
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/voice-agent
ExecStart=/usr/bin/docker-compose -f docker/docker-compose.yml up -d
ExecStop=/usr/bin/docker-compose -f docker/docker-compose.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Enable service:
```bash
sudo systemctl enable voice-agent
sudo systemctl start voice-agent
```

---

## Maintenance

### Start/Stop VM

```bash
# Stop VM (saves costs when not in use)
gcloud compute instances stop voice-agent-vm --zone=us-central1-a

# Start VM
gcloud compute instances start voice-agent-vm --zone=us-central1-a
```

### Update Application

```bash
# SSH into VM
gcloud compute ssh voice-agent-vm --zone=us-central1-a

# Pull latest changes (if using git)
cd /opt/voice-agent
git pull

# Rebuild and restart
sudo docker-compose -f docker/docker-compose.yml down
sudo docker-compose -f docker/docker-compose.yml up -d --build
```

### View Logs

```bash
# Real-time logs
sudo docker-compose -f docker/docker-compose.yml logs -f

# Last 100 lines
sudo docker-compose -f docker/docker-compose.yml logs --tail=100

# Specific service
sudo docker-compose -f docker/docker-compose.yml logs -f voice-agent
```

### Backup Data

```bash
# Backup appointments and knowledge base
cd /opt/voice-agent
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# Download to local machine
gcloud compute scp voice-agent-vm:/opt/voice-agent/backup-*.tar.gz ./ \
    --zone=us-central1-a
```

---

## Troubleshooting

### Issue: Can't SSH into VM

```bash
# Check VM is running
gcloud compute instances list

# Check firewall rules
gcloud compute firewall-rules list

# Try serial console
gcloud compute connect-to-serial-port voice-agent-vm --zone=us-central1-a
```

### Issue: Container won't start

```bash
# Check logs
sudo docker-compose -f docker/docker-compose.yml logs

# Check if port is already in use
sudo lsof -i :8000

# Rebuild from scratch
sudo docker-compose -f docker/docker-compose.yml down -v
sudo docker-compose -f docker/docker-compose.yml up -d --build
```

### Issue: Calls not connecting

1. **Check webhook URL:**
   ```bash
   curl http://EXTERNAL_IP:8000/webhook/voice -X POST
   ```

2. **Check Twilio logs:**
   - Go to Twilio Console → Monitor → Logs
   - Look for webhook errors

3. **Verify WebSocket URL:**
   ```bash
   # In .env file
   echo $WEBSOCKET_URL
   ```

4. **Check firewall:**
   ```bash
   gcloud compute firewall-rules list | grep voice-agent
   ```

---

## Cost Optimization

### Reduce VM Costs

```bash
# Use preemptible VMs (80% cheaper, but can be terminated)
gcloud compute instances create voice-agent-vm \
    --preemptible \
    ...

# Use smaller machine type during testing
--machine-type=e2-micro  # ~$7/month
```

### Monitor API Usage

- Set up billing alerts in GCP
- Monitor Anthropic usage at console.anthropic.com
- Check ElevenLabs quota at elevenlabs.io
- Monitor Twilio usage at console.twilio.com

---

## Security Checklist

- [ ] All API keys in environment variables (not in code)
- [ ] Firewall allows only necessary ports (8000, 22, 80, 443)
- [ ] SSH key-based authentication enabled
- [ ] Regular security updates (`sudo apt-get update && sudo apt-get upgrade`)
- [ ] HTTPS enabled (if using domain)
- [ ] Twilio webhook signature verification enabled
- [ ] Rate limiting configured
- [ ] Logs don't contain sensitive data

---

## Next Steps

1. **Set up monitoring** - Prometheus + Grafana dashboard
2. **Configure alerts** - Email/SMS when errors occur
3. **Add custom knowledge** - Update `knowledge/sample_kb.json`
4. **Customize voice** - Try different ElevenLabs voices
5. **Scale horizontally** - Add load balancer for multiple VMs

---

## Support

If you encounter issues:

1. Check logs: `docker-compose logs -f`
2. Verify health: `curl http://localhost:8000/health`
3. Review Twilio webhook logs
4. Check GitHub Issues
5. Contact support@byteai.com

---

**Deployment complete! 🚀 Your voice AI agent is live!**
