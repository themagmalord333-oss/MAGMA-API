import os
import re
import time
import asyncio
import sqlite3
import logging
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv
import yt_dlp
from ytmusicapi import YTMusic

# Load environment variables from .env file
load_dotenv()

# Configuration from Environment Variables
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CACHE_EXPIRE_HOURS = float(os.getenv("CACHE_EXPIRE_HOURS", "24"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "720")
PORT = int(os.getenv("PORT", "8000"))
COOKIE_URL = os.getenv("COOKIE_URL", "")
COOKIES_FILE = "cookies.txt"
DB_FILE = "cache.db"

# Worker Limit (Max simultaneous downloads)
DOWNLOAD_WORKERS = int(os.getenv("DOWNLOAD_WORKERS", "3"))

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------
# QUEUE & WORKER SYSTEM GLOBALS
# ---------------------------------------------------------
download_semaphore = None
task_lock = None  # Lock for thread-safe active_tasks modification
active_tasks = {}  # Tracks ongoing downloads to prevent duplicates

# ---------------------------------------------------------
# DATABASE & CACHE SYSTEM
# ---------------------------------------------------------

def init_db():
    try:
        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
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
        logger.info("SQLite database initialized.")
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
        logger.error(f"Error accessing cache DB: {e}")
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
                deleted_files = 0
                db_cleaned = 0
                with sqlite3.connect(DB_FILE, timeout=15.0) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()

                    if os.path.exists(DOWNLOAD_DIR):
                        for entry in os.scandir(DOWNLOAD_DIR):
                            if entry.is_file():
                                file_stat = entry.stat()
                                if file_stat.st_mtime < expiry_time:
                                    try:
                                        os.remove(entry.path)
                                        deleted_files += 1
                                        cur.execute("DELETE FROM downloads WHERE file_name = ?", (entry.name,))
                                    except Exception:
                                        pass

                    cur.execute("SELECT id, file_path FROM downloads")
                    for record in cur.fetchall():
                        if not os.path.exists(record['file_path']):
                            cur.execute("DELETE FROM downloads WHERE id = ?", (record['id'],))
                            db_cleaned += 1
                    conn.commit()
                return deleted_files, db_cleaned

            deleted_files, db_cleaned = await asyncio.to_thread(perform_cleanup)
            if deleted_files > 0 or db_cleaned > 0:
                logger.info(f"Cleanup: {deleted_files} files, {db_cleaned} DB records removed.")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        await asyncio.sleep(3600)

# ---------------------------------------------------------
# FASTAPI LIFESPAN
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global download_semaphore, task_lock
    # Initialize locks inside the async event loop
    download_semaphore = asyncio.Semaphore(DOWNLOAD_WORKERS)
    task_lock = asyncio.Lock()
    
    logger.info("Starting ANYSNAP Music API...")
    init_db()

    if COOKIE_URL:
        try:
            urllib.request.urlretrieve(COOKIE_URL, COOKIES_FILE)
        except Exception as e:
            logger.error(f"Cookie DL failed: {e}")

    cleanup_worker = asyncio.create_task(cache_cleanup_task())
    yield 
    cleanup_worker.cancel()

# ---------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------

app = FastAPI(title="ANYSNAP Music API", version="3.1.0-Production", lifespan=lifespan)
ytmusic = YTMusic()

# ---------------------------------------------------------
# YT-DLP HELPERS & DOWNLOADERS
# ---------------------------------------------------------

def extract_video_id(url: str) -> Optional[str]:
    if not url: return None
    if re.match(r"^[0-9A-Za-z_-]{11}$", url): return url
    pattern = r"(?:youtu\.be\/|v=|\/shorts\/|\/embed\/|\/v\/)([0-9A-Za-z_-]{11})"  
    match = re.search(pattern, url)  
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
        'retries': 5,
        'socket_timeout': 15,
        'continuedl': True, 
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github']
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
    return opts

def download_audio_sync(url: str, video_id: str) -> Dict[str, Any]:
    opts = get_base_ydl_opts()  
    opts.update({  
        'format': '140/ba[ext=m4a]/bestaudio/best', 
        'writethumbnail': False,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'extractor_args': {'youtube': ['player_client=ios,android,web']}, 
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            
        'nocheckcertificate': True,
        'postprocessor_args': ['-threads', '0', '-vn', '-sn']
    })  
    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=True)  
            filename = ydl.prepare_filename(info)  
            final_path = f"{os.path.splitext(filename)[0]}.mp3"  

            response_data = {  
                "status": True,  
                "title": info.get("title", ""),  
                "duration": info.get("duration", 0),  
                "thumbnail": info.get("thumbnail", ""),  
                "filename": os.path.basename(final_path),  
                "path": final_path,  
                "download_url": f"/files/{os.path.basename(final_path)}",  
                "videoId": info.get("id"),  
                "uploader": info.get("uploader"),  
                "filesize": os.path.getsize(final_path)  
            }
            save_cached_metadata(response_data, "mp3")
            return response_data
    except Exception as e:  
        raise RuntimeError(f"Internal Server Error: {str(e)}")

