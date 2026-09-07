import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response


# ============================================================
# CONFIG
# ============================================================

DEFAULT_BACKEND = "https://stamina-porcupine-untimely.ngrok-free.dev"

BACKEND_FILE = Path(__file__).with_name("backend-url.json")


def get_backend_url() -> str:
    """
    Backend URL priority:

    1. BACKEND_URL environment variable
    2. backend-url.json
    3. DEFAULT_BACKEND
    """

    env_url = os.getenv(
        "BACKEND_URL",
        "",
    ).strip()

    if env_url:
        return env_url.rstrip("/")

    try:
        data = json.loads(
            BACKEND_FILE.read_text(
                encoding="utf-8"
            )
        )

        url = str(
            data.get("url", "")
        ).strip()

        if url:
            return url.rstrip("/")

    except Exception:
        pass

    return DEFAULT_BACKEND


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Magma API",
    version="1.0",
    description="Magma API Website and Proxy",
)


# ============================================================
# WEBSITE HTML
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Magma API — Developer Portal</title>

<link
    rel="preconnect"
    href="https://fonts.googleapis.com"
>

<link
    rel="preconnect"
    href="https://fonts.gstatic.com"
>

<link
    rel="preconnect"
    href="https://fonts.gstatic.com"
    crossorigin
>

<link
    href="https://fonts.googleapis.com/css2?family=Caveat:wght@600;700&family=Inter:wght@400;500;600;700;800&family=Patrick+Hand&family=JetBrains+Mono:wght@400;500;700&display=swap"
    rel="stylesheet"
>

<link
    rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
>

<style>

:root{
    --bg:#f5f3ef;
    --paper:#ffffff;
    --ink:#202020;
    --muted:#707070;
    --line:#d3d0c9;
    --gold:#c9991a;
    --gold2:#9b6e08;
    --green:#168548;
    --blue:#2867b2;
}

*{
    box-sizing:border-box;
}

html{
    scroll-behavior:smooth;
}

body{
    margin:0;
    background:
        radial-gradient(
            circle at 10% 20%,
            #ddd8ce55 0 2px,
            transparent 3px
        ),
        radial-gradient(
            circle at 88% 60%,
            #ddd8ce55 0 2px,
            transparent 3px
        ),
        var(--bg);
    color:var(--ink);
    font-family:Inter,Arial,sans-serif;
}

a{
    text-decoration:none;
    color:inherit;
}

button,
input{
    font:inherit;
}

.wrap{
    width:min(
        960px,
        calc(100% - 26px)
    );
    margin:auto;
}


/* ============================================================
   NAV
   ============================================================ */

.nav{
    height:62px;
    background:#ffffffed;
    border-bottom:1px solid #dedbd4;
    position:sticky;
    top:0;
    z-index:20;
    backdrop-filter:blur(7px);
}

.navin{
    height:100%;
    display:flex;
    align-items:center;
    justify-content:space-between;
}

.brand{
    font-weight:800;
    font-size:17px;
    display:flex;
    align-items:center;
}

.brand span{
    color:var(--gold2);
}

.mark{
    width:30px;
    height:30px;
    border:2px solid #222;
    border-radius:50%;
    display:grid;
    place-items:center;
    margin-right:8px;
    transform:rotate(-5deg);
}

.links{
    display:flex;
    gap:3px;
}

.links a{
    font-size:12px;
    font-weight:700;
    padding:7px 10px;
    border-radius:999px;
}

.links a:hover{
    background:#f0eee9;
}

.online{
    font-size:10px;
    font-weight:800;
    color:var(--green);
    border:1px solid var(--green);
    border-radius:999px;
    padding:6px 9px;
    background:#1685480b;
}


/* ============================================================
   HERO
   ============================================================ */

.hero{
    padding:31px 0 8px;
    text-align:center;
}

.paper{
    background:#fff;
    border:2px dashed #d0cdc6;
    border-radius:
        255px 15px 225px 15px /
        15px 225px 15px 255px;
    padding:29px 18px;
    box-shadow:4px 4px 0 #0000000d;
}

