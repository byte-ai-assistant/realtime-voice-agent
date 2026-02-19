#!/bin/bash
# Deploy Real-Time Voice AI Agent to Google Cloud Platform

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${REGION}-a"
INSTANCE_NAME="voice-agent-vm"
MACHINE_TYPE="e2-standard-2"
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"

echo "🚀 Deploying Real-Time Voice AI Agent to GCP"
echo ""
echo "Configuration:"
echo "  Project: $PROJECT_ID"
echo "  Region: $REGION"
echo "  Zone: $ZONE"
echo "  Instance: $INSTANCE_NAME"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI not found. Please install it first:"
    echo "   https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Set project
echo "🔧 Setting GCP project..."
gcloud config set project $PROJECT_ID
echo ""

# Create VM instance
echo "🔧 Creating VM instance..."
gcloud compute instances create $INSTANCE_NAME \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --image-family=$IMAGE_FAMILY \
    --image-project=$IMAGE_PROJECT \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-ssd \
    --tags=http-server,https-server \
    --metadata-from-file startup-script=scripts/startup-script.sh \
    || echo "Instance may already exist"

echo "✅ VM instance created"
echo ""

# Create firewall rules
echo "🔧 Creating firewall rules..."
gcloud compute firewall-rules create allow-voice-agent \
    --allow=tcp:8000 \
    --target-tags=http-server \
    --description="Allow traffic to voice agent" \
    || echo "Firewall rule may already exist"

echo "✅ Firewall rules created"
echo ""

# Get external IP
echo "📍 Getting external IP..."
EXTERNAL_IP=$(gcloud compute instances describe $INSTANCE_NAME \
    --zone=$ZONE \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo "✅ External IP: $EXTERNAL_IP"
echo ""

# Wait for instance to be ready
echo "⏳ Waiting for instance to be ready (this may take 2-3 minutes)..."
sleep 120

# SSH and setup
echo "🔧 Setting up application on VM..."
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command="
    cd /opt/voice-agent && \
    sudo docker-compose up -d
" || echo "Manual setup required"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "1. Configure Twilio webhook to: http://$EXTERNAL_IP:8000/webhook/voice"
echo "2. Set WebSocket URL in .env: wss://$EXTERNAL_IP/ws/media"
echo "3. Test the deployment: curl http://$EXTERNAL_IP:8000/health"
echo "4. Make a test call to your Twilio number"
echo ""
echo "🔗 Useful commands:"
echo "  SSH: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo "  Logs: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='cd /opt/voice-agent && docker-compose logs -f'"
echo "  Stop: gcloud compute instances stop $INSTANCE_NAME --zone=$ZONE"
echo "  Start: gcloud compute instances start $INSTANCE_NAME --zone=$ZONE"
echo ""
