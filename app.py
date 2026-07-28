import os
import re
import time
import asyncio
import sqlite3
import logging
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv
import yt_dlp
from ytmusicapi import YTMusic

load_dotenv()

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CACHE_EXPIRE_HOURS = float(os.getenv("CACHE_EXPIRE_HOURS", "24"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "720")
PORT = int(os.getenv("PORT", "8000"))
COOKIE_URL = os.getenv("COOKIE_URL", "")
COOKIES_FILE = "cookies.txt"
DB_FILE = "cache.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
                    logger.warning(f"File {row['file_name']} missing from disk. Removing DB entry.")
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

def find_legacy_cached_file(video_id: str, ext: str) -> Optional[str]:
    if not video_id: return None
    suffix = f"_{video_id}.{ext}"
    try:
        with os.scandir(DOWNLOAD_DIR) as entries:
            for entry in entries:
                if entry.name.endswith(suffix):
                    return entry.name
    except Exception as e:
        logger.error(f"Error reading {DOWNLOAD_DIR}: {e}")
    return None

async def cache_cleanup_task():
    while True:
        try:
            logger.info("Running advanced cache cleanup...")
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
                                    except Exception as e:
                                        logger.warning(f"Could not delete old file {entry.name}: {e}")

                    cur.execute("SELECT id, file_path FROM downloads")
                    all_records = cur.fetchall()
                    for record in all_records:
                        if not os.path.exists(record['file_path']):
                            cur.execute("DELETE FROM downloads WHERE id = ?", (record['id'],))
                            db_cleaned += 1

                    conn.commit()
                return deleted_files, db_cleaned

            deleted_files, db_cleaned = await asyncio.to_thread(perform_cleanup)

            if deleted_files > 0 or db_cleaned > 0:
                logger.info(f"Cleanup complete: Deleted {deleted_files} old files on disk, cleared {db_cleaned} DB records.")
            else:
                logger.info("Cleanup complete: No expired files found.")

        except Exception as e:
            logger.error(f"Cache cleanup encountered an error: {e}")

        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Anysnap Music API...")
    init_db()

    if COOKIE_URL:
        try:
            urllib.request.urlretrieve(COOKIE_URL, COOKIES_FILE)
            logger.info(f"Successfully downloaded cookies.txt from COOKIE_URL")
        except Exception as e:
            logger.error(f"Failed to download cookies from COOKIE_URL: {e}")

    cleanup_worker = asyncio.create_task(cache_cleanup_task())

    yield 

    logger.info("Shutting down Anysnap Music API...")
    cleanup_worker.cancel()

app = FastAPI(title="Anysnap Music API", version="3.0.0-Production", lifespan=lifespan)
ytmusic = YTMusic()

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
        'quiet': False,
        'no_warnings': False,
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 30,
        'continuedl': True,
        'js_runtimes': {'node': {}}
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
        logger.info(f"Loaded cookies from {COOKIES_FILE}")
    return opts

def fetch_thumbnail_sync(url: str) -> Dict[str, Any]:
    opts = get_base_ydl_opts()
    opts['skip_download'] = True
    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=False)  
            return {  
                "title": info.get("title"),  
                "thumbnail": info.get("thumbnail"),  
                "videoId": info.get("id")  
            }  
    except Exception as e:  
        logger.error(f"Thumbnail fetch error: {e}")  
        raise RuntimeError(f"Failed to fetch thumbnail: {str(e)}")