h1{
    font-size:clamp(34px,6vw,52px);
    line-height:1.05;
    letter-spacing:-2px;
    margin:0;
}

.underline{
    position:relative;
}

.underline:after{
    content:"";
    position:absolute;
    height:5px;
    left:0;
    right:0;
    bottom:-6px;
    background:#c9991a33;
    border-bottom:3px solid var(--gold);
    border-radius:50%;
}

.hand{
    font:700 23px Caveat,cursive;
    color:var(--gold2);
    margin-top:9px;
}

.hero p{
    max-width:640px;
    margin:4px auto;
    color:#707070;
    font-size:13px;
    line-height:1.65;
}

.stamps{
    display:flex;
    justify-content:center;
    gap:7px;
    flex-wrap:wrap;
    margin-top:12px;
}

.stamp{
    font:700 12px "Patrick Hand",cursive;
    border:1.5px dashed #777;
    padding:4px 10px;
    border-radius:
        255px 15px 225px 15px /
        15px 225px 15px 255px;
    transform:rotate(-1deg);
}

.stamp:nth-child(2){
    color:var(--green);
    border-color:var(--green);
    transform:rotate(1deg);
}

.stamp:nth-child(3){
    color:var(--blue);
    border-color:var(--blue);
    transform:rotate(-1.5deg);
}

.actions{
    display:flex;
    justify-content:center;
    gap:7px;
    flex-wrap:wrap;
    margin-top:15px;
}

.btn{
    border:1.5px solid #aaa69e;
    background:#fff;
    border-radius:
        255px 15px 225px 15px /
        15px 225px 15px 255px;
    padding:8px 14px;
    font-size:11px;
    font-weight:800;
    cursor:pointer;
    box-shadow:2px 2px 0 #0000000d;
}

.btn.primary{
    background:var(--gold);
    border-color:#a87808;
    color:#fff;
}

.note{
    position:relative;
    margin:16px auto 0;
    max-width:690px;
    background:#fff0a3;
    border-left:6px solid #e5ad10;
    padding:10px 15px;
    text-align:left;
    transform:rotate(-.4deg);
    box-shadow:4px 4px 10px #00000010;
}

.note b{
    font:700 16px Caveat,cursive;
    color:#75510d;
}

.note p{
    font:700 17px Caveat,cursive;
    margin:0;
    color:#4c3713;
    line-height:1.25;
}


/* ============================================================
   METRICS
   ============================================================ */

.metrics{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:9px;
    margin-top:18px;
}

.metric{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:11px;
    padding:13px;
    text-align:center;
}

.metric b{
    font-size:19px;
}

.metric small{
    display:block;
    color:#888;
    font-size:9px;
    margin-top:3px;
}


/* ============================================================
   SECTIONS
   ============================================================ */

section{
    padding-top:35px;
}

.section{
    text-align:center;
    margin-bottom:17px;
}

.scribble{
    font:700 19px Caveat,cursive;
    color:var(--gold2);
}

h2{
    margin:0;
    font-size:26px;
    letter-spacing:-.7px;
}

.section p{
    margin:2px auto 0;
    color:#777;
    font-size:11px;
}


/* ============================================================
   DOCUMENTATION
   ============================================================ */

.doc{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:15px;
    padding:15px;
    box-shadow:5px 5px 0 #00000009;
}

.tabs{
    display:flex;
    gap:6px;
    flex-wrap:wrap;
    border-bottom:2px dashed var(--line);
    padding-bottom:10px;
    margin-bottom:13px;
}

.tab{
    border:1.5px solid #ccc;
    background:#fafafa;
    border-radius:999px;
    padding:7px 11px;
    font-size:10px;
    font-weight:800;
    cursor:pointer;
}

.tab.active{
    background:var(--gold);
    color:#fff;
    border-color:#a87808;
}

.dochead{
    display:flex;
    justify-content:space-between;
    gap:12px;
    text-align:left;
}

.route{
    font:700 11px JetBrains Mono;
    color:var(--green);
}

.title{
    font-size:19px;
    font-weight:800;
    margin-top:3px;
}

.desc{
    font-size:11px;
    color:#777;
    margin-top:3px;
}

