sudo apt update
sudo apt install -y python3 python3-venv python3-pip
sudo apt install -y ffmpeg sqlite3 curl git nodejs npm

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt