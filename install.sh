#!/usr/bin/env bash

set -e

echo "========================================="
echo "        COOKIE API Auto Installer"
echo "========================================="

echo ""
echo "[1/12] Updating System..."
sudo apt update && sudo apt upgrade -y

echo ""
echo "[2/12] Installing Required Packages..."
sudo apt install -y \
git \
curl \
ffmpeg \
python3 \
python3-pip \
python3-venv

echo ""
echo "[3/12] Installing Node.js 22..."

if command -v node >/dev/null 2>&1; then
    NODE_MAJOR=$(node -v | cut -d'.' -f1 | tr -d 'v')
else
    NODE_MAJOR=0
fi

if [ "$NODE_MAJOR" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
else
    echo "Node.js 22+ already installed."
fi

echo ""
echo "[4/12] Creating Python Virtual Environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

echo ""
echo "[5/12] Upgrading pip..."

pip install --upgrade pip

echo ""
echo "[6/12] Installing Latest yt-dlp..."

pip uninstall -y yt-dlp || true

pip install -U git+https://github.com/yt-dlp/yt-dlp.git

pip install -U "yt-dlp[default]"

echo ""
echo "[7/12] Installing Python Requirements..."

pip install -r requirements.txt

echo ""
echo "[8/12] Checking .env..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ".env created."
    else
        touch .env
        echo ".env file created."
    fi
fi

echo ""
echo "[9/12] Checking FFmpeg..."

ffmpeg -version >/dev/null || {
    echo "FFmpeg installation failed."
    exit 1
}

echo ""
echo "[10/12] Verifying Python Packages..."

python3 - <<EOF
import yt_dlp
import fastapi
import ytmusicapi
print("Python packages verified.")
EOF

echo ""
echo "[11/12] Verifying Installation..."

echo "Node Version:"
node -v

echo ""

echo "Python:"
python3 --version

echo ""

echo "yt-dlp:"
yt-dlp --version

echo ""

echo "yt-dlp-ejs:"
pip show yt-dlp-ejs >/dev/null || {
    echo "yt-dlp-ejs missing!"
    exit 1
}

echo ""

echo "FFmpeg:"
ffmpeg -version | head -n1

echo ""
echo "[12/12] Testing yt-dlp..."

yt-dlp -v --js-runtimes node -F https://youtu.be/U0EI7XFkkV4 >/dev/null || {
    echo ""
    echo "yt-dlp test failed."
    exit 1
}

echo ""
echo "========================================="
echo " INSTALLATION COMPLETED SUCCESSFULLY"
echo "========================================="
echo ""
echo "To Start API:"
echo ""
echo "source venv/bin/activate"
echo "uvicorn app:app --host 0.0.0.0 --port 8000"
echo ""
echo "API:"
echo "http://YOUR_SERVER_IP:8000"
echo ""
echo "Health:"
echo "http://YOUR_SERVER_IP:8000/health"
echo ""
echo "Search:"
echo "http://YOUR_SERVER_IP:8000/search?q=Believer"
echo ""
echo "Thumbnail:"
echo "http://YOUR_SERVER_IP:8000/thumbnail?url=https://youtu.be/U0EI7XFkkV4"
echo ""
echo "MP3:"
echo "http://YOUR_SERVER_IP:8000/download?url=https://youtu.be/U0EI7XFkkV4"
echo ""
echo "MP4:"
echo "http://YOUR_SERVER_IP:8000/video?url=https://youtu.be/U0EI7XFkkV4"
echo ""
echo "========================================="