.grid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:10px;
    margin-top:14px;
}

.code{
    background:#fafafa;
    border:1px solid #ddd9d2;
    border-radius:9px;
    padding:12px;
    text-align:left;
    position:relative;
}

.code h4{
    font-size:8px;
    color:#888;
    letter-spacing:1px;
    margin:0 0 7px;
}

pre{
    white-space:pre-wrap;
    word-break:break-word;
    margin:0;
    font:10px/1.65 JetBrains Mono;
    color:#383838;
}

.copy{
    position:absolute;
    right:6px;
    top:6px;
    border:1px solid #d0ccc4;
    background:#fff;
    border-radius:6px;
    padding:3px 6px;
    font-size:8px;
    cursor:pointer;
}

.endpoints{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:5px;
    margin-top:11px;
    padding-top:10px;
    border-top:1px solid #e5e2dc;
}

.ep{
    border:1px solid #e1ded7;
    border-radius:7px;
    padding:7px;
    text-align:left;
    font:9px JetBrains Mono;
    background:#fff;
}

.ep span{
    color:var(--green);
    font-weight:700;
}


/* ============================================================
   EXAMPLES
   ============================================================ */

.examples{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:9px;
}

.example{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:11px;
    padding:14px;
    text-align:left;
}

.example h3{
    font-size:13px;
    margin:0 0 4px;
}

.example p{
    font-size:10px;
    color:#777;
    margin:0 0 9px;
}

.dark{
    background:#1d1d1d;
    color:#eee;
    border-radius:8px;
    padding:12px;
    position:relative;
}

.dark pre{
    color:#eee;
}


/* ============================================================
   FEATURES
   ============================================================ */

.cards{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:9px;
}

.card{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:11px;
    padding:14px;
    text-align:left;
}

.card i{
    color:var(--gold2);
}

.card h3{
    font-size:12px;
    margin:8px 0 4px;
}

.card p{
    font-size:10px;
    line-height:1.55;
    color:#777;
    margin:0;
}


/* ============================================================
   STATUS
   ============================================================ */

.status{
    display:grid;
    grid-template-columns:1.3fr .7fr;
    gap:9px;
}

.statusbox{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:12px;
    padding:15px;
    text-align:left;
}

.statushead{
    font-size:12px;
    font-weight:800;
}

.sdot{
    display:inline-block;
    width:8px;
    height:8px;
    border-radius:50%;
    background:var(--green);
    margin-right:5px;
}

.srows{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:6px;
    margin-top:11px;
}

.sitem{
    border:1px solid #dfdcd6;
    border-radius:7px;
    padding:8px;
}

.sitem small{
    display:block;
    color:#888;
    font-size:8px;
}

.sitem b{
    font-size:9px;
    color:var(--green);
}

.uptime{
    font:700 26px Caveat;
    color:var(--gold2);
}

.tiny{
    font-size:9px;
    color:#888;
}


/* ============================================================
   FOOTER
   ============================================================ */

footer{
    padding:40px 0 23px;
}

.foot{
    background:#fff;
    border:2px dashed var(--line);
    border-radius:
        255px 15px 225px 15px /
        15px 225px 15px 255px;
    padding:18px;
    display:flex;
    justify-content:space-between;
    gap:15px;
    align-items:center;
}

.footbrand{
    font-weight:800;
    font-size:16px;
}

.footbrand span{
    color:var(--gold2);
}

.foot p{
    font-size:9px;
    color:#888;
    margin:4px 0 0;
}

.flinks{
    display:flex;
    gap:11px;
    font-size:9px;
    color:#777;
    font-weight:700;
}

.copyr{
    text-align:center;
    color:#999;
    font-size:8px;
    margin-top:12px;
}


/* ============================================================
   MODAL
   ============================================================ */

.modal{
    display:none;
    position:fixed;
    inset:0;
    background:#0008;
    z-index:100;
    align-items:center;
    justify-content:center;
    padding:15px;
}

.modal.open{
    display:flex;
}

.modalbox{
    width:min(550px,100%);
    background:#fff;
    border:2px dashed #aaa;
    border-radius:14px;
    padding:16px;
    box-shadow:7px 7px 0 #0005;
}

