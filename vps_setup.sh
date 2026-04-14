#!/bin/bash

# VPS Setup Script for Aria Selfbot
# Run as root or with sudo

echo "Setting up VPS for Aria..."

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3 python3-pip python3-venv tmux htop logrotate nginx fail2ban squid ufw cron nodejs npm

# Create bot user
sudo useradd -m -s /bin/bash aria
sudo usermod -aG sudo aria  # Optional, for sudo access

# Set up directory
sudo mkdir -p /home/aria/Aria
sudo chown aria:aria /home/aria/Aria

# Copy code (assuming it's in current dir)
# Replace with actual copy command
# cp -r /path/to/code /home/aria/Aria

# Set up virtual environment
sudo -u aria bash -c "cd /home/aria/Aria && python3 -m venv .venv"
sudo -u aria bash -c "cd /home/aria/Aria && .venv/bin/pip install curl-cffi websocket-client aiohttp websockets flask colorama requests"

# Install PM2
sudo npm install -g pm2

# Set up PM2 for the bot
sudo -u aria bash -c "cd /home/aria/Aria && pm2 start main.py --name aria --interpreter /home/aria/Aria/.venv/bin/python3 --cwd /home/aria/Aria"
sudo -u aria bash -c "pm2 save"
sudo -u aria bash -c "pm2 startup"

# Optional systemd for PM2 (if needed)
# cat <<EOF | sudo tee /etc/systemd/system/aria.service
# [Unit]
# Description=Aria Bot
# After=network.target
# 
# [Service]
# User=aria
# ExecStart=/usr/bin/pm2 start aria
# Restart=always
# 
# [Install]
# WantedBy=multi-user.target
# EOF
# sudo systemctl daemon-reload
# sudo systemctl enable aria
# sudo systemctl start aria

# Firewall
sudo ufw --force enable
sudo ufw allow 22/tcp  # SSH
sudo ufw allow 8080/tcp  # Webpanel
sudo ufw allow 3128/tcp  # Squid proxy

# Squid proxy
sudo systemctl enable squid
sudo systemctl start squid

# Nginx for webpanel
cat <<EOF | sudo tee /etc/nginx/sites-available/aria
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/aria /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Cron for updates
echo "0 2 * * * cd /home/aria/Aria && git pull" | sudo crontab -u aria -

# Logrotate
cat <<EOF | sudo tee /etc/logrotate.d/aria
/home/aria/Aria/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF

# Fail2Ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Add workspace root to PYTHONPATH
export PYTHONPATH="/workspaces/Aria/Aria:$PYTHONPATH"

echo "Setup complete. Bot is running via systemd. Access webpanel at http://your-vps-ip"