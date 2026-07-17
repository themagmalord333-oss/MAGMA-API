<div align="center">
<img src="[https://capsule-render.vercel.app/api?type=waving&color=0:8b5cf6,100:06b6d4&height=200&section=header&text=COOKIE%20API&fontSize=60&fontColor=ffffff&animation=fadeIn&fontAlignY=35](https://capsule-render.vercel.app/api?type=waving&color=0:8b5cf6,100:06b6d4&height=200&section=header&text=COOKIE%20API&fontSize=60&fontColor=ffffff&animation=fadeIn&fontAlignY=35)" width="100%" alt="Cookie API Header" />
<img src="[https://files.catbox.moe/6u7xjj.jpg](https://files.catbox.moe/6u7xjj.jpg)" alt="Hero Banner" width="100%" />
<img src="[https://readme-typing-svg.demolab.com?font=Space+Grotesk&weight=700&size=28&pause=1000&color=06B6D4&center=true&vCenter=true&width=800&height=50&lines=Next-Gen+Media+Processing+API;Asynchronous+FastAPI+Backend;Automatic+JS+Challenge+Solving;Powered+by+yt-dlp+%26+FFmpeg](https://readme-typing-svg.demolab.com?font=Space+Grotesk&weight=700&size=28&pause=1000&color=06B6D4&center=true&vCenter=true&width=800&height=50&lines=Next-Gen+Media+Processing+API;Asynchronous+FastAPI+Backend;Automatic+JS+Challenge+Solving;Powered+by+yt-dlp+%26+FFmpeg)" alt="Typing Animation" />
<img src="[https://komarev.com/ghpvc/?username=themagmalord333-oss&label=PROFILE+VIEWS&color=8b5cf6&style=for-the-badge](https://komarev.com/ghpvc/?username=themagmalord333-oss&label=PROFILE+VIEWS&color=8b5cf6&style=for-the-badge)" alt="Profile Views" />
<img src="[https://img.shields.io/badge/Python-3.11+-8b5cf6?style=for-the-badge&logo=python&logoColor=white](https://img.shields.io/badge/Python-3.11+-8b5cf6?style=for-the-badge&logo=python&logoColor=white)" alt="Python Badge" />
<img src="[https://img.shields.io/badge/FastAPI-06b6d4?style=for-the-badge&logo=fastapi&logoColor=white](https://img.shields.io/badge/FastAPI-06b6d4?style=for-the-badge&logo=fastapi&logoColor=white)" alt="FastAPI Badge" />
<img src="[https://img.shields.io/badge/Node.js-3b82f6?style=for-the-badge&logo=nodedotjs&logoColor=white](https://img.shields.io/badge/Node.js-3b82f6?style=for-the-badge&logo=nodedotjs&logoColor=white)" alt="Node JS Badge" />
<img src="[https://img.shields.io/badge/FFmpeg-8b5cf6?style=for-the-badge&logo=ffmpeg&logoColor=white](https://img.shields.io/badge/FFmpeg-8b5cf6?style=for-the-badge&logo=ffmpeg&logoColor=white)" alt="FFmpeg Badge" />


<img src="[https://img.shields.io/badge/AWS-06b6d4?style=for-the-badge&logo=amazon-aws&logoColor=white](https://img.shields.io/badge/AWS-06b6d4?style=for-the-badge&logo=amazon-aws&logoColor=white)" alt="AWS Badge" />
<img src="[https://img.shields.io/badge/Docker-3b82f6?style=for-the-badge&logo=docker&logoColor=white](https://img.shields.io/badge/Docker-3b82f6?style=for-the-badge&logo=docker&logoColor=white)" alt="Docker Badge" />
<img src="[https://img.shields.io/badge/Ubuntu-8b5cf6?style=for-the-badge&logo=ubuntu&logoColor=white](https://img.shields.io/badge/Ubuntu-8b5cf6?style=for-the-badge&logo=ubuntu&logoColor=white)" alt="Ubuntu Badge" />
<img src="[https://img.shields.io/badge/License-MIT-06b6d4?style=for-the-badge](https://img.shields.io/badge/License-MIT-06b6d4?style=for-the-badge)" alt="License Badge" />
**The ultimate production-ready REST API for high-quality media processing.**
Featuring an intelligent Node.js challenge solver and seamless automated cookie rotation.
</div>
<div align="center">
<h2>✨ Core Features</h2>
</div>
 * **⚡ Async FastAPI** — Lightning-fast asynchronous request handling.
 * **🍪 Auto Cookie Sync** — Seamlessly rotates Netscape cookies via remote URL.
 * **🛡️ JS Challenge Solver** — Bypasses anti-bot mechanisms using an isolated Node V8 engine.
 * **🎬 FFmpeg Engine** — Merges 4K/8K video and audio with zero sync issues.
 * **🧠 Advanced Cache** — Sub-millisecond response times using Redis/In-Memory state.
 * **📦 Production Ready** — Dockerized, AWS-compatible, and Ubuntu-native.
<div align="center">
<img src="[https://files.catbox.moe/6gi3gi.jpg](https://files.catbox.moe/6gi3gi.jpg)" alt="Secondary Banner" width="100%" />
</div>
<div align="center">
<h2>🏗️ Architecture & Installation</h2>
</div>
<details>
<summary><b>🧠 View System Architecture</b></summary>


 * **API Layer**: Powered by Uvicorn and FastAPI for RESTful routing.
 * **Execution Layer**: yt-dlp paired with yt-dlp-ejs and a Node.js subprocess.
 * **Muxing Layer**: Direct interface with FFmpeg for memory-efficient media merging.
 * **Auth Layer**: Background daemon syncing remote cookies to maintain session validity.
