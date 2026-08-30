import os
import re
import time
import asyncio
import sqlite3
import logging
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvloop
import orjson
import psutil
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse, FileResponse
from dotenv import load_dotenv

from prometheus_client import make_asgi_app
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

import yt_dlp
from ytmusicapi import YTMusic

# Enable ultra-fast event loop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

load_dotenv()

# Configuration
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CACHE_EXPIRE_HOURS = float(os.getenv("CACHE_EXPIRE_HOURS", "24"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "720")
PORT = int(os.getenv("PORT", "8000"))
COOKIE_URL = os.getenv("COOKIE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
COOKIES_FILE = "cookies.txt"
DB_FILE = "cache.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ytmusic = YTMusic()
redis_client: redis.Redis = None

def init_db():
    try:
        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    title TEXT,
                    file_name TEXT,
                    file_path TEXT,
                    file_type TEXT,
                    file_size INTEGER,
                    duration INTEGER,
                    created_time REAL,
                    thumbnail TEXT,
                    UNIQUE(video_id, file_type)
                )
            ''')
            conn.commit()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

def get_cached_metadata(video_id: str, file_type: str) -> Optional[Dict[str, Any]]:
    try:
        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM downloads WHERE video_id = ? AND file_type = ?", (video_id, file_type))
            row = cur.fetchone()

            if row:
                if os.path.isfile(row['file_path']) and os.path.getsize(row['file_path']) > 0:
                    return dict(row)
                else:
                    cur.execute("DELETE FROM downloads WHERE id = ?", (row['id'],))
                    conn.commit()
            return None
    except Exception as e:
        return None

def save_cached_metadata(data: Dict[str, Any], file_type: str):
    try:
        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO downloads 
                (video_id, title, file_name, file_path, file_type, file_size, duration, created_time, thumbnail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['videoId'], data['title'], data['filename'], data['path'], 
                file_type, data['filesize'], data['duration'], time.time(), data['thumbnail']
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving to cache DB: {e}")

async def cache_cleanup_task():
    while True:
        try:
            expiry_time = time.time() - (CACHE_EXPIRE_HOURS * 3600)
            def perform_cleanup():
                deleted, db_cleaned = 0, 0
                with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
                    cur = conn.cursor()
                    if os.path.exists(DOWNLOAD_DIR):
                        for entry in os.scandir(DOWNLOAD_DIR):
                            if entry.is_file() and entry.stat().st_mtime < expiry_time:
                                try:
                                    os.remove(entry.path)
                                    deleted += 1
                                    cur.execute("DELETE FROM downloads WHERE file_name = ?", (entry.name,))
                                except Exception:
                                    pass
                    cur.execute("SELECT id, file_path FROM downloads")
                    for record in cur.fetchall():
                        if not os.path.exists(record[1]):
                            cur.execute("DELETE FROM downloads WHERE id = ?", (record[0],))
                            db_cleaned += 1
                    conn.commit()
                return deleted, db_cleaned
            
            await asyncio.to_thread(perform_cleanup)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting Anysnap MAGMA-API...")
    init_db()

    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
    except Exception:
        redis_client = None

    if COOKIE_URL:
        try:
            urllib.request.urlretrieve(COOKIE_URL, COOKIES_FILE)
        except Exception as e:
            logger.error(f"Failed to download cookies: {e}")

    cleanup_worker = asyncio.create_task(cache_cleanup_task())
    yield
    cleanup_worker.cancel()
    if redis_client:
        await redis_client.aclose()

# FastAPI setup with ORJSONResponse to strictly return JSON
app = FastAPI(
    title="Anysnap MAGMA-API", 
    version="3.0.0-Optimized", 
    lifespan=lifespan,
    default_response_class=ORJSONResponse 
)

FastAPIInstrumentor.instrument_app(app)
app.mount("/metrics", make_asgi_app())

def extract_video_id(url: str) -> Optional[str]:
    if not url: return None
    if re.match(r"^[0-9A-Za-z_-]{11}$", url): return url
    match = re.search(r"(?:youtu\.be\/|v=|\/shorts\/|\/embed\/|\/v\/)([0-9A-Za-z_-]{11})", url)  
    if match: return match.group(1)  
    match = re.search(r"[0-9A-Za-z_-]{11}", url)  
    return match.group(0) if match else None

def get_base_ydl_opts() -> Dict[str, Any]:
    opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/%(title).150s_%(id)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 15,
        'continuedl': True,
        'source_address': '0.0.0.0', 
        'external_downloader': 'aria2c', 
        'external_downloader_args': {'aria2c': ['-c', '-j', '15', '-x', '15', '-s', '15', '-k', '1M']}
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
    return opts

def extract_youtube_with_fallback(url: str, opts: Dict[str, Any], download: bool = True) -> Dict[str, Any]:
    strategies = [("default", {}), ("web_embedded", {"youtube": {"player_client": ["default", "web_embedded"]}})]
    last_err = None
    for name, args in strategies:
        try:
            attempt_opts = dict(opts)
            if args: attempt_opts["extractor_args"] = args
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"All extraction strategies failed: {last_err}")

def download_audio_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)
    if video_id:
        cached = get_cached_metadata(video_id, "mp3")
        if cached:
            return {
                "status": True, "title": cached["title"], "duration": cached["duration"],
                "thumbnail": cached["thumbnail"], "filename": cached["file_name"],
                "path": cached["file_path"], "download_url": f"/files/{cached['file_name']}",
                "videoId": video_id, "uploader": "Anysnap-Cache", "filesize": cached["file_size"]
            }

    opts = get_base_ydl_opts()  
    opts.update({  
        'format': '140/ba[ext=m4a]/bestaudio/best', 
        'writethumbnail': False,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'nocheckcertificate': True,
        'clean_infojson': False,
        'postprocessor_args': ['-threads', '0', '-vn', '-sn']
    })  

    info = extract_youtube_with_fallback(url, opts, download=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        filename = ydl.prepare_filename(info)  
    
    final_path = f"{os.path.splitext(filename)[0]}.mp3"  
    
    res = {  
        "status": True, "title": info.get("title", ""), "duration": info.get("duration", 0),  
        "thumbnail": info.get("thumbnail", ""), "filename": os.path.basename(final_path),  
        "path": final_path, "download_url": f"/files/{os.path.basename(final_path)}",  
        "videoId": info.get("id"), "uploader": info.get("uploader"), "filesize": os.path.getsize(final_path)  
    }
    save_cached_metadata(res, "mp3")
    return res

def download_video_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)
    if video_id:
        cached = get_cached_metadata(video_id, "mp4")
        if cached:
            return {
                "status": True, "title": cached["title"], "duration": cached["duration"],
                "thumbnail": cached["thumbnail"], "filename": cached["file_name"],
                "path": cached["file_path"], "download_url": f"/files/{cached['file_name']}",
                "videoId": video_id, "uploader": "Anysnap-Cache", "filesize": cached["file_size"]
            }

    opts = get_base_ydl_opts()  
    opts.update({  
        'format': f'bv*[height<={MAX_VIDEO_QUALITY}][ext=mp4]+ba[ext=m4a]/b[height<={MAX_VIDEO_QUALITY}][ext=mp4]/best',  
        'merge_output_format': 'mp4',
        'nocheckcertificate': True
    })  

    info = extract_youtube_with_fallback(url, opts, download=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        filename = ydl.prepare_filename(info)  
    
    base_path = os.path.splitext(filename)[0]
    final_path = f"{base_path}.mp4"
    for ext in [".mp4", ".webm", ".mkv"]:
        if os.path.isfile(f"{base_path}{ext}"):
            final_path = f"{base_path}{ext}"
            break

    res = {  
        "status": True, "title": info.get("title", ""), "duration": info.get("duration", 0),  
        "thumbnail": info.get("thumbnail", ""), "filename": os.path.basename(final_path),  
        "path": final_path, "download_url": f"/files/{os.path.basename(final_path)}",  
        "videoId": info.get("id"), "uploader": info.get("uploader"), "filesize": os.path.getsize(final_path)  
    }
    save_cached_metadata(res, "mp4")
    return res

@app.get("/")
async def root():
    return {"name": "Anysnap MAGMA-API", "version": "3.0.0", "status": "online"}

@app.get("/sysinfo")
async def system_info():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_used_mb": round(psutil.virtual_memory().used / (1024*1024), 2),
        "disk_free_mb": round(psutil.disk_usage(DOWNLOAD_DIR).free / (1024*1024), 2)
    }

@app.get("/search")
async def search_youtube_music(
    q: str = Query(..., description="Search query"),
    limit: int = Query(1, description="Number of results to return (max 20)")
):
    try:
        actual_limit = min(max(1, limit), 20)
        cache_key = f"anysnap:search:{q}:{actual_limit}"

        if redis_client:
            cached_result = await redis_client.get(cache_key)
            if cached_result:
                return ORJSONResponse(content=orjson.loads(cached_result))

        results = await asyncio.to_thread(ytmusic.search, q, filter="songs", limit=actual_limit)  
        
        formatted_results = []  
        for r in results:  
            formatted_results.append({  
                "title": r.get("title"),  
                "artist": ", ".join([a.get("name", "") for a in r.get("artists", [])]),  
                "videoId": r.get("videoId"),  
                "duration": r.get("duration"),  
                "thumbnail": r.get("thumbnails", [])[-1].get("url") if r.get("thumbnails") else None  
            })  

        final_json = formatted_results[0] if actual_limit == 1 and formatted_results else formatted_results

        if redis_client:
            await redis_client.setex(cache_key, 43200, orjson.dumps(final_json))

        return ORJSONResponse(content=final_json)
    except Exception as e:  
        raise HTTPException(status_code=500, detail={"error": "Search failed", "message": str(e)})

@app.get("/download")
async def download_audio(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_audio_sync, url)
        return ORJSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Audio download failed", "message": str(e)})

@app.get("/video")
async def download_video(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_video_sync, url)
        return ORJSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Video download failed", "message": str(e)})

@app.get("/files/{filename}")
async def get_file(filename: str):
    file_path = os.path.join(DOWNLOAD_DIR, os.path.basename(filename))
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename)

# ✅ FIX: Yahan app:app kar diya gaya hai
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")