def download_video_sync(url: str, video_id: str) -> Dict[str, Any]:
    opts = get_base_ydl_opts()  
    opts.update({  
        'format': f'bv*[height<={MAX_VIDEO_QUALITY}][ext=mp4]+ba[ext=m4a]/b[height<={MAX_VIDEO_QUALITY}][ext=mp4]/best',  
        'merge_output_format': 'mp4',
        'extractor_args': {'youtube': ['player_client=ios,android,web']},
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            
        'nocheckcertificate': True,
        'postprocessor_args': ['-threads', '0']
    })  
    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=True)  
            filename = ydl.prepare_filename(info)  
            base_path = os.path.splitext(filename)[0]
            
            final_path = f"{base_path}.mp4"
            for ext in [".mp4", ".webm", ".mkv"]:
                if os.path.isfile(f"{base_path}{ext}"):
                    final_path = f"{base_path}{ext}"
                    break

            response_data = {  
                "status": True,  
                "title": info.get("title", ""),  
                "thumbnail": info.get("thumbnail", ""),  
                "filename": os.path.basename(final_path),  
                "path": final_path,  
                "download_url": f"/files/{os.path.basename(final_path)}",  
                "duration": info.get("duration", 0),  
                "videoId": info.get("id"),  
                "uploader": info.get("uploader"),  
                "filesize": os.path.getsize(final_path)  
            }
            save_cached_metadata(response_data, "mp4")
            return response_data
    except Exception as e:  
        raise RuntimeError(f"Internal Server Error: {str(e)}")

# ---------------------------------------------------------
# SMART DOWNLOAD MANAGER (QUEUE + LOCK DEDUPLICATION)
# ---------------------------------------------------------

async def smart_download(url: str, download_func, file_type: str):
    """Handles Caching, Worker Limits, and strictly locked Duplicate Request Prevention"""
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    # 1. DB Cache Check (Fast Return)
    cached_data = get_cached_metadata(video_id, file_type)
    if cached_data:
        logger.info(f"DB Cache hit for {video_id}")
        return {
            "status": True,
            "title": cached_data["title"],
            "thumbnail": cached_data["thumbnail"],
            "filename": cached_data["file_name"],
            "download_url": f"/files/{cached_data['file_name']}",
            "videoId": video_id,
            "uploader": "Cached",
            "filesize": cached_data["file_size"]
        }

    task_key = f"{video_id}_{file_type}"
    is_new_task = False

    # 2. Duplicate Check with strictly enforced Lock to prevent race conditions
    async with task_lock:
        if task_key in active_tasks:
            logger.info(f"Duplicate request for {video_id}. Waiting for existing download...")
            future = active_tasks[task_key]
        else:
            # Register new download task securely
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            active_tasks[task_key] = future
            is_new_task = True

    # If another user already initiated this, just wait for their result
    if not is_new_task:
        return await future

    try:
        # 3. Queue System: Wait for a worker slot to become available
        async with download_semaphore:
            logger.info(f"Worker assigned. Starting download for: {video_id}")
            result = await asyncio.to_thread(download_func, url, video_id)
        
        # Share the result with any queued identical requests
        future.set_result(result)
        return result
    except Exception as e:
        future.set_exception(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up the task lock dictionary
        async with task_lock:
            active_tasks.pop(task_key, None)

# ---------------------------------------------------------
# API ROUTES
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {"name": "ANYSNAP Music API", "version": "3.1.0-Production", "status": "online"}

@app.get("/search")
async def search_youtube_music(
    q: str = Query(..., description="Search query"),
    limit: int = Query(1, description="Number of results to return (max 20)")
):
    try:
        actual_limit = min(max(1, limit), 20)  
        results = await asyncio.to_thread(lambda: ytmusic.search(q, filter="songs", limit=actual_limit))  

        formatted_results = []  
        for r in results:  
            formatted_results.append({  
                "title": r.get("title"),  
                "artist": ", ".join([a.get("name", "") for a in r.get("artists", [])]),  
                "videoId": r.get("videoId"),  
                "duration": r.get("duration"),  
                "thumbnail": r.get("thumbnails", [])[-1].get("url") if r.get("thumbnails") else None  
            })  

        if actual_limit == 1:  
            return {"status": True, "result": formatted_results[0] if formatted_results else {}}  
        return {"status": True, "results": formatted_results}
    except Exception as e:  
        raise HTTPException(status_code=500, detail={"error": "Search failed", "message": str(e)})

@app.get("/download")
async def download_audio(url: str = Query(..., description="YouTube URL")):
    result = await smart_download(url, download_audio_sync, "mp3")
    return JSONResponse(content=result)

@app.get("/video")
async def download_video(url: str = Query(..., description="YouTube URL")):
    result = await smart_download(url, download_video_sync, "mp4")
    return JSONResponse(content=result)

@app.get("/files/{filename}")
async def get_file(filename: str):
    filename = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)