.modalhead{
    display:flex;
    justify-content:space-between;
}

.close{
    border:0;
    background:none;
    cursor:pointer;
}

.form{
    display:flex;
    gap:6px;
    margin-top:12px;
}

.form input{
    flex:1;
    border:1px solid #ccc;
    border-radius:9px;
    padding:9px;
    font:10px JetBrains Mono;
    outline:0;
}

.result{
    display:none;
    background:#1d1d1d;
    color:#eee;
    border-radius:8px;
    padding:11px;
    margin-top:9px;
    white-space:pre-wrap;
    font:9px/1.5 JetBrains Mono;
}


/* ============================================================
   MOBILE
   ============================================================ */

@media(max-width:700px){

    .links{
        display:none;
    }

    .metrics{
        grid-template-columns:1fr 1fr;
    }

    .grid,
    .examples,
    .status{
        grid-template-columns:1fr;
    }

    .cards{
        grid-template-columns:1fr 1fr;
    }

    .endpoints{
        grid-template-columns:1fr;
    }
}

@media(max-width:480px){

    .wrap{
        width:calc(100% - 16px);
    }

    .hero{
        padding-top:20px;
    }

    .cards{
        grid-template-columns:1fr;
    }

    .srows{
        grid-template-columns:1fr;
    }

    .foot{
        display:block;
    }

    .flinks{
        margin-top:12px;
        flex-wrap:wrap;
    }
}

</style>

</head>


<body>


<!-- ============================================================
     NAVBAR
     ============================================================ -->

<nav class="nav">

<div class="wrap navin">

<a
    class="brand"
    href="/"
>

<span class="mark">
<i class="fa-solid fa-bolt"></i>
</span>

Magma<span>API</span>

</a>


<div class="links">

<a href="#docs">
API Docs
</a>

<a href="#examples">
Examples
</a>

<a href="#features">
Features
</a>

<a href="#status">
Status
</a>

</div>


<div class="online">

<i
    class="fa-solid fa-circle"
    style="font-size:6px"
></i>

ONLINE

</div>

</div>

</nav>


<!-- ============================================================
     HERO
     ============================================================ -->

<header class="hero">

<div class="wrap">

<div class="paper">

<h1>

Your API.<br>

<span class="underline">
Simple to use.
</span>

</h1>


<div class="hand">

Built for developers who just want the endpoint.

</div>


<p>

Magma API provides straightforward REST endpoints for
search, audio, video and service information.

</p>


<div class="stamps">

<span class="stamp">
<i class="fa-solid fa-code"></i>
REST API
</span>

<span class="stamp">
<i class="fa-solid fa-bolt"></i>
Fast
</span>

<span class="stamp">
<i class="fa-solid fa-file-code"></i>
JSON
</span>

<span class="stamp">
<i class="fa-solid fa-shield-halved"></i>
Reliable
</span>

</div>


<div class="actions">

<a
    class="btn primary"
    href="#docs"
>

<i class="fa-solid fa-book-open"></i>
API Docs

</a>


<button
    class="btn"
    onclick="openTester()"
>

<i class="fa-solid fa-flask"></i>
Test API

</button>

</div>

</div>


<div class="note">

<b>
Quick note
</b>

<p>

Pick an endpoint below, copy the example and replace
the base URL with this API.

</p>

</div>

</div>

</header>


<!-- ============================================================
     MAIN
     ============================================================ -->

<main class="wrap">


<!-- ============================================================
     METRICS
     ============================================================ -->

<div class="metrics">

<div class="metric">
<b>REST</b>
<small>Interface</small>
</div>

<div class="metric">
<b>JSON</b>
<small>Responses</small>
</div>

<div class="metric">
<b>24/7</b>
<small>Service</small>
</div>

<div class="metric">
<b>v1</b>
<small>API version</small>
</div>

</div>


<!-- ============================================================
     DOCUMENTATION
     ============================================================ -->

<section id="docs">

<div class="section">

<div class="scribble">
✎ developer notebook
</div>

<h2>
API Documentation
</h2>

<p>
Small, practical documentation — no giant dashboard.
</p>

