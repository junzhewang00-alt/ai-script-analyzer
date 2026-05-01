#!/bin/bash
# ============================================================
#  AI 短剧剧本分析器 — 云服务器一键部署脚本
#  适用: Alibaba Cloud Linux 3 / CentOS 8+ / RHEL 8+
#  用法: chmod +x deploy.sh && ./deploy.sh
# ============================================================
set -e

# ---- 配置区（部署前修改这里）----
API_KEY="sk-你的真实api-key"
APP_DIR="/home/ai-script-analyzer"
REPO_URL="https://github.com/junzhewang00-alt/ai-script-analyzer.git"
# -----------------------------------

echo "=== 1/7 安装系统依赖 ==="
sudo dnf install -y python3 python3-pip python3-devel nginx git

echo "=== 2/7 克隆项目 ==="
sudo rm -rf "$APP_DIR"
sudo git clone "$REPO_URL" "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"
cd "$APP_DIR"

echo "=== 3/7 创建 Python 虚拟环境 ==="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools
pip install -r requirements.txt

echo "=== 4/7 创建 .env 配置文件 ==="
APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cat > .env << ENVEOF
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=$API_KEY
LLM_MODEL=deepseek-chat
FLASK_SECRET_KEY=$APP_KEY
ENVEOF
echo ".env 已创建 (FLASK_SECRET_KEY=$APP_KEY)"

echo "=== 5/7 创建 systemd 服务 ==="
sudo tee /etc/systemd/system/ai-analyzer.service > /dev/null << UNITEOF
[Unit]
Description=AI Script Analyzer
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py --prod
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNITEOF

sudo systemctl daemon-reload
sudo systemctl enable ai-analyzer
sudo systemctl start ai-analyzer
echo "systemd 服务已启动"

echo "=== 6/7 配置 nginx 反向代理 ==="
sudo tee /etc/nginx/conf.d/ai-analyzer.conf > /dev/null << NGINXEOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        client_max_body_size 10m;
    }
}
NGINXEOF

sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
echo "nginx 已启动"

echo "=== 7/7 修复 SELinux（如有） ==="
if command -v setsebool &>/dev/null; then
    sudo setsebool -P httpd_can_network_connect 1 2>/dev/null || true
fi

# ---- 验证 ----
echo ""
echo "========================================"
echo "  部署完成！"
echo "========================================"
sleep 2

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  本地测试: ✓ 通过"
else
    echo "  本地测试: ✗ HTTP $HTTP_CODE，请检查 sudo journalctl -u ai-analyzer --no-pager -n 10"
    exit 1
fi

PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "未知")
echo "  公网地址: http://$PUBLIC_IP"
echo "  服务状态: $(sudo systemctl is-active ai-analyzer) | $(sudo systemctl is-active nginx)"
echo "  开机自启: $(sudo systemctl is-enabled ai-analyzer) | $(sudo systemctl is-enabled nginx)"
echo "========================================"