def download_audio_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)

    if video_id:
        cached_data = get_cached_metadata(video_id, "mp3")
        if cached_data:
            logger.info(f"Database cache hit! Returning audio for {video_id}")
            return {
                "status": True,
                "title": cached_data["title"],
                "duration": cached_data["duration"],
                "thumbnail": cached_data["thumbnail"],
                "filename": cached_data["file_name"],
                "path": cached_data["file_path"],
                "download_url": f"/files/{cached_data['file_name']}",
                "videoId": video_id,
                "uploader": "Cached",
                "filesize": cached_data["file_size"]
            }

        legacy_file = find_legacy_cached_file(video_id, "mp3")
        if legacy_file:
            path = os.path.join(DOWNLOAD_DIR, legacy_file)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                logger.info(f"Legacy disk cache hit for {video_id}. Saving to DB.")
                data = {
                    "videoId": video_id,
                    "title": legacy_file[:-len(f"_{video_id}.mp3")],
                    "filename": legacy_file,
                    "path": path,
                    "type": "mp3",
                    "filesize": os.path.getsize(path),
                    "duration": 0,
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                }
                save_cached_metadata(data, "mp3")
                data["status"] = True
                data["download_url"] = f"/files/{legacy_file}"
                data["uploader"] = "Cached"
                return data

    logger.info(f"Starting audio download for: {url}")
    opts = get_base_ydl_opts()  

    opts.update({  
        'format': 'bestaudio/best',
        'writethumbnail': False,
        'postprocessors': [{  
            'key': 'FFmpegExtractAudio',  
            'preferredcodec': 'mp3',  
            'preferredquality': '192',  
        }],
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            
        'nocheckcertificate': True,
        'noprogress': True,
        'quiet': False,
        'no_warnings': False,
        'updatetime': False,                    
        'clean_infojson': False,
        'postprocessor_args': [
            '-threads', '0',                    
            '-vn', '-sn'                        
        ]
    })  

    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=True)  
            filename = ydl.prepare_filename(info)  
            base_path, _ = os.path.splitext(filename)  
            final_path = f"{base_path}.mp3"  

            if not os.path.isfile(final_path) or os.path.getsize(final_path) == 0:  
                raise RuntimeError("Downloaded file is missing or empty.")  

            logger.info(f"Successfully downloaded audio: {final_path}")  

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

    except yt_dlp.utils.DownloadError as e:  
        logger.error(f"yt-dlp error downloading audio for {url}: {e}")  
        raise RuntimeError(f"Download Error: {str(e)}")  
    except Exception as e:  
        logger.error(f"Unexpected error downloading audio for {url}: {e}")  
        raise RuntimeError(f"Internal Server Error: {str(e)}")


def download_video_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)

    if video_id:
        cached_data = get_cached_metadata(video_id, "mp4")
        if cached_data:
            logger.info(f"Database cache hit! Returning video for {video_id}")
            return {
                "status": True,
                "title": cached_data["title"],
                "thumbnail": cached_data["thumbnail"],
                "filename": cached_data["file_name"],
                "path": cached_data["file_path"],
                "download_url": f"/files/{cached_data['file_name']}",
                "duration": cached_data["duration"],
                "videoId": video_id,
                "uploader": "Cached",
                "filesize": cached_data["file_size"]
            }

        legacy_file = find_legacy_cached_file(video_id, "mp4")
        if legacy_file:
            path = os.path.join(DOWNLOAD_DIR, legacy_file)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                logger.info(f"Legacy disk cache hit for {video_id}. Saving to DB.")
                data = {
                    "videoId": video_id,
                    "title": legacy_file[:-len(f"_{video_id}.mp4")],
                    "filename": legacy_file,
                    "path": path,
                    "type": "mp4",
                    "filesize": os.path.getsize(path),
                    "duration": 0,
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                }
                save_cached_metadata(data, "mp4")
                data["status"] = True
                data["download_url"] = f"/files/{legacy_file}"
                data["uploader"] = "Cached"
                return data

    logger.info(f"Starting video download for: {url}")
    opts = get_base_ydl_opts()  

    opts.update({  
        'format': f'bestvideo[height<={MAX_VIDEO_QUALITY}]+bestaudio/best[height<={MAX_VIDEO_QUALITY}]/best',  
        'merge_output_format': 'mp4',
        'writethumbnail': False,
        'embedthumbnail': False,
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            
        'nocheckcertificate': True,
        'noprogress': True,
        'quiet': False,
        'no_warnings': False,
        'updatetime': False,
        'clean_infojson': False,
        'postprocessor_args': [
            '-threads', '0'                     
        ]
    })  

    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=True)  
            filename = ydl.prepare_filename(info)  
            base_path, _ = os.path.splitext(filename)  

            final_path = f"{base_path}.mp4"
            for ext in [".mp4", ".webm", ".mkv"]:
                test_path = f"{base_path}{ext}"
                if os.path.isfile(test_path) and os.path.getsize(test_path) > 0:
                    final_path = test_path
                    break

            if not (os.path.isfile(final_path) and os.path.getsize(final_path) > 0):  
                raise RuntimeError("Downloaded file not found or is empty.")  

            logger.info(f"Successfully downloaded video: {final_path}")  

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

    except yt_dlp.utils.DownloadError as e:  
        logger.error(f"yt-dlp error downloading video for {url}: {e}")  
        raise RuntimeError(f"Download Error: {str(e)}")  
    except Exception as e:  
        logger.error(f"Unexpected error downloading video for {url}: {e}")  
        raise RuntimeError(f"Internal Server Error: {str(e)}")


