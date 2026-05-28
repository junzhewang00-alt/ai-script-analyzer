#!/bin/bash
set -e
cd /home/ai-script-analyzer
git pull
sudo systemctl restart ai-analyzer
echo "已更新并重启服务"
