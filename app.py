import os
import re
import time
import asyncio
import sqlite3
import logging
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv
import yt_dlp
from ytmusicapi import YTMusic


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CACHE_EXPIRE_HOURS = float(os.getenv("CACHE_EXPIRE_HOURS", "24"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "720")
PORT = int(os.getenv("PORT", "8000"))

COOKIE_URL = os.getenv("COOKIE_URL", "")
COOKIES_FILE = "cookies.txt"
DB_FILE = "cache.db"

# Speed tuning
CONCURRENT_FRAGMENTS = int(
    os.getenv("CONCURRENT_FRAGMENTS", "25")
)

HTTP_CHUNK_SIZE = int(
    os.getenv("HTTP_CHUNK_SIZE", "10485760")
)  # 10 MB


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


# =========================================================
# DIRECTORIES
# =========================================================

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =========================================================
# DATABASE & CACHE
# =========================================================

def init_db():
    """Initialize SQLite cache database."""

    try:
        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:

            conn.execute("""
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
            """)

            conn.commit()

        logger.info("SQLite database initialized.")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")


def get_cached_metadata(
    video_id: str,
    file_type: str
) -> Optional[Dict[str, Any]]:

    try:

        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:

            conn.row_factory = sqlite3.Row

            cur = conn.cursor()

            cur.execute(
                """
                SELECT *
                FROM downloads
                WHERE video_id = ?
                AND file_type = ?
                """,
                (video_id, file_type)
            )

            row = cur.fetchone()

            if row:

                if (
                    os.path.isfile(row["file_path"])
                    and os.path.getsize(row["file_path"]) > 0
                ):

                    return dict(row)

                logger.warning(
                    f"Cached file missing: {row['file_name']}"
                )

                cur.execute(
                    "DELETE FROM downloads WHERE id = ?",
                    (row["id"],)
                )

                conn.commit()

            return None

    except Exception as e:

        logger.error(
            f"Error accessing cache DB: {e}"
        )

        return None


def save_cached_metadata(
    data: Dict[str, Any],
    file_type: str
):

    try:

        with sqlite3.connect(DB_FILE, timeout=15.0) as conn:

            conn.execute("""
                INSERT OR REPLACE INTO downloads
                (
                    video_id,
                    title,
                    file_name,
                    file_path,
                    file_type,
                    file_size,
                    duration,
                    created_time,
                    thumbnail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["videoId"],
                data["title"],
                data["filename"],
                data["path"],
                file_type,
                data["filesize"],
                data["duration"],
                time.time(),
                data["thumbnail"]
            ))

            conn.commit()

    except Exception as e:

        logger.error(
            f"Error saving cache metadata: {e}"
        )


def find_legacy_cached_file(
    video_id: str,
    ext: str
) -> Optional[str]:

    if not video_id:
        return None

    suffix = f"_{video_id}.{ext}"

    try:

        with os.scandir(DOWNLOAD_DIR) as entries:

            for entry in entries:

                if entry.is_file() and entry.name.endswith(suffix):
                    return entry.name

    except Exception as e:

        logger.error(
            f"Error reading {DOWNLOAD_DIR}: {e}"
        )

    return None


# =========================================================
# CACHE CLEANUP
# =========================================================

async def cache_cleanup_task():

    while True:

        try:

            logger.info(
                "Running advanced cache cleanup..."
            )

            expiry_time = (
                time.time()
                - (CACHE_EXPIRE_HOURS * 3600)
            )

            def perform_cleanup():

                deleted_files = 0
                db_cleaned = 0

                with sqlite3.connect(
                    DB_FILE,
                    timeout=15.0
                ) as conn:

                    conn.row_factory = sqlite3.Row

                    cur = conn.cursor()

                    # -------------------------------------------------
                    # Remove expired files
                    # -------------------------------------------------

                    if os.path.exists(DOWNLOAD_DIR):

                        for entry in os.scandir(
                            DOWNLOAD_DIR
                        ):

                            if not entry.is_file():
                                continue

                            try:

                                file_stat = entry.stat()

                                if (
                                    file_stat.st_mtime
                                    < expiry_time
                                ):

                                    os.remove(entry.path)

                                    deleted_files += 1

                                    cur.execute(
                                        """
                                        DELETE FROM downloads
                                        WHERE file_name = ?
                                        """,
                                        (entry.name,)
                                    )

                            except Exception as e:

                                logger.warning(
                                    f"Could not delete "
                                    f"{entry.name}: {e}"
                                )

                    # -------------------------------------------------
                    # Remove phantom DB records
                    # -------------------------------------------------

                    cur.execute(
                        "SELECT id, file_path FROM downloads"
                    )

                    records = cur.fetchall()

                    for record in records:

                        if not os.path.exists(
                            record["file_path"]
                        ):

                            cur.execute(
                                """
                                DELETE FROM downloads
                                WHERE id = ?
                                """,
                                (record["id"],)
                            )

                            db_cleaned += 1

                    conn.commit()

                return deleted_files, db_cleaned

            deleted_files, db_cleaned = (
                await asyncio.to_thread(
                    perform_cleanup
                )
            )

            if deleted_files or db_cleaned:

                logger.info(
                    f"Cleanup complete: "
                    f"deleted={deleted_files}, "
                    f"db_cleaned={db_cleaned}"
                )

            else:

                logger.info(
                    "Cleanup complete: "
                    "No expired files found."
                )

        except Exception as e:

            logger.error(
                f"Cache cleanup error: {e}"
            )

        await asyncio.sleep(3600)


# =========================================================
# FASTAPI LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(
        "Starting MAGMA Music API..."
    )

    init_db()

    # -----------------------------------------------------
    # Download cookies
    # -----------------------------------------------------

    if COOKIE_URL:

        try:

            urllib.request.urlretrieve(
                COOKIE_URL,
                COOKIES_FILE
            )

            logger.info(
                "Successfully downloaded cookies.txt"
            )

        except Exception as e:

            logger.error(
                f"Failed to download cookies: {e}"
            )

    # -----------------------------------------------------
    # Background cleanup
    # -----------------------------------------------------

    cleanup_worker = asyncio.create_task(
        cache_cleanup_task()
    )

    yield

    # -----------------------------------------------------
    # Shutdown
    # -----------------------------------------------------

    logger.info(
        "Shutting down MAGMA Music API..."
    )

    cleanup_worker.cancel()

    try:
        await cleanup_worker
    except asyncio.CancelledError:
        pass


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="YouTube Downloader & Search API",
    version="2.3.0-Speed",
    lifespan=lifespan
)

ytmusic = YTMusic()


# =========================================================
# YOUTUBE VIDEO ID
# =========================================================

def extract_video_id(
    url: str
) -> Optional[str]:

    if not url:
        return None

    if re.match(
        r"^[0-9A-Za-z_-]{11}$",
        url
    ):
        return url

    pattern = (
        r"(?:youtu\.be/|v=|/shorts/|"
        r"/embed/|/v/)"
        r"([0-9A-Za-z_-]{11})"
    )

    match = re.search(
        pattern,
        url
    )

    if match:
        return match.group(1)

    match = re.search(
        r"[0-9A-Za-z_-]{11}",
        url
    )

    return (
        match.group(0)
        if match
        else None
    )


# =========================================================
# BASE YT-DLP OPTIONS
# =========================================================

def get_base_ydl_opts() -> Dict[str, Any]:

    opts = {

        # Filename
        "outtmpl":
            f"{DOWNLOAD_DIR}/"
            "%(title).150s_%(id)s.%(ext)s",

        "restrictfilenames": True,
        "noplaylist": True,

        # Logging
        "quiet": False,
        "no_warnings": False,

        # Network
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,

        # Resume
        "continuedl": True,

        # YouTube JS challenge support
        "js_runtimes": {
            "node": {}
        },

        "remote_components": [
            "ejs:github"
        ],
    }

    if os.path.exists(COOKIES_FILE):

        opts["cookiefile"] = COOKIES_FILE

        logger.info(
            f"Loaded cookies from {COOKIES_FILE}"
        )

    return opts


# =========================================================
# YT-DLP EXTRACTION WITH FALLBACK
# =========================================================

def extract_youtube_with_fallback(
    url: str,
    opts: Dict[str, Any],
    download: bool = True
) -> Dict[str, Any]:

    strategies = [

        (
            "default",
            {}
        ),

        (
            "default-web_embedded",
            {
                "youtube": {
                    "player_client": [
                        "default",
                        "web_embedded"
                    ]
                }
            }
        ),
    ]

    last_error = None

    for name, extractor_args in strategies:

        try:

            attempt_opts = dict(opts)

            if extractor_args:

                attempt_opts[
                    "extractor_args"
                ] = extractor_args

            logger.info(
                f"▶️ YouTube strategy: {name}"
            )

            with yt_dlp.YoutubeDL(
                attempt_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=download
                )

            logger.info(
                f"✅ Extraction successful: {name}"
            )

            return info

        except yt_dlp.utils.DownloadError as e:

            last_error = e

            logger.warning(
                f"❌ Strategy failed: "
                f"{name} | {e}"
            )

    raise RuntimeError(
        "All YouTube extraction strategies failed: "
        f"{last_error}"
    )


# =========================================================
# THUMBNAIL
# =========================================================

def fetch_thumbnail_sync(
    url: str
) -> Dict[str, Any]:

    opts = get_base_ydl_opts()

    opts["skip_download"] = True

    try:

        info = extract_youtube_with_fallback(
            url,
            opts,
            download=False
        )

        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "videoId": info.get("id")
        }

    except Exception as e:

        logger.error(
            f"Thumbnail fetch error: {e}"
        )

        raise RuntimeError(
            f"Failed to fetch thumbnail: {str(e)}"
        )


# =========================================================
# AUDIO DOWNLOAD
# =========================================================

def download_audio_sync(
    url: str
) -> Dict[str, Any]:

    video_id = extract_video_id(url)

    # -----------------------------------------------------
    # DATABASE CACHE
    # -----------------------------------------------------

    if video_id:

        cached_data = get_cached_metadata(
            video_id,
            "mp3"
        )

        if cached_data:

            logger.info(
                f"Database cache hit: {video_id}"
            )

            return {
                "status": True,
                "title": cached_data["title"],
                "duration": cached_data["duration"],
                "thumbnail": cached_data["thumbnail"],
                "filename": cached_data["file_name"],
                "path": cached_data["file_path"],
                "download_url":
                    f"/files/"
                    f"{cached_data['file_name']}",
                "videoId": video_id,
                "uploader": "Cached",
                "filesize": cached_data["file_size"]
            }

        # -------------------------------------------------
        # Legacy cache
        # -------------------------------------------------

        legacy_file = find_legacy_cached_file(
            video_id,
            "mp3"
        )

        if legacy_file:

            path = os.path.join(
                DOWNLOAD_DIR,
                legacy_file
            )

            if (
                os.path.isfile(path)
                and os.path.getsize(path) > 0
            ):

                logger.info(
                    f"Legacy cache hit: {video_id}"
                )

                data = {
                    "videoId": video_id,
                    "title":
                        legacy_file[
                            :-len(
                                f"_{video_id}.mp3"
                            )
                        ],
                    "filename": legacy_file,
                    "path": path,
                    "type": "mp3",
                    "filesize":
                        os.path.getsize(path),
                    "duration": 0,
                    "thumbnail":
                        f"https://i.ytimg.com/"
                        f"vi/{video_id}/"
                        f"hqdefault.jpg"
                }

                save_cached_metadata(
                    data,
                    "mp3"
                )

                data["status"] = True

                data["download_url"] = (
                    f"/files/{legacy_file}"
                )

                data["uploader"] = "Cached"

                return data

    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    logger.info(
        f"Starting audio download: {url}"
    )

    opts = get_base_ydl_opts()

    opts.update({

        # Fast audio source
        "format":
            "140/ba[ext=m4a]/bestaudio/best",

        # No thumbnail
        "writethumbnail": False,

        # MP3 conversion
        "postprocessors": [
            {
                "key":
                    "FFmpegExtractAudio",

                "preferredcodec":
                    "mp3",

                "preferredquality":
                    "192",
            }
        ],

        # SPEED
        "concurrent_fragment_downloads":
            CONCURRENT_FRAGMENTS,

        "http_chunk_size":
            HTTP_CHUNK_SIZE,

        # Network
        "nocheckcertificate": True,
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "updatetime": False,

        "clean_infojson": False,

        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 15,

        # FFmpeg
        "postprocessor_args": [
            "-threads",
            "0",
            "-vn",
            "-sn"
        ],
    })

    try:

        info = extract_youtube_with_fallback(
            url,
            opts,
            download=True
        )

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            filename = ydl.prepare_filename(
                info
            )

        base_path, _ = os.path.splitext(
            filename
        )

        final_path = (
            f"{base_path}.mp3"
        )

        if (
            not os.path.isfile(final_path)
            or os.path.getsize(final_path) == 0
        ):

            raise RuntimeError(
                "Downloaded audio file "
                "is missing or empty."
            )

        logger.info(
            f"Audio downloaded: {final_path}"
        )

        response_data = {

            "status": True,

            "title":
                info.get("title", ""),

            "duration":
                info.get("duration", 0),

            "thumbnail":
                info.get("thumbnail", ""),

            "filename":
                os.path.basename(final_path),

            "path":
                final_path,

            "download_url":
                f"/files/"
                f"{os.path.basename(final_path)}",

            "videoId":
                info.get("id"),

            "uploader":
                info.get("uploader"),

            "filesize":
                os.path.getsize(final_path)
        }

        save_cached_metadata(
            response_data,
            "mp3"
        )

        return response_data

    except yt_dlp.utils.DownloadError as e:

        logger.error(
            f"yt-dlp audio error: {e}"
        )

        raise RuntimeError(
            f"Download Error: {str(e)}"
        )

    except Exception as e:

        logger.error(
            f"Audio download error: {e}"
        )

        raise RuntimeError(
            f"Internal Server Error: {str(e)}"
        )


# =========================================================
# VIDEO DOWNLOAD
# =========================================================

def download_video_sync(
    url: str
) -> Dict[str, Any]:

    video_id = extract_video_id(url)

    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    if video_id:

        cached_data = get_cached_metadata(
            video_id,
            "mp4"
        )

        if cached_data:

            logger.info(
                f"Database cache hit: {video_id}"
            )

            return {
                "status": True,
                "title":
                    cached_data["title"],
                "thumbnail":
                    cached_data["thumbnail"],
                "filename":
                    cached_data["file_name"],
                "path":
                    cached_data["file_path"],
                "download_url":
                    f"/files/"
                    f"{cached_data['file_name']}",
                "duration":
                    cached_data["duration"],
                "videoId":
                    video_id,
                "uploader":
                    "Cached",
                "filesize":
                    cached_data["file_size"]
            }

        # -------------------------------------------------
        # Legacy cache
        # -------------------------------------------------

        legacy_file = find_legacy_cached_file(
            video_id,
            "mp4"
        )

        if legacy_file:

            path = os.path.join(
                DOWNLOAD_DIR,
                legacy_file
            )

            if (
                os.path.isfile(path)
                and os.path.getsize(path) > 0
            ):

                logger.info(
                    f"Legacy cache hit: {video_id}"
                )

                data = {
                    "videoId": video_id,

                    "title":
                        legacy_file[
                            :-len(
                                f"_{video_id}.mp4"
                            )
                        ],

                    "filename":
                        legacy_file,

                    "path":
                        path,

                    "type":
                        "mp4",

                    "filesize":
                        os.path.getsize(path),

                    "duration":
                        0,

                    "thumbnail":
                        f"https://i.ytimg.com/"
                        f"vi/{video_id}/"
                        f"hqdefault.jpg"
                }

                save_cached_metadata(
                    data,
                    "mp4"
                )

                data["status"] = True

                data["download_url"] = (
                    f"/files/{legacy_file}"
                )

                data["uploader"] = "Cached"

                return data

    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    logger.info(
        f"Starting video download: {url}"
    )

    opts = get_base_ydl_opts()

    opts.update({

        # Up to MAX_VIDEO_QUALITY
        "format":
            f"bv*[height<="
            f"{MAX_VIDEO_QUALITY}]"
            f"[ext=mp4]"
            f"+ba[ext=m4a]"
            f"/b[height<="
            f"{MAX_VIDEO_QUALITY}]"
            f"[ext=mp4]"
            f"/best",

        "merge_output_format":
            "mp4",

        # No unnecessary thumbnail work
        "writethumbnail":
            False,

        "embedthumbnail":
            False,

        # SPEED
        "concurrent_fragment_downloads":
            CONCURRENT_FRAGMENTS,

        "http_chunk_size":
            HTTP_CHUNK_SIZE,

        # Network
        "nocheckcertificate":
            True,

        "noprogress":
            True,

        "quiet":
            True,

        "no_warnings":
            True,

        "updatetime":
            False,

        "clean_infojson":
            False,

        "retries":
            5,

        "fragment_retries":
            5,

        "socket_timeout":
            15,

        # FFmpeg
        "postprocessor_args": [
            "-threads",
            "0"
        ],
    })

    try:

        info = extract_youtube_with_fallback(
            url,
            opts,
            download=True
        )

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            filename = ydl.prepare_filename(
                info
            )

        base_path, _ = os.path.splitext(
            filename
        )

        # -------------------------------------------------
        # Find final output
        # -------------------------------------------------

        final_path = (
            f"{base_path}.mp4"
        )

        for ext in (
            ".mp4",
            ".webm",
            ".mkv"
        ):

            test_path = (
                f"{base_path}{ext}"
            )

            if (
                os.path.isfile(test_path)
                and os.path.getsize(test_path) > 0
            ):

                final_path = test_path
                break

        if not (
            os.path.isfile(final_path)
            and os.path.getsize(final_path) > 0
        ):

            raise RuntimeError(
                "Downloaded video file "
                "not found or empty."
            )

        logger.info(
            f"Video downloaded: {final_path}"
        )

        response_data = {

            "status": True,

            "title":
                info.get("title", ""),

            "thumbnail":
                info.get("thumbnail", ""),

            "filename":
                os.path.basename(final_path),

            "path":
                final_path,

            "download_url":
                f"/files/"
                f"{os.path.basename(final_path)}",

            "duration":
                info.get("duration", 0),

            "videoId":
                info.get("id"),

            "uploader":
                info.get("uploader"),

            "filesize":
                os.path.getsize(final_path)
        }

        save_cached_metadata(
            response_data,
            "mp4"
        )

        return response_data

    except yt_dlp.utils.DownloadError as e:

        logger.error(
            f"yt-dlp video error: {e}"
        )

        raise RuntimeError(
            f"Download Error: {str(e)}"
        )

    except Exception as e:

        logger.error(
            f"Video download error: {e}"
        )

        raise RuntimeError(
            f"Internal Server Error: {str(e)}"
        )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
async def root():

    return {
        "name":
            "MAGMA Music API",

        "version":
            "2.3.0-Speed",

        "status":
            "online"
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
async def health_check():

    return {

        "status":
            "healthy",

        "version":
            "2.3.0",

        "yt_dlp_version":
            yt_dlp.version.__version__,

        "cache_expiry_hours":
            CACHE_EXPIRE_HOURS,

        "concurrent_fragments":
            CONCURRENT_FRAGMENTS,

        "http_chunk_size":
            HTTP_CHUNK_SIZE,

        "max_video_quality":
            MAX_VIDEO_QUALITY
    }


# =========================================================
# SEARCH
# =========================================================

@app.get("/search")
async def search_youtube_music(

    q: str = Query(
        ...,
        description="Search query"
    ),

    limit: int = Query(
        1,
        description=
        "Number of results "
        "to return (max 20)"
    )
):

    try:

        logger.info(
            f"Search request: "
            f"'{q}' limit={limit}"
        )

        actual_limit = min(
            max(1, limit),
            20
        )

        def perform_search():

            return ytmusic.search(
                q,
                filter="songs",
                limit=actual_limit
            )

        results = await asyncio.to_thread(
            perform_search
        )

        formatted_results = []

        for r in results:

            artists = ", ".join(
                [
                    a.get("name", "")
                    for a in r.get(
                        "artists",
                        []
                    )
                ]
            )

            thumbnails = r.get(
                "thumbnails",
                []
            )

            thumbnail_url = (
                thumbnails[-1].get("url")
                if thumbnails
                else None
            )

            formatted_results.append({

                "title":
                    r.get("title"),

                "artist":
                    artists,

                "videoId":
                    r.get("videoId"),

                "duration":
                    r.get("duration"),

                "thumbnail":
                    thumbnail_url
            })

        logger.info(
            f"Search completed: "
            f"{len(formatted_results)} results"
        )

        if actual_limit == 1:

            return (
                formatted_results[0]
                if formatted_results
                else {}
            )

        return formatted_results

    except Exception as e:

        logger.error(
            f"Search error: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Search failed",

                "message":
                    str(e)
            }
        )


# =========================================================
# THUMBNAIL API
# =========================================================

@app.get("/thumbnail")
async def get_thumbnail(

    url: str = Query(
        ...,
        description="YouTube URL"
    )
):

    try:

        result = await asyncio.to_thread(
            fetch_thumbnail_sync,
            url
        )

        return result

    except Exception as e:

        logger.error(
            f"Thumbnail API error: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Failed to fetch thumbnail",

                "message":
                    str(e)
            }
        )


# =========================================================
# AUDIO API
# =========================================================

@app.get("/download")
async def download_audio(

    url: str = Query(
        ...,
        description="YouTube URL"
    )
):

    try:

        result = await asyncio.to_thread(
            download_audio_sync,
            url
        )

        return JSONResponse(
            content=result
        )

    except Exception as e:

        logger.error(
            f"Audio download API error: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Audio download failed",

                "message":
                    str(e)
            }
        )


# =========================================================
# VIDEO API
# =========================================================

@app.get("/video")
async def download_video(

    url: str = Query(
        ...,
        description="YouTube URL"
    )
):

    try:

        result = await asyncio.to_thread(
            download_video_sync,
            url
        )

        return JSONResponse(
            content=result
        )

    except Exception as e:

        logger.error(
            f"Video download API error: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Video download failed",

                "message":
                    str(e)
            }
        )


# =========================================================
# FILE SERVER
# =========================================================

@app.get("/files/{filename}")
async def get_file(
    filename: str
):

    # Prevent path traversal
    filename = os.path.basename(
        filename
    )

    file_path = os.path.join(
        DOWNLOAD_DIR,
        filename
    )

    if not os.path.isfile(
        file_path
    ):

        logger.warning(
            f"Requested file not found: "
            f"{filename}"
        )

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return FileResponse(
        path=file_path,
        filename=filename
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=1
    )