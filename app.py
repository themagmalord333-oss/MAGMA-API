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
# DATABASE & CACHE SYSTEM
# ---------------------------------------------------------

def init_db():
    """Initializes the SQLite database for caching metadata safely."""
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
    """Retrieves cached metadata from SQLite and verifies file existence."""
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
    """Saves download metadata to SQLite."""
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
    """Fallback to check un-indexed files downloaded before SQLite was added."""
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
    """Background task to delete old files and clean up the database without blocking the event loop."""
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

                    # 1. Scan actual disk directory for expired files (covers orphans too)
                    if os.path.exists(DOWNLOAD_DIR):
                        for entry in os.scandir(DOWNLOAD_DIR):
                            if entry.is_file():
                                file_stat = entry.stat()
                                # st_mtime safely protects active downloads from being deleted
                                if file_stat.st_mtime < expiry_time:
                                    try:
                                        os.remove(entry.path)
                                        deleted_files += 1
                                        cur.execute("DELETE FROM downloads WHERE file_name = ?", (entry.name,))
                                    except Exception as e:
                                        logger.warning(f"Could not delete old file {entry.name}: {e}")

                    # 2. Sweep database for phantom records
                    cur.execute("SELECT id, file_path FROM downloads")
                    all_records = cur.fetchall()
                    for record in all_records:
                        if not os.path.exists(record['file_path']):
                            cur.execute("DELETE FROM downloads WHERE id = ?", (record['id'],))
                            db_cleaned += 1

                    conn.commit()
                return deleted_files, db_cleaned

            # Execute blocking I/O on a separate thread
            deleted_files, db_cleaned = await asyncio.to_thread(perform_cleanup)

            if deleted_files > 0 or db_cleaned > 0:
                logger.info(f"Cleanup complete: Deleted {deleted_files} old files on disk, cleared {db_cleaned} orphaned DB records.")
            else:
                logger.info("Cleanup complete: No expired files found.")

        except Exception as e:
            logger.error(f"Cache cleanup encountered an error (will retry next cycle): {e}")

        # Run cleanup every hour safely
        await asyncio.sleep(3600)

# ---------------------------------------------------------
# FASTAPI LIFESPAN (STARTUP/SHUTDOWN)
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting MAGMA Music API...")
    init_db()

    if COOKIE_URL:
        try:
            urllib.request.urlretrieve(COOKIE_URL, COOKIES_FILE)
            logger.info(f"Successfully downloaded cookies.txt from COOKIE_URL")
        except Exception as e:
            logger.error(f"Failed to download cookies from COOKIE_URL: {e}")

    # Start background cleanup loop
    cleanup_worker = asyncio.create_task(cache_cleanup_task())

    yield # App runs here

    # Shutdown
    logger.info("Shutting down MAGMA Music API...")
    cleanup_worker.cancel()

# ---------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------

app = FastAPI(title="YouTube Downloader & Search API", version="2.2.0-Production", lifespan=lifespan)
ytmusic = YTMusic()

# ---------------------------------------------------------
# YT-DLP HELPERS & DOWNLOADERS
# ---------------------------------------------------------

def extract_video_id(url: str) -> Optional[str]:
    """Extracts the 11-character YouTube Video ID from a given URL."""
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
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
        'continuedl': True, # Enable Download Resume
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github']
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

    # ⚡ MAXIMUM SPEED AUDIO OPTIMIZATIONS
    opts.update({  
        'format': '140/ba[ext=m4a]/bestaudio/best', # Fast 128k AAC source for lightning quick mp3 conversion
        'writethumbnail': False,
        'postprocessors': [{  
            'key': 'FFmpegExtractAudio',  
            'preferredcodec': 'mp3',  
            'preferredquality': '192',  
        }],
        'extractor_args': {'youtube': ['player_client=ios,android,web']}, # iOS/Android bypasses JS throttling
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            # 10MB HTTP chunking to max out connection
        'nocheckcertificate': True,
        'noprogress': True,
        'quiet': True,
        'no_warnings': True,
        'updatetime': False,                    # Stops wasted Disk I/O modifying timestamps
        'clean_infojson': False,
        'retries': 5,                           
        'fragment_retries': 5,                  
        'socket_timeout': 15,
        'postprocessor_args': [
            '-threads', '0',                    # Force FFmpeg to use ALL CPU cores for MP3 encoding
            '-vn', '-sn'                        # Strictly strip video/subs inside FFmpeg processing
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

    # ⚡ MAXIMUM SPEED VIDEO OPTIMIZATIONS
    opts.update({  
        'format': f'bestvideo[vcodec^=avc1][height<={MAX_VIDEO_QUALITY}]+bestaudio[acodec^=mp4a]/bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]',  
        'merge_output_format': 'mp4',
        'writethumbnail': False,
        'embedthumbnail': False,
        'extractor_args': {'youtube': ['player_client=ios,android,web']},
        'concurrent_fragment_downloads': 15,    
        'http_chunk_size': 10485760,            
        'nocheckcertificate': True,
        'noprogress': True,
        'quiet': True,
        'no_warnings': True,
        'updatetime': False,
        'clean_infojson': False,
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 15,
        'postprocessor_args': [
            '-threads', '0'                     # Accelerates the merging process via FFmpeg across all cores
        ]
        # ⚠️ Removed FFmpegVideoConvertor: The merge_output_format='mp4' flag merges natively without wasting CPU re-encoding.
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

# ---------------------------------------------------------
# API ROUTES
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "MAGMA Music API",
        "version": "2.2.0-Production",
        "status": "online"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.2.0",
        "yt_dlp_version": yt_dlp.version.__version__,
        "cache_expiry_hours": CACHE_EXPIRE_HOURS
    }

@app.get("/search")
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

@app.get("/thumbnail")
async def get_thumbnail(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(fetch_thumbnail_sync, url)
        return result
    except Exception as e:
        logger.error(f"Thumbnail API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch thumbnail", "message": str(e)})

@app.get("/download")
async def download_audio(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_audio_sync, url)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Audio download API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Audio download failed", "message": str(e)})

@app.get("/video")
async def download_video(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_video_sync, url)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Video download API error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Video download failed", "message": str(e)})

@app.get("/files/{filename}")
async def get_file(filename: str):
    filename = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        logger.warning(f"Requested file not found: {filename}")
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)