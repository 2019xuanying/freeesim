#!/bin/bash

# ==========================================
# eSIM Telegram Bot 一键安装/更新脚本
# ==========================================

# 颜色设置
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 你的 GitHub 仓库地址 (请确保仓库是 Public，或者是能在服务器直接 clone 的)
REPO_URL="https://github.com/2019xuanying/freeesim.git"
INSTALL_DIR="/opt/esim_bot"

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}     欢迎使用 eSIM Bot 一键部署脚本    ${NC}"
echo -e "${GREEN}=====================================${NC}"

# 1. 检查 root 权限
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}请使用 root 用户或 sudo 执行此脚本！${NC}"
  exit 1
fi

# 2. 交互式获取配置变量
echo -e "\n${YELLOW}▶ 请输入以下配置信息 (如果你只是想更新代码，可以直接按回车跳过配置环节):${NC}"

read -p "请输入机器人的 BOT_TOKEN: " INPUT_BOT_TOKEN
read -p "请输入管理员的 Telegram ID (纯数字): " INPUT_ADMIN_ID
read -p "请输入强制加入的群组/频道 (例如 @my_channel_123): " INPUT_REQUIRED_CHAT_ID

# 3. 更新系统与安装必要环境
echo -e "\n${YELLOW}▶ 正在更新系统包并安装 Python3、Git 等依赖环境...${NC}"
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git curl

# 4. 拉取/更新代码
echo -e "\n${YELLOW}▶ 正在从 GitHub 获取最新代码...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "检测到目录已存在，正在更新代码..."
    cd $INSTALL_DIR
    git fetch --all
    git reset --hard origin/main
    git pull origin main
else
    echo -e "正在全新克隆仓库..."
    git clone $REPO_URL $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 5. 配置 Python 虚拟环境
echo -e "\n${YELLOW}▶ 正在配置 Python 虚拟环境并安装依赖库...${NC}"
python3 -m venv venv
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install python-telegram-bot

# 6. 配置 systemd 服务与环境变量
echo -e "\n${YELLOW}▶ 正在配置 systemd 后台守护进程...${NC}"

# 如果用户输入了新的 Token，就重新生成 service 文件；否则保留旧的配置
if [ -n "$INPUT_BOT_TOKEN" ] && [ -n "$INPUT_ADMIN_ID" ]; then
cat > /etc/systemd/system/esimbot.service <<EOF
[Unit]
Description=eSIM Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
Environment="BOT_TOKEN=${INPUT_BOT_TOKEN}"
Environment="ADMIN_ID=${INPUT_ADMIN_ID}"
Environment="REQUIRED_CHAT_ID=${INPUT_REQUIRED_CHAT_ID}"
ExecStart=$INSTALL_DIR/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
else
    echo -e "未输入新配置，保留已有配置启动..."
fi

# 7. 启动并设置开机自启
systemctl enable esimbot
systemctl restart esimbot

echo -e "\n${GREEN}=====================================${NC}"
echo -e "${GREEN}🎉 部署完成！机器人已经开始在后台运行。${NC}"
echo -e "${GREEN}=====================================${NC}"
echo -e "常用命令指南："
echo -e "🔹 查看运行状态: ${YELLOW}systemctl status esimbot${NC}"
echo -e "🔹 查看实时日志: ${YELLOW}journalctl -u esimbot -f -n 50${NC}"
echo -e "🔹 重启机器人:   ${YELLOW}systemctl restart esimbot${NC}"
echo -e "🔹 停止机器人:   ${YELLOW}systemctl stop esimbot${NC}"