@app.get("/", response_class=JSONResponse)
async def root():
    return {
        "name": "Anysnap Music API",
        "version": "3.0.0-Production",
        "status": "online"
    }

@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {
        "status": "healthy",
        "version": "3.0.0",
        "yt_dlp_version": yt_dlp.version.__version__,
        "cache_expiry_hours": CACHE_EXPIRE_HOURS
    }

@app.get("/search", response_class=JSONResponse)
async def search_youtube_music(
    q: str = Query(..., description="Search query"),
    limit: int = Query(1, description="Number of results to return (max 20)")
):
    try:
        logger.info(f"Received search request for query '{q}' with limit {limit}")
        actual_limit = min(max(1, limit), 20)  

        def perform_search():  
            return ytmusic.search(q, filter="songs", limit=actual_limit)  

        results = await asyncio.to_thread(perform_search)  

        formatted_results = []  
        for r in results:  
            artists = ", ".join([a.get("name", "") for a in r.get("artists", [])])  
            thumbnails = r.get("thumbnails", [])  
            thumbnail_url = thumbnails[-1].get("url") if thumbnails else None  

            formatted_results.append({  
                "title": r.get("title"),  
                "artist": artists,  
                "videoId": r.get("videoId"),  
                "duration": r.get("duration"),  
                "thumbnail": thumbnail_url  
            })  

        logger.info(f"Successfully completed search for query '{q}', returned {len(formatted_results)} result(s)")  

        if actual_limit == 1:  
            return formatted_results[0] if formatted_results else {}  

        return formatted_results  
    except Exception as e:  
        logger.error(f"Search error for query '{q}': {e}")  
        raise HTTPException(status_code=500, detail={"error": "Search failed", "message": str(e)})

@app.get("/thumbnail", response_class=JSONResponse)
async def get_thumbnail(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(fetch_thumbnail_sync, url)
        return result
    except Exception as e:
        logger.error(f"Thumbnail API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch thumbnail", "message": str(e)})

@app.get("/download", response_class=JSONResponse)
async def download_audio(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_audio_sync, url)
        return result
    except Exception as e:
        logger.error(f"Audio download API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Audio download failed", "message": str(e)})

@app.get("/video", response_class=JSONResponse)
async def download_video(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_video_sync, url)
        return result
    except Exception as e:
        logger.error(f"Video download API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Video download failed", "message": str(e)})

@app.get("/files/{filename}")
async def get_file(filename: str):
    filename = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        logger.warning(f"Requested file not found: {filename}")
        raise HTTPException(status_code=404, detail={"error": "File not found"})
    return FileResponse(path=file_path, filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)