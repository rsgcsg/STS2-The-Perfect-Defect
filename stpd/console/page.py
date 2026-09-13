"""A small shared shell with packaged assets and no external browser dependencies."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = {"console.css": "text/css", "console.js": "text/javascript"}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def asset(name: str) -> tuple[str, bytes] | None:
    if name not in ASSETS:
        return None
    return ASSETS[name], Path(__file__).with_name(name).read_bytes()


def render_shell(mode: str, api_base: str, cloud_url: str = "") -> str:
    if (mode, api_base) not in {("local", "/api/console"), ("cloud", "/app/api")}:
        raise ValueError("unsupported_console_mode")
    if cloud_url:
        parsed = urlsplit(cloud_url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not parsed.hostname
            or not (
                parsed.scheme == "https"
                or (
                    parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                )
            )
        ):
            raise ValueError("invalid_console_cloud_url")
    assets = "/assets" if mode == "local" else "/app/assets"
    cloud = html.escape(cloud_url.rstrip("/"), quote=True)
    label = "本机工作台" if mode == "local" else "云端数据中心"
    nav = "".join(
        f'<a class="nav-item" href="?view={key}" data-view="{key}">'
        f'<span class="nav-icon" aria-hidden="true">{icon}</span>{name}</a>'
        for key, name, icon in (
            ("overview", "概览", "◫"),
            ("collections", "采集记录", "▤"),
            ("datasets", "数据集", "▦"),
            ("jobs", "作业", "◷"),
            ("models", "模型与评估", "◇"),
            ("system", "系统", "⚙"),
        )
    )
    cloud_link = (
        f'<a class="button secondary" href="{cloud}/app/" target="_blank" '
        'rel="noreferrer">打开云端 ↗</a>'
        if mode == "local" and cloud
        else ""
    )
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpireAgent · {label}</title><link rel="stylesheet" href="{assets}/console.css">
<script src="{assets}/console.js" defer></script></head>
<body data-mode="{mode}" data-api="{api_base}" data-cloud-url="{cloud}">
<a class="skip-link" href="#main">跳到内容</a>
<aside class="sidebar"><a class="brand" href="?view=overview"><span class="brand-mark">S</span>
<span>SpireAgent<small>项目控制台</small></span></a>
<div class="workspace-label">{label}</div><nav aria-label="主导航">{nav}</nav>
<div class="sidebar-note"><span class="status-dot"></span> B PIPELINE
<p>采集有据可查<br>数据各有去向</p></div></aside>
<div class="workspace"><header class="topbar"><div><span class="mode-pill">{label}</span>
<span id="connection" class="connection">正在读取状态…</span></div>
<div class="topbar-actions">{cloud_link}<button id="refresh" class="button secondary"
type="button">刷新</button></div></header>
<main id="main" tabindex="-1"><div class="page-heading"><div><p class="eyebrow">SPIREAGENT / B</p>
<h1 id="title">概览</h1><p id="subtitle" class="subtitle">采集、上传与研究进展，一处查看。</p></div>
<span id="updated" class="updated"></span></div>
<div id="notice" role="status" aria-live="polite"></div>
<div id="content" aria-busy="true"><div class="empty-state">正在读取已确认的数据…</div></div>
</main><footer>录制质量 · 云端验收 · 研究准入，分别展示。
<span id="lifecycle-note"></span></footer></div>
<noscript>此控制台需要启用 JavaScript。CLI 的 project status 仍可独立使用。</noscript>
</body></html>'''