</div>


<div class="doc">

<div class="tabs">

<button
    class="tab active"
    data-api="search"
>
Search
</button>

<button
    class="tab"
    data-api="download"
>
Download
</button>

<button
    class="tab"
    data-api="video"
>
Video
</button>

<button
    class="tab"
    data-api="health"
>
Health
</button>

</div>


<div class="dochead">

<div>

<div
    class="route"
    id="route"
>
GET /search
</div>

<div
    class="title"
    id="title"
>
Search media
</div>

<div
    class="desc"
    id="description"
>
Search and return media information.
</div>

</div>


<button
    class="btn"
    onclick="openTester()"
>
Try it
</button>

</div>


<div class="grid">

<div class="code">

<button
    class="copy"
    onclick="copyCode('request',this)"
>
Copy
</button>

<h4>
REQUEST
</h4>

<pre id="request">GET /search?q=hello
Accept: application/json</pre>

</div>


<div class="code">

<button
    class="copy"
    onclick="copyCode('response',this)"
>
Copy
</button>

<h4>
RESPONSE
</h4>

<pre id="response">{
  "status":"success",
  "results":[]
}</pre>

</div>

</div>


<div class="endpoints">

<div class="ep">
<span>GET</span>
 /search — search media
</div>

<div class="ep">
<span>GET</span>
 /download — audio
</div>

<div class="ep">
<span>GET</span>
 /video — video
</div>

<div class="ep">
<span>GET</span>
 /health — status
</div>

</div>

</div>

</section>


<!-- ============================================================
     EXAMPLES
     ============================================================ -->

<section id="examples">

<div class="section">

<div class="scribble">
✎ copy & paste
</div>

<h2>
Integration Examples
</h2>

<p>
Use the API from a terminal or your own application.
</p>

</div>


<div class="examples">

<div class="example">

<h3>
<i class="fa-solid fa-terminal"></i>
cURL
</h3>

<p>
Simple terminal request.
</p>

<div class="dark">

<button
    class="copy"
    onclick="copyCode('curl',this)"
>
Copy
</button>

<pre id="curl">curl "YOUR_VERCEL_URL/search?q=hello"</pre>

</div>

</div>


<div class="example">

<h3>
<i class="fa-brands fa-js"></i>
JavaScript
</h3>

<p>
Fetch the JSON response.
</p>

<div class="dark">

<button
    class="copy"
    onclick="copyCode('js',this)"
>
Copy
</button>

<pre id="js">const r = await fetch(
  "/search?q=hello"
);

const data = await r.json();</pre>

</div>

</div>

</div>

</section>


<!-- ============================================================
     FEATURES
     ============================================================ -->

<section id="features">

<div class="section">

<div class="scribble">
✎ why Magma API
</div>

<h2>
Made for actual use
</h2>

<p>
Useful features without pretending to be a giant SaaS dashboard.
</p>

</div>


<div class="cards">

<div class="card">

<i class="fa-solid fa-bolt"></i>

<h3>
Fast API
</h3>

<p>
Vercel handles the public API layer while the media
backend stays on the server.
</p>

</div>


<div class="card">

<i class="fa-solid fa-magnifying-glass"></i>

<h3>
Search
</h3>

<p>
Search requests are forwarded to the real backend.
</p>

</div>


<div class="card">

<i class="fa-solid fa-music"></i>

<h3>
Audio
</h3>

<p>
Audio requests are forwarded to the downloader backend.
</p>

</div>


<div class="card">

<i class="fa-solid fa-video"></i>

<h3>
Video
</h3>

<p>
Video requests are forwarded to the downloader backend.
</p>

</div>


<div class="card">

<i class="fa-solid fa-link"></i>

<h3>
Single URL
</h3>

<p>
Users only need the Vercel domain instead of knowing
the backend URL.
</p>

</div>


<div class="card">

<i class="fa-solid fa-code"></i>

<h3>
Developer friendly
</h3>

<p>
Plain REST endpoints and JSON responses.
</p>

</div>

</div>

</section>


<!-- ============================================================
     STATUS
     ============================================================ -->

<section id="status">

