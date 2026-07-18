import os
import re
import asyncio
import logging
import urllib.request
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
import yt_dlp
from ytmusicapi import YTMusic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
COOKIE_URL = os.environ.get("COOKIE_URL")

# Restore automatic cookies download from COOKIE_URL on startup
if COOKIE_URL:
    try:
        urllib.request.urlretrieve(COOKIE_URL, COOKIES_FILE)
        logger.info(f"Successfully downloaded cookies.txt from COOKIE_URL")
    except Exception as e:
        logger.error(f"Failed to download cookies from COOKIE_URL: {e}")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI(title="YouTube Downloader & Search API", version="1.0.0")
ytmusic = YTMusic()

def sanitize_filename(filename: str) -> str:
    if not filename:
        return "download"
    sanitized = re.sub(r'[\/*?:"<>|]', "", filename)
    return sanitized.strip()

def extract_video_id(url: str) -> Optional[str]:
    """Extracts the 11-character YouTube Video ID from a given URL."""
    if not url:
        return None
    if re.match(r"^[0-9A-Za-z_-]{11}$", url):
        return url

    pattern = r"(?:youtu\.be\/|v=|\/shorts\/|\/embed\/|\/v\/)([0-9A-Za-z_-]{11})"  
    match = re.search(pattern, url)  
    if match:  
        return match.group(1)  

    match = re.search(r"[0-9A-Za-z_-]{11}", url)  
    return match.group(0) if match else None

def find_cached_file(video_id: str, ext: str) -> Optional[str]:
    """Searches the downloads directory for an existing file with the given video ID and extension."""
    if not video_id:
        return None
    suffix = f"_{video_id}.{ext}"
    try:
        for filename in os.listdir(DOWNLOAD_DIR):
            if filename.endswith(suffix):
                return filename
    except Exception as e:
        logger.error(f"Error reading {DOWNLOAD_DIR}: {e}")
    return None

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
    except yt_dlp.utils.DownloadError as e:  
        logger.error(f"yt-dlp error fetching thumbnail for {url}: {e}")  
        raise RuntimeError(f"Download Error: {str(e)}")  
    except Exception as e:  
        logger.error(f"Unexpected error fetching thumbnail for {url}: {e}")  
        raise RuntimeError(f"Internal Server Error: {str(e)}")

