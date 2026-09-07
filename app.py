import re
import sys
import time
import asyncio
import sqlite3
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

# ============================================================
# CONFIG
# ============================================================

load_dotenv = None
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except Exception:
    pass

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads")).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

CACHE_EXPIRE_HOURS = float(os.getenv("CACHE_EXPIRE_HOURS", "24"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "720")

PORT = int(os.getenv("PORT", "8000"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
DB_FILE = os.getenv("DB_FILE", "cache.db")

CONCURRENT_FRAGMENTS = int(os.getenv("CONCURRENT_FRAGMENTS", "64"))
HTTP_CHUNK_SIZE = os.getenv("HTTP_CHUNK_SIZE", "100M")
SOCKET_TIMEOUT = int(os.getenv("SOCKET_TIMEOUT", "20"))
RETRIES = int(os.getenv("RETRIES", "10"))
FRAGMENT_RETRIES = int(os.getenv("FRAGMENT_RETRIES", "10"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - MagmaAPI: %(message)s",
)
logger = logging.getLogger("MagmaAPI")


# ============================================================
# SQLITE CACHE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = db_connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(video_id, file_type)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_downloads_lookup
        ON downloads(video_id, file_type)
    """)
    conn.commit()
    conn.close()


def cache_get(video_id: str, file_type: str) -> Optional[str]:
    conn = db_connect()
    row = conn.execute(
        """
        SELECT file_path, created_at
        FROM downloads
        WHERE video_id=? AND file_type=?
        """,
        (video_id, file_type),
    ).fetchone()
    conn.close()

    if not row:
        return None

    path, created_at = row

    if not os.path.isfile(path):
        return None

    if CACHE_EXPIRE_HOURS > 0:
        if time.time() - created_at > CACHE_EXPIRE_HOURS * 3600:
            return None

    return path


def cache_put(video_id: str, file_type: str, path: str):
    conn = db_connect()
    conn.execute(
        """
        INSERT INTO downloads(video_id, file_type, file_path, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(video_id, file_type)
        DO UPDATE SET
            file_path=excluded.file_path,
            created_at=excluded.created_at
        """,
        (video_id, file_type, path, time.time()),
    )
    conn.commit()
    conn.close()


def cleanup_cache():
    conn = db_connect()

    rows = conn.execute(
        "SELECT id, file_path, created_at FROM downloads"
    ).fetchall()

    now = time.time()
    max_age = CACHE_EXPIRE_HOURS * 3600

    for row_id, path, created_at in rows:
        remove = not os.path.isfile(path)

        if (
            not remove
            and CACHE_EXPIRE_HOURS > 0
            and now - created_at > max_age
        ):
            remove = True

        if remove:
            conn.execute(
                "DELETE FROM downloads WHERE id=?",
                (row_id,),
            )

    conn.commit()
    conn.close()


# ============================================================
# YOUTUBE HELPERS
# ============================================================

def youtube_video_id(url: str) -> Optional[str]:
    patterns = (
        r"(?:v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:/embed/)([A-Za-z0-9_-]{11})",
    )

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def parse_chunk_size(value: str) -> int:
    value = str(value).strip().upper()

    try:
        if value.endswith("M"):
            return int(float(value[:-1]) * 1024 * 1024)
        if value.endswith("K"):
            return int(float(value[:-1]) * 1024)
        if value.endswith("G"):
            return int(float(value[:-1]) * 1024 * 1024 * 1024)
        return int(value)
    except ValueError:
        return 100 * 1024 * 1024


def common_yt_args():
    args = [
        "--no-playlist",

        "--retries", str(RETRIES),
        "--fragment-retries", str(FRAGMENT_RETRIES),
        "--file-access-retries", "5",

        "--socket-timeout", str(SOCKET_TIMEOUT),

        "--continue",

        "--concurrent-fragments",
        str(CONCURRENT_FRAGMENTS),

        "--http-chunk-size",
        str(HTTP_CHUNK_SIZE),

        "--js-runtimes",
        "node",

        "--remote-components",
        "ejs:github",

        "--no-check-certificates",

        # IMPORTANT:
        # No --no-part here.
        # .part files remain available for resume.

        "--restrict-filenames",
        "--newline",
        "--no-warnings",

        "-o",
        str(
            DOWNLOAD_DIR
            / "%(title).150s_%(id)s.%(ext)s"
        ),
    ]

    cookie_path = Path(COOKIES_FILE)

    if cookie_path.is_file():
        args.extend([
            "--cookies",
            str(cookie_path.resolve()),
        ])

    return args


# ============================================================
# INDEPENDENT YT-DLP SUBPROCESS
# ============================================================

async def run_ytdlp(args):
    """
    One independent yt-dlp subprocess for each API request.

    There is:
      - no asyncio.to_thread()
      - no application-level download queue
      - no semaphore
      - no global download lock

    Each incoming request can launch its own process immediately.
    """

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        *args,
    ]

    logger.info(
        "Starting independent yt-dlp process"
    )

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    output = []

    async def drain_output():
        while True:
            line = await process.stdout.readline()

            if not line:
                break

            text = line.decode(
                "utf-8",
                errors="replace",
            ).strip()

            if text:
                output.append(text)

                # Keep server logs useful without making them huge.
                if (
                    "[download]" not in text
                    or "%" not in text
                ):
                    logger.info(
                        "yt-dlp: %s",
                        text[-500:],
                    )

    reader = asyncio.create_task(
        drain_output()
    )

    try:
        return_code = await process.wait()
        await reader

    except asyncio.CancelledError:
        logger.warning(
            "API task cancelled; terminating yt-dlp process"
        )

        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

        raise

    if return_code != 0:
        error = "\n".join(output[-40:])

        raise RuntimeError(
            f"yt-dlp failed ({return_code}):\n{error}"
        )

    # --print after_move:filepath is handled by callers.
    # Find the final existing path from the output.
    for line in reversed(output):
        candidate = line.strip()

        if not candidate:
            continue

        candidate_path = Path(candidate)

        if candidate_path.is_file():
            return str(candidate_path.resolve())

    raise RuntimeError(
        "yt-dlp completed but output file was not found."
    )


# ============================================================
# FILE DISCOVERY
# ============================================================

def find_media_file(
    video_id: str,
    file_type: str,
):
    suffix = ".mp3" if file_type == "audio" else ".mp4"

    candidates = []

    for path in DOWNLOAD_DIR.iterdir():
        if not path.is_file():
            continue

        if video_id not in path.name:
            continue

        if path.suffix.lower() != suffix:
            continue

        candidates.append(path)

    if not candidates:
        return None

    candidates.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return str(candidates[0].resolve())


# ============================================================
# AUDIO / VIDEO DOWNLOAD COMMANDS
# ============================================================

async def download_audio_fast(url: str):
    video_id = youtube_video_id(url)

    if not video_id:
        raise ValueError(
            "Invalid YouTube URL"
        )

    cached = cache_get(
        video_id,
        "audio",
    )

    if cached:
        logger.info(
            "Audio cache hit: %s",
            video_id,
        )
        return cached

    args = common_yt_args()

    args.extend([
        "--format",
        "140/ba[ext=m4a]/bestaudio/best",

        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",

        "--print",
        "after_move:filepath",

        url,
    ])

    result = await run_ytdlp(args)

    # Prefer the actual final MP3.
    if not result.lower().endswith(".mp3"):
        found = find_media_file(
            video_id,
            "audio",
        )

        if found:
            result = found

    if not os.path.isfile(result):
        raise FileNotFoundError(
            "Audio output file was not found."
        )

    cache_put(
        video_id,
        "audio",
        result,
    )

    return result


async def download_video_fast(url: str):
    video_id = youtube_video_id(url)

    if not video_id:
        raise ValueError(
            "Invalid YouTube URL"
        )

    cached = cache_get(
        video_id,
        "video",
    )

    if cached:
        logger.info(
            "Video cache hit: %s",
            video_id,
        )
        return cached

    args = common_yt_args()

    args.extend([
        "--format",
        (
            f"bv*[height<={MAX_VIDEO_QUALITY}]"
            f"[ext=mp4]+ba[ext=m4a]"
            f"/b[height<={MAX_VIDEO_QUALITY}]"
            f"[ext=mp4]/best"
        ),

        "--merge-output-format",
        "mp4",

        "--print",
        "after_move:filepath",

        url,
    ])

    result = await run_ytdlp(args)

    if not result.lower().endswith(".mp4"):
        found = find_media_file(
            video_id,
            "video",
        )

        if found:
            result = found

    if not os.path.isfile(result):
        raise FileNotFoundError(
            "Video output file was not found."
        )

    cache_put(
        video_id,
        "video",
        result,
    )

    return result


# ============================================================
# FASTAPI
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cleanup_cache()

    logger.info(
        "Magma API started"
    )

    yield

    logger.info(
        "Magma API stopped"
    )


app = FastAPI(
    title="Magma API",
    version="1.0",
    description="Simple developer media API",
    lifespan=lifespan,
)


# ============================================================
# FRONTEND
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Magma API — Developer Portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@600;700&family=Inter:wght@400;500;600;700;800&family=Patrick+Hand&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">

<style>
:root{
--bg:#f5f3ef;--paper:#fff;--ink:#202020;--muted:#707070;
--line:#d3d0c9;--gold:#c9991a;--gold2:#9b6e08;
--green:#168548;--blue:#2867b2
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
margin:0;background:
radial-gradient(circle at 10% 20%,#ddd8ce55 0 2px,transparent 3px),
radial-gradient(circle at 88% 60%,#ddd8ce55 0 2px,transparent 3px),var(--bg);
color:var(--ink);font-family:Inter,Arial,sans-serif
}
a{text-decoration:none;color:inherit}
button,input{font:inherit}
.wrap{width:min(960px,calc(100% - 26px));margin:auto}

.nav{
height:62px;background:#ffffffed;border-bottom:1px solid #dedbd4;
position:sticky;top:0;z-index:20;backdrop-filter:blur(7px)
}
.navin{height:100%;display:flex;align-items:center;justify-content:space-between}
.brand{font-weight:800;font-size:17px;display:flex;align-items:center}
.mark{
width:30px;height:30px;border:2px solid #222;border-radius:50%;
display:grid;place-items:center;margin-right:8px;transform:rotate(-5deg)
}
.brand span{color:var(--gold2)}
.links{display:flex;gap:3px}
.links a{font-size:12px;font-weight:700;padding:7px 10px;border-radius:999px}
.links a:hover{background:#f0eee9}
.online{
font-size:10px;font-weight:800;color:var(--green);
border:1px solid var(--green);border-radius:999px;
padding:6px 9px;background:#1685480b
}

.hero{padding:31px 0 8px;text-align:center}
.paper{
background:#fff;border:2px dashed #d0cdc6;
border-radius:255px 15px 225px 15px/15px 225px 15px 255px;
padding:29px 18px;box-shadow:4px 4px 0 #0000000d
}
h1{font-size:clamp(34px,6vw,52px);line-height:1.05;letter-spacing:-2px;margin:0}
.underline{position:relative}
.underline:after{
content:"";position:absolute;height:5px;left:0;right:0;bottom:-6px;
background:#c9991a33;border-bottom:3px solid var(--gold);border-radius:50%
}
.hand{font:700 23px Caveat,cursive;color:var(--gold2);margin-top:9px}
.hero p{max-width:640px;margin:4px auto;color:#707070;font-size:13px;line-height:1.65}
.stamps{display:flex;justify-content:center;gap:7px;flex-wrap:wrap;margin-top:12px}
.stamp{
font:700 12px "Patrick Hand",cursive;border:1.5px dashed #777;
padding:4px 10px;border-radius:255px 15px 225px 15px/15px 225px 15px 255px;
transform:rotate(-1deg)
}
.stamp:nth-child(2){color:var(--green);border-color:var(--green);transform:rotate(1deg)}
.stamp:nth-child(3){color:var(--blue);border-color:var(--blue);transform:rotate(-1.5deg)}
.actions{display:flex;justify-content:center;gap:7px;flex-wrap:wrap;margin-top:15px}
.btn{
border:1.5px solid #aaa69e;background:#fff;
border-radius:255px 15px 225px 15px/15px 225px 15px 255px;
padding:8px 14px;font-size:11px;font-weight:800;cursor:pointer;
box-shadow:2px 2px 0 #0000000d
}
.btn.primary{background:var(--gold);border-color:#a87808;color:#fff}

.note{
position:relative;margin:16px auto 0;max-width:690px;background:#fff0a3;
border-left:6px solid #e5ad10;padding:10px 15px;text-align:left;
transform:rotate(-.4deg);box-shadow:4px 4px 10px #00000010
}
.note b{font:700 16px Caveat,cursive;color:#75510d}
.note p{font:700 17px Caveat,cursive;margin:0;color:#4c3713;line-height:1.25}

.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:18px}
.metric{background:#fff;border:2px dashed var(--line);border-radius:11px;padding:13px;text-align:center}
.metric b{font-size:19px}.metric small{display:block;color:#888;font-size:9px;margin-top:3px}

section{padding-top:35px}
.section{text-align:center;margin-bottom:17px}
.scribble{font:700 19px Caveat,cursive;color:var(--gold2)}
h2{margin:0;font-size:26px;letter-spacing:-.7px}
.section p{margin:2px auto 0;color:#777;font-size:11px}

.doc{
background:#fff;border:2px dashed var(--line);border-radius:15px;padding:15px;
box-shadow:5px 5px 0 #00000009
}
.tabs{
display:flex;gap:6px;flex-wrap:wrap;border-bottom:2px dashed var(--line);
padding-bottom:10px;margin-bottom:13px
}
.tab{
border:1.5px solid #ccc;background:#fafafa;border-radius:999px;
padding:7px 11px;font-size:10px;font-weight:800;cursor:pointer
}
.tab.active{background:var(--gold);color:#fff;border-color:#a87808}
.dochead{display:flex;justify-content:space-between;gap:12px;text-align:left}
.route{font:700 11px JetBrains Mono;color:var(--green)}
.title{font-size:19px;font-weight:800;margin-top:3px}
.desc{font-size:11px;color:#777;margin-top:3px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.code{
background:#fafafa;border:1px solid #ddd9d2;border-radius:9px;
padding:12px;text-align:left;position:relative
}
.code h4{font-size:8px;color:#888;letter-spacing:1px;margin:0 0 7px}
pre{
white-space:pre-wrap;word-break:break-word;margin:0;
font:10px/1.65 JetBrains Mono;color:#383838
}
.copy{
position:absolute;right:6px;top:6px;border:1px solid #d0ccc4;
background:#fff;border-radius:6px;padding:3px 6px;font-size:8px;cursor:pointer
}
.endpoints{
display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:11px;
padding-top:10px;border-top:1px solid #e5e2dc
}
.ep{
border:1px solid #e1ded7;border-radius:7px;padding:7px;text-align:left;
font:9px JetBrains Mono;background:#fff
}
.ep span{color:var(--green);font-weight:700}

.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.card{
background:#fff;border:2px dashed var(--line);border-radius:11px;
padding:14px;text-align:left
}
.card i{color:var(--gold2)}
.card h3{font-size:12px;margin:8px 0 4px}
.card p{font-size:10px;line-height:1.55;color:#777;margin:0}

.examples{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.example{
background:#fff;border:2px dashed var(--line);border-radius:11px;
padding:14px;text-align:left
}
.example h3{font-size:13px;margin:0 0 4px}
.example p{font-size:10px;color:#777;margin:0 0 9px}
.dark{background:#1d1d1d;color:#eee;border-radius:8px;padding:12px;position:relative}
.dark pre{color:#eee}

.status{display:grid;grid-template-columns:1.3fr .7fr;gap:9px}
.statusbox{
background:#fff;border:2px dashed var(--line);border-radius:12px;
padding:15px;text-align:left
}
.statushead{font-size:12px;font-weight:800}
.green{color:var(--green)}
.sdot{
display:inline-block;width:8px;height:8px;border-radius:50%;
background:var(--green);margin-right:5px
}
.srows{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:11px}
.sitem{border:1px solid #dfdcd6;border-radius:7px;padding:8px}
.sitem small{display:block;color:#888;font-size:8px}
.sitem b{font-size:9px;color:var(--green)}
.uptime{font:700 26px Caveat;color:var(--gold2)}
.tiny{font-size:9px;color:#888}

footer{padding:40px 0 23px}
.foot{
background:#fff;border:2px dashed var(--line);
border-radius:255px 15px 225px 15px/15px 225px 15px 255px;
padding:18px;display:flex;justify-content:space-between;gap:15px;align-items:center
}
.foot b{font-size:16px}.foot b span{color:var(--gold2)}
.foot p{font-size:9px;color:#888;margin:4px 0 0}
.flinks{display:flex;gap:11px;font-size:9px;color:#777;font-weight:700}
.copyr{text-align:center;color:#999;font-size:8px;margin-top:12px}

.modal{
display:none;position:fixed;inset:0;background:#0008;z-index:100;
align-items:center;justify-content:center;padding:15px
}
.modal.open{display:flex}
.modalbox{
width:min(550px,100%);background:#fff;border:2px dashed #aaa;
border-radius:14px;padding:16px;box-shadow:7px 7px 0 #0005
}
.modalhead{display:flex;justify-content:space-between}
.close{border:0;background:none;cursor:pointer}
.form{display:flex;gap:6px;margin-top:12px}
.form input{
flex:1;border:1px solid #ccc;border-radius:9px;padding:9px;
font:10px JetBrains Mono;outline:0
}
.result{
display:none;background:#1d1d1d;color:#eee;border-radius:8px;
padding:11px;margin-top:9px;white-space:pre-wrap;font:9px/1.5 JetBrains Mono
}

@media(max-width:700px){
.links{display:none}
.metrics{grid-template-columns:1fr 1fr}
.grid,.examples,.status{grid-template-columns:1fr}
.cards{grid-template-columns:1fr 1fr}
.endpoints{grid-template-columns:1fr}
}
@media(max-width:480px){
.wrap{width:calc(100% - 16px)}
.hero{padding-top:20px}
.cards{grid-template-columns:1fr}
.srows{grid-template-columns:1fr}
.foot{display:block}
.flinks{margin-top:12px;flex-wrap:wrap}
}
</style>
</head>

<body>

<nav class="nav">
<div class="wrap navin">
<a class="brand" href="/">
<span class="mark"><i class="fa-solid fa-bolt"></i></span>
Magma<span>API</span>
</a>
<div class="links">
<a href="#docs">API Docs</a>
<a href="#examples">Examples</a>
<a href="#features">Features</a>
<a href="#status">Status</a>
</div>
<div class="online">
<i class="fa-solid fa-circle" style="font-size:6px"></i> ONLINE
</div>
</div>
</nav>

<header class="hero">
<div class="wrap">

<div class="paper">
<h1>Your API.<br><span class="underline">Simple to use.</span></h1>
<div class="hand">Built for developers who just want the endpoint.</div>
<p>
Magma API provides straightforward REST endpoints for search,
audio, video and service information.
</p>

<div class="stamps">
<span class="stamp"><i class="fa-solid fa-code"></i> REST API</span>
<span class="stamp"><i class="fa-solid fa-bolt"></i> Fast</span>
<span class="stamp"><i class="fa-solid fa-file-code"></i> JSON</span>
<span class="stamp"><i class="fa-solid fa-shield-halved"></i> Reliable</span>
</div>

<div class="actions">
<a class="btn primary" href="#docs">
<i class="fa-solid fa-book-open"></i> API Docs
</a>
<button class="btn" onclick="openTester()">
<i class="fa-solid fa-flask"></i> Test API
</button>
</div>
</div>

<div class="note">
<b>Quick note</b>
<p>Pick an endpoint below, copy the example and replace the base URL with this API.</p>
</div>

</div>
</header>

<main class="wrap">

<div class="metrics">
<div class="metric"><b>REST</b><small>Interface</small></div>
<div class="metric"><b>JSON</b><small>Responses</small></div>
<div class="metric"><b>24/7</b><small>Service</small></div>
<div class="metric"><b>v1</b><small>API version</small></div>
</div>

<section id="docs">
<div class="section">
<div class="scribble">✎ developer notebook</div>
<h2>API Documentation</h2>
<p>Small, practical documentation — no giant dashboard.</p>
</div>

<div class="doc">
<div class="tabs">
<button class="tab active" data-api="search">Search</button>
<button class="tab" data-api="download">Download</button>
<button class="tab" data-api="video">Video</button>
<button class="tab" data-api="health">Health</button>
</div>

<div class="dochead">
<div>
<div class="route" id="route">GET /search</div>
<div class="title" id="title">Search media</div>
<div class="desc" id="description">Search and return media information.</div>
</div>
<button class="btn" onclick="openTester()">Try it</button>
</div>

<div class="grid">
<div class="code">
<button class="copy" onclick="copyCode('request',this)">Copy</button>
<h4>REQUEST</h4>
<pre id="request">GET /search?q=hello
Accept: application/json</pre>
</div>

<div class="code">
<button class="copy" onclick="copyCode('response',this)">Copy</button>
<h4>RESPONSE</h4>
<pre id="response">{
  "status":"success",
  "results":[]
}</pre>
</div>
</div>

<div class="endpoints">
<div class="ep"><span>GET</span> /search — search media</div>
<div class="ep"><span>GET</span> /download — audio</div>
<div class="ep"><span>GET</span> /video — video</div>
<div class="ep"><span>GET</span> /health — status</div>
</div>
</div>
</section>

<section id="examples">
<div class="section">
<div class="scribble">✎ copy & paste</div>
<h2>Integration Examples</h2>
<p>Use the API from a terminal or your own application.</p>
</div>

<div class="examples">
<div class="example">
<h3><i class="fa-solid fa-terminal"></i> cURL</h3>
<p>Simple terminal request.</p>
<div class="dark">
<button class="copy" onclick="copyCode('curl',this)">Copy</button>
<pre id="curl">curl "YOUR_API_URL/search?q=hello"</pre>
</div>
</div>

<div class="example">
<h3><i class="fa-brands fa-js"></i> JavaScript</h3>
<p>Fetch the JSON response.</p>
<div class="dark">
<button class="copy" onclick="copyCode('js',this)">Copy</button>
<pre id="js">const r = await fetch(
  "YOUR_API_URL/search?q=hello"
);
const data = await r.json();</pre>
</div>
</div>
</div>
</section>

<section id="features">
<div class="section">
<div class="scribble">✎ why Magma API</div>
<h2>Made for actual use</h2>
<p>Useful features without pretending to be a giant SaaS dashboard.</p>
</div>

<div class="cards">
<div class="card"><i class="fa-solid fa-bolt"></i><h3>Fast API</h3><p>Lightweight endpoints and efficient media processing.</p></div>
<div class="card"><i class="fa-solid fa-magnifying-glass"></i><h3>Search</h3><p>Search media and return useful structured information.</p></div>
<div class="card"><i class="fa-solid fa-music"></i><h3>Audio</h3><p>Audio processing with cached completed files.</p></div>
<div class="card"><i class="fa-solid fa-video"></i><h3>Video</h3><p>Video processing with configurable quality.</p></div>
<div class="card"><i class="fa-solid fa-database"></i><h3>Cache</h3><p>Previously completed files can be returned without another download.</p></div>
<div class="card"><i class="fa-solid fa-code"></i><h3>Developer friendly</h3><p>Plain REST endpoints and JSON responses.</p></div>
</div>
</section>

<section id="status">
<div class="section">
<div class="scribble">✎ little green light</div>
<h2>Service Status</h2>
<p>Live status is available from the health endpoint.</p>
</div>

<div class="status">
<div class="statusbox">
<div class="statushead">
<span class="sdot"></span> All systems operational
</div>
<div class="srows">
<div class="sitem"><small>API</small><b>Operational</b></div>
<div class="sitem"><small>Search</small><b>Operational</b></div>
<div class="sitem"><small>Downloads</small><b>Operational</b></div>
</div>
</div>

<div class="statusbox">
<div class="uptime">API v1</div>
<div class="tiny">Health endpoint: /health</div>
</div>
</div>
</section>

</main>

<footer>
<div class="wrap">
<div class="foot">
<div>
<div class="footbrand">Magma<span>API</span></div>
<p>Built to be useful, not noisy.</p>
</div>
<div class="flinks">
<a href="#docs">API Docs</a>
<a href="#examples">Examples</a>
<a href="#status">Status</a>
<a href="/docs">Swagger</a>
</div>
</div>
<div class="copyr">© 2026 Magma API · Developer Portal</div>
</div>
</footer>

<div class="modal" id="modal">
<div class="modalbox">
<div class="modalhead">
<div>
<div class="scribble">Live test</div>
<b>Try an API endpoint</b>
</div>
<button class="close" onclick="closeTester()">
<i class="fa-solid fa-xmark"></i>
</button>
</div>

<div class="form">
<input id="testurl" value="/health">
<button class="btn primary" onclick="runTest()">Run</button>
</div>

<div class="result" id="result"></div>
</div>
</div>

<script>
const api={
search:[
"GET /search",
"Search media",
"Search and return media information.",
"GET /search?q=hello\\nAccept: application/json",
`{
  "status":"success",
  "results":[]
}`
],
download:[
"GET /download",
"Audio download",
"Process a media URL as audio.",
"GET /download?url=MEDIA_URL\\nAccept: application/json",
`{
  "status":"success",
  "type":"audio",
  "file":"track.mp3"
}`
],
video:[
"GET /video",
"Video download",
"Process a media URL as video.",
"GET /video?url=MEDIA_URL\\nAccept: application/json",
`{
  "status":"success",
  "type":"video",
  "file":"video.mp4"
}`
],
health:[
"GET /health",
"Health check",
"Check whether the API is responding.",
"GET /health\\nAccept: application/json",
`{
  "status":"ok",
  "service":"MagmaAPI",
  "version":"1.0"
}`
]
};

document.querySelectorAll(".tab").forEach(x=>{
x.onclick=()=>{
document.querySelectorAll(".tab").forEach(y=>y.classList.remove("active"));
x.classList.add("active");

const d=api[x.dataset.api];

document.getElementById("route").textContent=d[0];
document.getElementById("title").textContent=d[1];
document.getElementById("description").textContent=d[2];
document.getElementById("request").textContent=d[3];
document.getElementById("response").textContent=d[4];
};
});

function copyCode(id,b){
navigator.clipboard.writeText(
document.getElementById(id).innerText
);

const old=b.textContent;
b.textContent="Copied";

setTimeout(()=>{
b.textContent=old;
},900);
}

function openTester(){
document.getElementById("modal").classList.add("open");
}

function closeTester(){
document.getElementById("modal").classList.remove("open");
}

async function runTest(){
const url=document.getElementById("testurl").value.trim();
const out=document.getElementById("result");

out.style.display="block";
out.textContent="Requesting…";

try{
const started=performance.now();

const response=await fetch(
url,
{headers:{Accept:"application/json"}}
);

const elapsed=Math.round(
performance.now()-started
);

const body=await response.text();

out.textContent=
"HTTP "+response.status+
" · "+elapsed+" ms\\n\\n"+body;

}catch(error){
out.textContent=
"Request failed: "+
error.message;
}
}

document.getElementById("modal").onclick=e=>{
if(e.target.id==="modal"){
closeTester();
}
};
</script>

</body>
</html>
"""


# ============================================================
# ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(HTML)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "MagmaAPI",
        "version": "1.0",
        "timestamp": int(time.time()),
    }


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1),
):
    try:
        # Import only when search is actually requested.
        from ytmusicapi import YTMusic

        music = YTMusic()

        results = await asyncio.to_thread(
            music.search,
            q,
            filter="songs",
        )

        output = []

        for item in results[:10]:
            thumbnails = item.get("thumbnails") or []

            output.append({
                "title": item.get("title"),
                "video_id": item.get("videoId"),
                "artists": [
                    artist.get("name")
                    for artist in item.get("artists", [])
                ],
                "album": (
                    item.get("album", {}).get("name")
                    if item.get("album")
                    else None
                ),
                "duration": item.get("duration"),
                "thumbnail": (
                    thumbnails[-1].get("url")
                    if thumbnails
                    else None
                ),
            })

        return {
            "status": "success",
            "query": q,
            "results": output,
        }

    except Exception as exc:
        logger.exception("Search error")

        return JSONResponse(
            {
                "status": "error",
                "error": str(exc),
            },
            status_code=500,
        )


@app.get("/thumbnail")
async def thumbnail(
    url: str = Query(...),
):
    video_id = youtube_video_id(url)

    if not video_id:
        return JSONResponse(
            {
                "status": "error",
                "error": "Invalid YouTube URL",
            },
            status_code=400,
        )

    return {
        "status": "success",
        "video_id": video_id,
        "thumbnail": (
            f"https://i.ytimg.com/vi/"
            f"{video_id}/hqdefault.jpg"
        ),
    }


@app.get("/download")
async def download(
    url: str = Query(...),
):
    started = time.perf_counter()

    try:
        video_id = youtube_video_id(url)

        filepath = await download_audio_fast(url)

        return JSONResponse({
            "status": "success",
            "type": "audio",
            "video_id": video_id,
            "file": os.path.basename(filepath),
            "path": filepath,
            "url": (
                "/files/"
                + Path(filepath).name
            ),
            "time": round(
                time.perf_counter() - started,
                2,
            ),
        })

    except asyncio.CancelledError:
        logger.warning(
            "Audio download request cancelled"
        )
        raise

    except Exception as exc:
        logger.exception(
            "Audio download failed"
        )

        return JSONResponse(
            {
                "status": "error",
                "error": str(exc),
            },
            status_code=500,
        )


@app.get("/video")
async def video(
    url: str = Query(...),
):
    started = time.perf_counter()

    try:
        video_id = youtube_video_id(url)

        filepath = await download_video_fast(url)

        return JSONResponse({
            "status": "success",
            "type": "video",
            "video_id": video_id,
            "file": os.path.basename(filepath),
            "path": filepath,
            "url": (
                "/files/"
                + Path(filepath).name
            ),
            "time": round(
                time.perf_counter() - started,
                2,
            ),
        })

    except asyncio.CancelledError:
        logger.warning(
            "Video download request cancelled"
        )
        raise

    except Exception as exc:
        logger.exception(
            "Video download failed"
        )

        return JSONResponse(
            {
                "status": "error",
                "error": str(exc),
            },
            status_code=500,
        )


@app.get("/files/{filename}")
async def files(filename: str):
    # Prevent path traversal.
    safe_name = Path(filename).name
    path = DOWNLOAD_DIR / safe_name

    if not path.is_file():
        return JSONResponse(
            {
                "status": "error",
                "error": "File not found",
            },
            status_code=404,
        )

    return FileResponse(
        path=str(path),
        filename=path.name,
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        workers=1,
    )