<div class="section">

<div class="scribble">
✎ little green light
</div>

<h2>
Service Status
</h2>

<p>
Live status is checked through the backend.
</p>

</div>


<div class="status">

<div class="statusbox">

<div class="statushead">

<span class="sdot"></span>

<span id="statusText">
Checking backend…
</span>

</div>


<div class="srows">

<div class="sitem">

<small>
API
</small>

<b id="apiStatus">
Checking
</b>

</div>


<div class="sitem">

<small>
Search
</small>

<b>
Ready
</b>

</div>


<div class="sitem">

<small>
Downloads
</small>

<b>
Ready
</b>

</div>

</div>

</div>


<div class="statusbox">

<div class="uptime">
API v1
</div>

<div class="tiny">
Public base: this Vercel URL
</div>

</div>

</div>

</section>

</main>


<!-- ============================================================
     FOOTER
     ============================================================ -->

<footer>

<div class="wrap">

<div class="foot">

<div>

<div class="footbrand">
Magma<span>API</span>
</div>

<p>
Built to be useful, not noisy.
</p>

</div>


<div class="flinks">

<a href="#docs">
API Docs
</a>

<a href="#examples">
Examples
</a>

<a href="#status">
Status
</a>

<a href="/docs">
Swagger
</a>

</div>

</div>


<div class="copyr">
© 2026 Magma API · Developer Portal
</div>

</div>

</footer>


<!-- ============================================================
     TEST MODAL
     ============================================================ -->

<div
    class="modal"
    id="modal"
>

<div class="modalbox">

<div class="modalhead">

<div>

<div class="scribble">
Live test
</div>

<b>
Try an API endpoint
</b>

</div>


<button
    class="close"
    onclick="closeTester()"
>

<i class="fa-solid fa-xmark"></i>

</button>

</div>


<div class="form">

<input
    id="testurl"
    value="/health"
>

<button
    class="btn primary"
    onclick="runTest()"
>
Run
</button>

</div>


<div
    class="result"
    id="result"
></div>

</div>

</div>


<!-- ============================================================
     JAVASCRIPT
     ============================================================ -->

<script>

const api = {

    search: [

        "GET /search",

        "Search media",

        "Search and return media information.",

        `GET /search?q=hello
Accept: application/json`,

        `{
  "status":"success",
  "results":[]
}`

    ],

    download: [

        "GET /download",

        "Audio download",

        "Process a media URL as audio.",

        `GET /download?url=MEDIA_URL
Accept: application/json`,

        `{
  "status":"success",
  "type":"audio",
  "file":"track.mp3"
}`

    ],

    video: [

        "GET /video",

        "Video download",

        "Process a media URL as video.",

        `GET /video?url=MEDIA_URL
Accept: application/json`,

        `{
  "status":"success",
  "type":"video",
  "file":"video.mp4"
}`

    ],

    health: [

        "GET /health",

        "Health check",

        "Check whether the API is responding.",

        `GET /health
Accept: application/json`,

        `{
  "status":"ok",
  "service":"MagmaAPI",
  "version":"1.0"
}`

    ]

};


document
.querySelectorAll(".tab")
.forEach(button => {

    button.onclick = () => {

        document
        .querySelectorAll(".tab")
        .forEach(item => {

            item.classList.remove(
                "active"
            );

        });

        button.classList.add(
            "active"
        );

        const data =
            api[
                button.dataset.api
            ];

        document
        .getElementById("route")
        .textContent =
            data[0];

        document
        .getElementById("title")
        .textContent =
            data[1];

        document
        .getElementById("description")
        .textContent =
            data[2];

        document
        .getElementById("request")
        .textContent =
            data[3];

        document
        .getElementById("response")
        .textContent =
            data[4];

    };

});


function copyCode(
    id,
    button
){

    const element =
        document.getElementById(
            id
        );

    if(!element){
        return;
    }

    const text =
        element.innerText;

    if(navigator.clipboard){

        navigator
        .clipboard
        .writeText(text);

    }

    const old =
        button.textContent;

    button.textContent =
        "Copied";

    setTimeout(() => {

        button.textContent =
            old;

    },900);

}