def download_audio_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)

    # 1. Check for existing MP3 cache file directly on disk  
    if video_id:  
        cached_filename = find_cached_file(video_id, "mp3")  
        if cached_filename:  
            final_path = os.path.join(DOWNLOAD_DIR, cached_filename)  
            if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:  
                logger.info(f"Cache hit! Returning existing audio for {video_id} without running yt-dlp")  

                # Extract title from filename (removing the _videoId.mp3 part)  
                title = cached_filename[:-len(f"_{video_id}.mp3")]  

                return {  
                    "status": True,  
                    "title": title,  
                    "duration": 0,  
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",  
                    "filename": cached_filename,  
                    "path": final_path,  
                    "download_url": f"/files/{cached_filename}",  
                    "videoId": video_id,  
                    "uploader": "Cached",  
                    "filesize": os.path.getsize(final_path)  
                }  

    # 2. Proceed with yt-dlp download if no cache exists  
    opts = get_base_ydl_opts()  
    
    # =========================================================================
    # AUDIO DOWNLOAD OPTIMIZATIONS APPLIED FOR MAXIMUM SPEED:
    # 
    # 1. format: '139/worstaudio/bestaudio'
    #    - 139 is the lowest bitrate M4A (~48kbps). 
    #    - worstaudio acts as a fallback to the absolute smallest available file. 
    #    - Smaller file size translates to drastically faster download times.
    #
    # 2. preferredquality: '32'
    #    - Lowering the target MP3 bitrate to 32 kbps minimizes FFmpeg CPU workload 
    #    - and reduces disk write operations to near zero, speeding up the post-processing phase.
    #
    # 3. nocheckcertificate: True
    #    - Skips SSL certificate validation overhead during network connections.
    #
    # 4. noprogress, quiet, no_warnings: True
    #    - Disables all terminal I/O during download, preventing process blocking.
    #
    # 5. concurrent_fragment_downloads: 10
    #    - Downloads multiple DASH segments at once to saturate bandwidth.
    #
    # 6. http_chunk_size: 10485760 (10MB)
    #    - Defeats potential HTTP throttling by requesting chunks instead of the whole file.
    #
    # 7. postprocessor_args: ['-threads', '0', '-vn', '-sn']
    #    - '-threads 0' forces FFmpeg to use all available CPU cores.
    #    - '-vn' (no video) and '-sn' (no subtitles) ensures FFmpeg skips unnecessary stream parsing.
    #
    # 8. retries (3), fragment_retries (3), socket_timeout (15)
    #    - Fails faster on dead connections instead of hanging for extended periods.
    # =========================================================================
    opts.update({  
        'format': '139/worstaudio/bestaudio',  
        'postprocessors': [{  
            'key': 'FFmpegExtractAudio',  
            'preferredcodec': 'mp3',  
            'preferredquality': '32',  
        }],
        'concurrent_fragment_downloads': 10,
        'http_chunk_size': 10485760,  
        'nocheckcertificate': True,
        'noprogress': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 15,
        'postprocessor_args': [
            '-threads', '0', 
            '-vn', 
            '-sn'
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

            return {  
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

    except yt_dlp.utils.DownloadError as e:  
        logger.error(f"yt-dlp error downloading audio for {url}: {e}")  
        raise RuntimeError(f"Download Error: {str(e)}")  
    except Exception as e:  
        logger.error(f"Unexpected error downloading audio for {url}: {e}")  
        raise RuntimeError(f"Internal Server Error: {str(e)}")

def download_video_sync(url: str) -> Dict[str, Any]:
    video_id = extract_video_id(url)

    # 1. Check for existing MP4 cache file directly on disk  
    if video_id:  
        cached_filename = find_cached_file(video_id, "mp4")  
        if cached_filename:  
            final_path = os.path.join(DOWNLOAD_DIR, cached_filename)  
            if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:  
                logger.info(f"Cache hit! Returning existing video for {video_id} without running yt-dlp")  

                # Extract title from filename (removing the _videoId.mp4 part)  
                title = cached_filename[:-len(f"_{video_id}.mp4")]  

                return {  
                    "status": True,  
                    "title": title,  
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",  
                    "filename": cached_filename,  
                    "path": final_path,  
                    "download_url": f"/files/{cached_filename}",  
                    "duration": 0,  
                    "videoId": video_id,  
                    "uploader": "Cached",  
                    "filesize": os.path.getsize(final_path)  
                }  

    # 2. Proceed with yt-dlp download if no cache exists  
    opts = get_base_ydl_opts()  
    opts.update({  
        'format': 'bestvideo+bestaudio/best',  
        'merge_output_format': 'mp4'  
    })  

    try:  
        with yt_dlp.YoutubeDL(opts) as ydl:  
            info = ydl.extract_info(url, download=True)  
            filename = ydl.prepare_filename(info)  
            base_path, _ = os.path.splitext(filename)  

            final_path = filename
            for ext in [".mp4", ".webm", ".mkv"]:
                test_path = f"{base_path}{ext}"
                if os.path.isfile(test_path) and os.path.getsize(test_path) > 0:
                    final_path = test_path
                    break

            if not (os.path.isfile(final_path) and os.path.getsize(final_path) > 0):  
                raise RuntimeError("Downloaded file not found or is empty.")  

            logger.info(f"Successfully downloaded video: {final_path}")  

            return {  
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

    except yt_dlp.utils.DownloadError as e:  
        logger.error(f"yt-dlp error downloading video for {url}: {e}")  
        raise RuntimeError(f"Download Error: {str(e)}")  
    except Exception as e:  
        logger.error(f"Unexpected error downloading video for {url}: {e}")  
        raise RuntimeError(f"Internal Server Error: {str(e)}")

@app.get("/")
async def root():
    return {
        "name": "MAGMA Music API",
        "version": "2.0.0",
        "status": "online"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "yt_dlp_version": yt_dlp.version.__version__
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
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch thumbnail", "message": str(e)})

@app.get("/download")
async def download_audio(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_audio_sync, url)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Audio download failed", "message": str(e)})

@app.get("/video")
async def download_video(url: str = Query(..., description="YouTube URL")):
    try:
        result = await asyncio.to_thread(download_video_sync, url)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Video download failed", "message": str(e)})

@app.get("/files/{filename}")
async def get_file(filename: str):
    filename = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)