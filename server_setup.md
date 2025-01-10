# BossDB RAG Server Setup Guide

This guide details how to set up the BossDB RAG chatbot on an Ubuntu EC2 instance on AWS.

## Prerequisites

- Ubuntu EC2 instance (recommended: t3.medium or higher)
- Domain name pointing to your EC2 instance
- AWS credentials
- GitHub token

## 1. Initial Server Setup

First, update the system and install required dependencies:

```bash
# Update system
sudo apt update
sudo apt upgrade -y

# Add repositories
sudo add-apt-repository universe
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update

# Install Python and development tools
sudo apt install -y python3.12 python3.12-venv python3.12-distutils
sudo apt-get install -y build-essential python3-dev
```

## 2. Clone and Configure Repository

```bash
# Clone repository
git clone https://github.com/aplbrain/bossdb-rag-chatbot.git
cd bossdb-rag-chatbot

# Create and secure environment file
touch .env
chmod 600 .env

# Add the following to .env (replace with your values):
# AWS_ACCESS_KEY_ID=your_key_here
# AWS_SECRET_ACCESS_KEY=your_secret_here
# AWS_REGION=your_region
# GITHUB_TOKEN=your_token

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If `requirments.txt` does not work, attempt to use `strict_requirements.txt`.

## 3. Install and Configure MongoDB

```bash
# Install Docker
sudo snap install docker
sudo chmod 666 /var/run/docker.sock

# Run MongoDB container
docker run -d \
    --name mongodb \
    -p 27017:27017 \
    -e MONGO_INITDB_ROOT_USERNAME=admin \
    -e MONGO_INITDB_ROOT_PASSWORD=password123 \
    mongodb/mongodb-community-server:latest
```

If encountering the following error: `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Post "http://%2Fvar%2Frun%2Fdocker.sock/v1.47/containers/mongodb/start": dial unix /var/run/docker.sock: connect: permission denied`, utilize `sudo chmod 666 /var/run/docker.sock` to modify the permission so the command will no longer be denied.

## 4. Install and Configure Nginx

```bash
# Install Nginx and Certbot
sudo apt install -y nginx python3-certbot-nginx

# Stop Nginx for certificate setup
sudo systemctl stop nginx

# Create Nginx configuration
sudo nano /etc/nginx/conf.d/your-domain.conf

# Add the following configuration (replace your-domain):
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    ssl_certificate /etc/letsencrypt/live/your-domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain/privkey.pem;
    server_name your-domain;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}

# Set up SSL certificate
sudo certbot certonly --standalone --debug -d your-domain

# Start Nginx
sudo systemctl start nginx
sudo systemctl restart nginx
```

## 5. Setup Startup Script

The repository includes a `start_bossdb_rag.sh` script. Review and modify the directory path if needed:

```bash
# Check the path in start_bossdb_rag.sh
cd /home/ubuntu/bossdb-rag-chatbot  # Modify this line if your installation is in a different location
```

Make the script executable:
```bash
chmod +x start_bossdb_rag.sh
```

The script handles:
- Loading environment variables from `.env`
- Starting MongoDB with appropriate permissions
- Activating the virtual environment
- Starting the Chainlit server with logging

Inspect the script to confirm it matches your setup:
```bash
cat start_bossdb_rag.sh
```

## 6. Configure Auto-start and Daily Reboot

Set up crontab for automatic startup and daily system reboot:

```bash
sudo crontab -e

# Add these lines:
@reboot sleep 30 && /home/ubuntu/bossdb-rag-chatbot/start_bossdb_rag.sh
0 0 * * * /sbin/shutdown -r now
```

Modify path to `start_bossdb_rag.sh` as needed.

## 7. Final Steps

1. Start the services manually first time:
```bash
./start_bossdb_rag.sh
```

2. Monitor the logs:
```bash
tail -f startup.log
```

## Maintenance

- Check logs: `tail -f startup.log`
- Restart service: `sudo reboot`
- Monitor MongoDB: `docker logs mongodb`
- Check Nginx status: `sudo systemctl status nginx`

## Security Notes

- Keep `.env` file secure and never commit it to version control
- Regularly update system packages
- Monitor EC2 security groups and firewall rules
- Keep SSL certificates up to date

## Troubleshooting

If the service fails to start:

1. Check logs in `startup.log`
2. Verify MongoDB is running: `docker ps`
3. Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`
4. Ensure all environment variables are properly set