function openTester(){

    document
    .getElementById("modal")
    .classList.add("open");

}


function closeTester(){

    document
    .getElementById("modal")
    .classList.remove("open");

}


async function runTest(){

    const url =
        document
        .getElementById(
            "testurl"
        )
        .value
        .trim();

    const output =
        document
        .getElementById(
            "result"
        );

    output.style.display =
        "block";

    output.textContent =
        "Requesting…";

    try{

        const started =
            performance.now();

        const response =
            await fetch(
                url,
                {
                    headers:{
                        Accept:
                            "application/json"
                    }
                }
            );

        const elapsed =
            Math.round(
                performance.now()
                -
                started
            );

        const body =
            await response.text();

        output.textContent =
            "HTTP "
            +
            response.status
            +
            " · "
            +
            elapsed
            +
            " ms\n\n"
            +
            body;

    }catch(error){

        output.textContent =
            "Request failed: "
            +
            error.message;

    }

}


document
.getElementById("modal")
.onclick = event => {

    if(
        event.target.id ===
        "modal"
    ){

        closeTester();

    }

};


async function checkStatus(){

    try{

        const response =
            await fetch(
                "/health",
                {
                    cache:"no-store"
                }
            );

        if(response.ok){

            document
            .getElementById(
                "statusText"
            )
            .textContent =
                "All systems operational";

            document
            .getElementById(
                "apiStatus"
            )
            .textContent =
                "Operational";

        }else{

            throw new Error(
                "Backend error"
            );

        }

    }catch(error){

        document
        .getElementById(
            "statusText"
        )
        .textContent =
            "Backend unavailable";

        document
        .getElementById(
            "apiStatus"
        )
        .textContent =
            "Offline";

    }

}


checkStatus();

</script>

</body>