</details>
<details>
<summary><b>🐧 Ubuntu / Debian Setup</b></summary>


```bash
# Update and install dependencies
sudo apt update && sudo apt install -y python3-venv ffmpeg nodejs

# Clone the repository
git clone https://github.com/MAGMAxRICH/cookie-api.git
cd cookie-api

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt
npm install

# Run server
uvicorn app.main:app --host 0.0.0.0 --port 8000

```
</details>
<details>
<summary><b>🐳 Docker / AWS Deployment</b></summary>


```bash
# Build the image
docker build -t cookie-api .

# Run the container in the background
docker run -d -p 8000:8000 --env-file .env cookie-api

```
</details>
<div align="center">
<h2>⚙️ Environment Variables</h2>
</div>
| Variable | Description | Required | Default |
|---|---|---|---|
| COOKIE_URL | Remote .txt file for cookie rotation | ✔️ | *None* |
| API_PORT | Port for FastAPI to listen on | ❌ | 8000 |
| CACHE_TTL | Redis/Memory cache lifetime (seconds) | ❌ | 3600 |
| MAX_CONCURRENT | Limit active FFmpeg merge threads | ❌ | 5 |
<div align="center">
<h2>🌐 API Endpoints</h2>
</div>
| Method | Endpoint | Purpose | Auth |
|---|---|---|---|
| GET | /api/v1/health | System diagnostics & status | ❌ |
| GET | /api/v1/search | Search media by keyword | ❌ |
| GET | /api/v1/thumbnail | Fetch max-res thumbnails | ❌ |
| POST | /api/v1/download/audio | Process & extract audio | ❌ |
| POST | /api/v1/download/video | Merge 4K video + audio | ❌ |
| POST | /api/v1/cookies/sync | Trigger manual cookie update | ✔️ |
<details>
<summary><b>💡 View API Examples</b></summary>


**1. Health Check (GET)**
```bash
curl "http://localhost:8000/api/v1/health"

```
```json
{
  "status": "online",
  "version": "2.1.0",
  "cookie_status": "synced"
}

```
**2. Video Download (POST)**
```bash
curl -X POST "http://localhost:8000/api/v1/download/video" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://youtube.com/watch?v=dQw4w9WgXcQ", "resolution": "1080p"}'

```
```json
{
  "success": true,
  "task_id": "vid_45kx9",
  "status": "merging_audio_video",
  "download_url": "http://localhost:8000/media/vid_45kx9.mp4"
}

```
</details>
<div align="center">
<h2>❓ FAQ & Troubleshooting</h2>
</div>
<details>
<summary><b>Why am I getting a "Bot verification" error?</b></summary>


Your COOKIE_URL is likely missing or the remote file has expired. Ensure your remote server is providing a fresh Netscape-formatted cookies.txt.
</details>
<details>
<summary><b>Why is my Audio/Video out of sync?</b></summary>


Ensure FFmpeg is correctly installed on your host machine. Underpowered CPUs can also cause multiplexing delays.
</details>
<div align="center">
<h2>📈 GitHub Activity</h2>


<img src="[https://github-readme-stats.vercel.app/api?username=themagmalord333-oss&show_icons=true&theme=tokyonight&hide_border=true&bg_color=0D1117](https://github-readme-stats.vercel.app/api?username=themagmalord333-oss&show_icons=true&theme=tokyonight&hide_border=true&bg_color=0D1117)" alt="GitHub Stats" />



<img src="[https://github-readme-stats.vercel.app/api/top-langs/?username=themagmalord333-oss&theme=tokyonight&hide_border=true&bg_color=0D1117&layout=compact](https://github-readme-stats.vercel.app/api/top-langs/?username=themagmalord333-oss&theme=tokyonight&hide_border=true&bg_color=0D1117&layout=compact)" alt="Top Languages" />



<img src="[https://streak-stats.demolab.com?user=themagmalord333-oss&theme=tokyonight&hide_border=true&background=0D1117](https://streak-stats.demolab.com?user=themagmalord333-oss&theme=tokyonight&hide_border=true&background=0D1117)" alt="GitHub Streak" />



<img src="[https://github-readme-activity-graph.vercel.app/graph?username=themagmalord333-oss&theme=tokyo-night&hide_border=true&bg_color=0D1117](https://github-readme-activity-graph.vercel.app/graph?username=themagmalord333-oss&theme=tokyo-night&hide_border=true&bg_color=0D1117)" alt="Activity Graph" width="100%" />
</div>
<div align="center">
<h2>🤝 Support & License</h2>
</div>
 * **License**: Distributed under the **MIT License**.
 * **Support**: Found a bug or need custom features? Please open an **Issue** or submit a **Pull Request**.
<div align="center">
<p>Made with 💜 by <a href="[https://github.com/MAGMAxRICH](https://github.com/MAGMAxRICH)">@MAGMAxRICH</a></p>
</div>
<div align="center">
<img src="[https://capsule-render.vercel.app/api?type=waving&color=0:06b6d4,100:8b5cf6&height=150&section=footer](https://capsule-render.vercel.app/api?type=waving&color=0:06b6d4,100:8b5cf6&height=150&section=footer)" width="100%" alt="Cookie API Footer" />
</div>