</html>
"""


# ============================================================
# HOME / WEBSITE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def home():

    return HTMLResponse(
        content=HTML
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    backend = get_backend_url()

    try:

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
        ) as client:

            response = await client.get(
                f"{backend}/health"
            )

        try:

            backend_data = response.json()

        except Exception:

            backend_data = {
                "backend_response":
                    response.text[:500]
            }

        return JSONResponse(

            {
                "status":
                    (
                        "ok"
                        if response.is_success
                        else "degraded"
                    ),

                "service":
                    "MagmaAPI Proxy",

                "backend":
                    backend,

                "backend_status":
                    response.status_code,

                "backend_response":
                    backend_data,
            },

            status_code=(
                200
                if response.is_success
                else 502
            ),
        )

    except Exception as error:

        return JSONResponse(

            {
                "status":
                    "error",

                "service":
                    "MagmaAPI Proxy",

                "backend":
                    backend,

                "error":
                    str(error),
            },

            status_code=502,
        )


# ============================================================
# GENERIC GET PROXY
# ============================================================

async def proxy_get(
    path: str,
    request: Request,
    timeout: float = 60.0,
):

    backend = get_backend_url()

    target = (
        f"{backend}/"
        f"{path.lstrip('/')}"
    )

    params = list(
        request
        .query_params
        .multi_items()
    )

    try:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout,
                connect=30.0,
            ),
            follow_redirects=True,
        ) as client:

            response = await client.get(
                target,
                params=params,
            )

        content_type = response.headers.get(
            "content-type",
            "application/octet-stream",
        )

        headers = {}

        for name in (
            "content-disposition",
            "cache-control",
            "etag",
            "last-modified",
            "accept-ranges",
        ):

            if name in response.headers:

                headers[name] = (
                    response.headers[name]
                )

        media_type = (
            content_type.split(";")[0]
        )

        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=media_type,
            headers=headers,
        )

    except httpx.TimeoutException:

        return JSONResponse(

            {
                "status":
                    "error",

                "error":
                    "Backend request timed out",

                "backend":
                    backend,
            },

            status_code=504,
        )

    except Exception as error:

        return JSONResponse(

            {
                "status":
                    "error",

                "error":
                    str(error),

                "backend":
                    backend,
            },

            status_code=502,
        )


# ============================================================
# SEARCH
# ============================================================

@app.get("/search")
async def search(
    request: Request,
    q: str = Query(
        ...,
        min_length=1,
    ),
):

    return await proxy_get(
        "/search",
        request,
        timeout=30,
    )


# ============================================================
# THUMBNAIL
# ============================================================

@app.get("/thumbnail")
async def thumbnail(
    request: Request,
):

    return await proxy_get(
        "/thumbnail",
        request,
        timeout=30,
    )


# ============================================================
# AUDIO DOWNLOAD
# ============================================================

@app.get("/download")
async def download(
    request: Request,
):

    return await proxy_get(
        "/download",
        request,
        timeout=300,
    )


# ============================================================
# VIDEO
# ============================================================

@app.get("/video")
async def video(
    request: Request,
):

    return await proxy_get(
        "/video",
        request,
        timeout=300,
    )


# ============================================================
# FILES
# ============================================================

@app.get(
    "/files/{filename:path}"
)
async def files(
    request: Request,
    filename: str,
):

    safe_filename = Path(
        filename
    ).name

    return await proxy_get(
        f"/files/{safe_filename}",
        request,
        timeout=120,
    )


# ============================================================
# CATCH-ALL PROXY
# ============================================================
#
# Upar defined routes ke alawa jo bhi endpoint aayega,
# woh automatically backend ko forward hoga.
#
# /abc
#   ↓
# backend /abc
#
# /api/test
#   ↓
# backend /api/test
#
# /anything?q=hello
#   ↓
# backend /anything?q=hello
#
# ============================================================

@app.api_route(
    "/{path:path}",
    methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
)
async def catch_all_proxy(
    path: str,
    request: Request,
):

    backend = get_backend_url()


    # ========================================================
    # TARGET URL
    # ========================================================

    if path:

        target_url = (
            f"{backend}/{path}"
        )

    else:

        target_url = backend


    # ========================================================
    # QUERY PARAMETERS
    # ========================================================

    params = list(
        request
        .query_params
        .multi_items()
    )


    # ========================================================
    # REQUEST BODY
    # ========================================================

    body = await request.body()


    # ========================================================
    # REQUEST HEADERS
    # ========================================================

    headers = dict(
        request.headers
    )

    headers.pop(
        "host",
        None
    )

    headers.pop(
        "content-length",
        None
    )


    # ========================================================
    # FORWARD TO BACKEND
    # ========================================================

    try:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                300.0,
                connect=30.0,
            ),
            follow_redirects=True,
        ) as client:

            backend_response = (
                await client.request(

                    method=request.method,

                    url=target_url,

                    params=params,

                    content=body,

                    headers=headers,

                )
            )


        # ====================================================
        # RESPONSE HEADERS
        # ====================================================

        response_headers = {}

        for header in [

            "content-type",

            "content-disposition",

            "cache-control",

            "etag",

            "last-modified",

            "accept-ranges",

        ]:

            if header in backend_response.headers:

                response_headers[header] = (
                    backend_response
                    .headers[header]
                )


        # ====================================================
        # RETURN BACKEND RESPONSE
        # ====================================================

        return Response(

            content=(
                backend_response
                .content
            ),

            status_code=(
                backend_response
                .status_code
            ),

            headers=response_headers,

        )


    # ========================================================
    # TIMEOUT
    # ========================================================

    except httpx.TimeoutException:

        return JSONResponse(

            {
                "status":
                    "error",

                "error":
                    "Backend request timed out",

                "backend":
                    backend,
            },

            status_code=504,
        )


    # ========================================================
    # HTTPX ERROR
    # ========================================================

    except httpx.HTTPError as error:

        return JSONResponse(

            {
                "status":
                    "error",

                "error":
                    str(error),

                "backend":
                    backend,
            },

            status_code=502,
        )


    # ========================================================
    # OTHER ERROR
    # ========================================================

    except Exception as error:

        return JSONResponse(

            {
                "status":
                    "error",

                "error":
                    str(error),

                "backend":
                    backend,
            },

            status_code=502,
        )


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        app,

        host="0.0.0.0",

        port=int(
            os.getenv(
                "PORT",
                "8000",
            )
        ),

    )