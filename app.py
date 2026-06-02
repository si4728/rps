from __future__ import annotations

import datetime as dt
import html
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, session


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "rps.db"

CHOICES = {"rock", "paper", "scissors"}
CHOICE_TIMEOUT_SECONDS = 10

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "app" / "templates"),
    static_folder=str(BASE_DIR / "app" / "static"),
)
app.config["SECRET_KEY"] = os.environ.get("RPS_SECRET_KEY", "CHANGE_ME_TO_A_LONG_RANDOM_SECRET")

state_lock = threading.RLock()
waiting_queues: dict[int, list[int]] = defaultdict(list)
queued_users: set[int] = set()
preferred_opponents: dict[int, int] = {}
active_match_by_user: dict[int, int] = {}
sessions: dict[int, dict] = {}
pending_invites: dict[int, int] = {}
events_by_user: dict[int, list[dict]] = defaultdict(list)


USER_HELP = {
    "title": "가위바위보 알고리즘 대전 시스템 일반사용자 도움말",
    "overview": {
        "description": "각 PC가 하나의 플레이어가 되어 API 또는 Python client로 가위바위보 게임에 참여하고, 사용자가 직접 만든 전략 알고리즘으로 승률을 실험하는 시스템입니다.",
        "roles": [
            "Web UI: 브라우저에서 직접 입장, 매칭, 게임, 전적/분석 확인",
            "Python client: 각 PC에서 자동으로 게임에 참여하는 봇",
            "Strategy file: 사용자가 작성하는 선택 알고리즘",
        ],
    },
    "web_ui": {
        "title": "Web UI 사용법",
        "steps": [
            "브라우저에서 http://127.0.0.1:8000 접속",
            "이름을 입력하고 입장",
            "로비에서 매칭 시작 또는 초청 매칭 사용",
            "매칭 후 바위/보/가위 선택",
            "결과, 전적, 개인 분석, 랭킹 확인",
        ],
        "features": [
            "방 생성/참가/나가기",
            "일반 매칭",
            "초청 매칭",
            "개인 승패 기록",
            "선택별/상대별/최근 흐름 분석",
        ],
    },
    "client": {
        "title": "Python client 사용법",
        "commands": [
            "python rps_client.py --profile p1 --name BotA --choice rock",
            "python rps_client.py --profile p2 --name BotB --choice scissors",
            "python rps_client.py --profile p1 --rounds 10 --strategy-file strategies\\best_choice_strategy.py",
            "python rps_client.py --profile p1 --wait-previous-opponent --strategy-file strategies\\my_strategy.py",
        ],
        "notes": [
            "같은 PC에서 여러 클라이언트를 실행할 때는 profile을 다르게 지정해야 합니다.",
            "처음 실행하면 profile별 client_id가 PC에 저장됩니다.",
            "rounds 옵션은 같은 game_id 안에서 여러 라운드를 진행합니다.",
        ],
    },
    "strategy": {
        "title": "전략 파일 작성법",
        "description": "전략 파일은 choose(context) 함수를 정의하는 Python 파일입니다.",
        "example": [
            "import random",
            "",
            "def choose(context):",
            "    analysis = context['analysis']",
            "    if analysis['best_choice'] in context['choices']:",
            "        return analysis['best_choice']",
            "    return random.choice(context['choices'])",
        ],
        "context_keys": [
            "client: API 호출용 RpsClient 객체",
            "game_id: 현재 게임 ID",
            "round_index: 현재 라운드 번호",
            "me: 내 사용자 정보",
            "state: 현재 상태",
            "analysis: 개인 분석 결과",
            "saved: PC 저장 정보",
            "choices: ('rock', 'paper', 'scissors')",
        ],
    },
    "api": {
        "title": "API 사용법",
        "flow": [
            "POST /api/players 로 client_id 발급",
            "POST /api/match/join 으로 매칭 참가",
            "GET /api/state 로 game_id 대기",
            "POST /api/match/choice 로 선택 제출",
            "GET /api/games/{game_id}/result 로 승패 조회",
            "GET /api/analysis 로 개인 분석 조회",
        ],
        "auth": [
            "JSON body의 coupon_id",
            "X-Coupon-ID header",
            "query string의 coupon_id",
        ],
    },
    "ids": {
        "client_id": "PC/플레이어 고유 ID입니다. coupon_id와 같은 값입니다.",
        "game_name": "참가자 조합으로 생성되는 게임 이름입니다.",
        "game_id": "game_name에 serial을 붙인 실제 게임 ID입니다.",
    },
    "troubleshooting": [
        {
            "title": "같은 PC에서 매칭되지 않음",
            "solution": "두 클라이언트가 같은 profile을 사용하고 있을 수 있습니다. --profile p1, --profile p2처럼 다르게 실행하세요.",
        },
        {
            "title": "end: already ended by the other client",
            "solution": "오류가 아닙니다. 상대 클라이언트가 먼저 매치를 종료한 상태입니다.",
        },
        {
            "title": "TimeoutError",
            "solution": "상대 클라이언트가 실행 중인지, 같은 profile을 재사용하지 않았는지 확인하세요.",
        },
    ],
}


USER_HELP = {
    "title": "가위바위보 알고리즘 대전 시스템 일반사용자 도움말",
    "overview": {
        "description": "각 PC가 하나의 플레이어가 되어 API 또는 Python client로 게임에 참여하고, 사용자가 직접 만든 전략 알고리즘으로 승률을 실험하는 시스템입니다.",
        "roles": [
            "Web UI: 브라우저에서 직접 입장, 매칭, 게임, 전적/분석 확인",
            "Python client: 각 PC에서 자동으로 게임에 참여하는 실행형 봇",
            "api_client.py: 다른 Python 프로그램에서 재사용하는 API 호출 모듈",
            "strategy file: 사용자가 작성하는 선택 알고리즘 파일",
        ],
    },
    "web_ui": {
        "title": "Web UI 사용법",
        "steps": [
            "브라우저에서 http://127.0.0.1:8000 접속",
            "이름을 입력하고 입장",
            "로비에서 매칭 시작 또는 초대 매칭 사용",
            "매칭 후 rock/paper/scissors 중 하나 선택",
            "결과, 전적, 개인 분석, 티켓 확인",
        ],
    },
    "client": {
        "title": "실행형 Python client 사용법",
        "commands": [
            "python rps_client.py --profile p1 --name BotA --choice rock",
            "python rps_client.py --profile p2 --name BotB --choice scissors",
            "python rps_client.py --profile p1 --rounds 10 --strategy-file strategies\\best_choice_strategy.py",
            "python rps_client.py --profile p1 --wait-previous-opponent --strategy-file strategies\\my_strategy.py",
        ],
        "notes": [
            "같은 PC에서 여러 client를 실행할 때는 --profile 값을 다르게 지정합니다.",
            "처음 실행하면 profile별 client_id/coupon_id가 PC에 저장됩니다.",
            "--rounds 옵션은 같은 game_id 안에서 여러 라운드를 진행합니다.",
        ],
    },
    "api_client": {
        "title": "api_client.py 재사용 방법",
        "description": "api_client.py는 다른 Python 코드에서 import해서 쓰는 간단한 API 래퍼입니다.",
        "commands": [
            "python sample_api_game.py --name BotA --choice rock",
            "python sample_api_game.py --name BotB --choice scissors",
        ],
        "sample": [
            "from api_client import RpsApiClient",
            "",
            "client = RpsApiClient('http://127.0.0.1:8000')",
            "player = client.create_player('MyBot')",
            "client.coupon_id = player['coupon_id']",
            "joined = client.join_match()",
            "game_id = joined.get('game_id') or client.wait_for_game()",
            "client.submit_choice('rock')",
            "result = client.wait_for_next_result(game_id, 0)",
            "print(result['latest_result']['player_result'])",
        ],
    },
    "strategy": {
        "title": "전략 파일 작성법",
        "description": "전략 파일은 choose(context) 함수를 정의하는 Python 파일입니다.",
        "example": [
            "import random",
            "",
            "def choose(context):",
            "    analysis = context['analysis']",
            "    best_choice = analysis.get('best_choice')",
            "    if best_choice in context['choices']:",
            "        return best_choice",
            "    return random.choice(context['choices'])",
        ],
        "context_keys": [
            "client: API 호출용 RpsClient 객체",
            "game_id: 현재 게임 ID",
            "round_index: 현재 라운드 번호",
            "me: 내 사용자 정보",
            "state: 현재 상태",
            "analysis: 개인 분석 결과",
            "saved: PC 저장 정보",
            "choices: ('rock', 'paper', 'scissors')",
        ],
    },
    "api": {
        "title": "API 사용 흐름",
        "flow": [
            "POST /api/players 로 client_id/coupon_id 발급",
            "POST /api/match/join 으로 매칭 참여",
            "GET /api/state 로 game_id 대기",
            "POST /api/match/choice 로 선택 제출",
            "GET /api/games/{game_id}/result 로 승패 조회",
            "GET /api/analysis 로 개인 분석 조회",
            "GET /api/help?format=text 로 출력용 도움말 조회",
        ],
        "auth": [
            "JSON body의 coupon_id",
            "X-Coupon-ID header",
            "query string의 coupon_id",
        ],
    },
    "ids": {
        "client_id": "PC/플레이어 고유 ID입니다. coupon_id와 같은 값으로 발급됩니다.",
        "game_name": "참가자 조합으로 생성되는 게임 이름입니다. 같은 참가자 조합이면 같은 game_name을 사용합니다.",
        "game_id": "game_name에 serial을 붙인 실제 게임 ID입니다.",
    },
    "troubleshooting": [
        {
            "title": "같은 PC에서 매칭되지 않음",
            "solution": "두 client가 같은 profile을 사용하고 있을 수 있습니다. --profile p1, --profile p2처럼 다르게 실행하세요.",
        },
        {
            "title": "end: already ended by the other client",
            "solution": "오류가 아닙니다. 상대 client가 먼저 매치를 종료한 상태입니다.",
        },
        {
            "title": "TimeoutError",
            "solution": "상대 client가 실행 중인지, 같은 profile을 재사용하지 않았는지 확인하세요.",
        },
    ],
}


def help_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def localize_help_text(value: str, base_url: str) -> str:
    if not base_url:
        return value
    return value.replace("http://127.0.0.1:8000", base_url.rstrip("/"))


def render_user_help_text(section: str | None = None, base_url: str = "") -> str:
    selected = USER_HELP if section is None else {section: USER_HELP[section]}
    base_url = base_url.rstrip("/")
    lines = [
        USER_HELP["title"],
        "=" * len(USER_HELP["title"]),
        "",
        "출력용 도움말:",
        f"  GET {help_url(base_url, '/api/help?format=text')}",
        f"  GET {help_url(base_url, '/api/help?section=client&format=text')}",
        f"  GET {help_url(base_url, '/api/help?section=api_client&format=text')}",
        "",
    ]

    def add_value(key: str, value, indent: int = 0) -> None:
        prefix = " " * indent
        if isinstance(value, dict):
            title = value.get("title") or key
            lines.append(f"{prefix}[{title}]")
            for child_key, child_value in value.items():
                if child_key == "title":
                    continue
                add_value(child_key, child_value, indent + 2)
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}- {item.get('title', '')}")
                    if item.get("solution"):
                        lines.append(f"{prefix}  해결: {item['solution']}")
                else:
                    lines.append(f"{prefix}- {localize_help_text(str(item), base_url)}")
        else:
            lines.append(f"{prefix}{key}: {localize_help_text(str(value), base_url)}")

    for key, value in selected.items():
        if key == "title":
            continue
        add_value(key, value)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def help_sections() -> list[str]:
    return [key for key in USER_HELP.keys() if key != "title"]


def inline_code(text: str) -> str:
    return f"<code>{html.escape(text)}</code>"


def code_block(language: str, lines: list[str]) -> str:
    body = "\n".join(html.escape(line) for line in lines)
    return (
        '<div class="code-card">'
        f'<div class="code-lang">{html.escape(language)}</div>'
        f"<pre><code>{body}</code></pre>"
        "</div>"
    )


def render_user_help_html(section: str | None = None, base_url: str = "") -> str:
    base_url = base_url.rstrip("/")
    title = html.escape(USER_HELP["title"])
    section_suffix = f"&section={html.escape(section)}" if section else ""
    selected_title = ""
    if section:
        selected = USER_HELP[section]
        if isinstance(selected, dict):
            selected_title = html.escape(selected.get("title") or section)
        else:
            selected_title = html.escape(section)

    body_parts = [
        '<ul class="help-list">',
        f"<li>{inline_code('GET ' + help_url(base_url, '/api/help'))} : 브라우저용 도움말 페이지</li>",
        f"<li>{inline_code('GET ' + help_url(base_url, '/api/help?format=json'))} : JSON 도움말</li>",
        f"<li>{inline_code('GET ' + help_url(base_url, '/api/help?format=text'))} : print/text 도움말</li>",
        f"<li>{inline_code('GET ' + help_url(base_url, '/api/help?section=client&format=text'))}</li>",
        f"<li>{inline_code('GET ' + help_url(base_url, '/api/help?section=api_client&format=text'))}</li>",
        "</ul>",
        '<ul class="help-list">',
        f"<li>JSON 도움말에 {inline_code('print_version')} 필드가 필요하면 {inline_code('include_print=1')}을 붙입니다.</li>",
        f"<li>재사용 가능한 API client: <a href='{help_url(base_url, '/api/help?section=api_client')}'>api_client.py</a></li>",
        f"<li>실행 가능한 샘플 코드: <a href='{help_url(base_url, '/api/help?section=api_client')}'>sample_api_game.py</a></li>",
        "<li>사용자 설명서/README에 api_client.py, 샘플 코드, print 도움말 사용법이 포함되어 있습니다.</li>",
        "</ul>",
    ]

    if selected_title:
        body_parts.append(f"<h2>{selected_title}</h2>")

    body_parts.extend(
        [
            "<p>실행 예시는 아래처럼 쓰면 됩니다.</p>",
            code_block(
                "powershell",
                [
                    "python app.py",
                    f'curl "{help_url(base_url, "/api/help?format=text")}"',
                    f'curl "{help_url(base_url, "/api/help?section=api_client&format=text")}"',
                ],
            ),
            "<p>샘플 API 게임:</p>",
            code_block(
                "powershell",
                [
                    "python sample_api_game.py --name BotA --choice rock",
                    "python sample_api_game.py --name BotB --choice scissors",
                ],
            ),
        ]
    )

    if section == "api_client":
        sample = [localize_help_text(line, base_url) for line in USER_HELP["api_client"]["sample"]]
        body_parts.extend(["<p>api_client.py 사용 예:</p>", code_block("python", sample)])
    elif section == "client":
        body_parts.extend(["<p>실행형 client 명령:</p>", code_block("powershell", USER_HELP["client"]["commands"])])
    elif section == "strategy":
        body_parts.extend(["<p>전략 파일 예:</p>", code_block("python", USER_HELP["strategy"]["example"])])
    elif section == "api":
        body_parts.append("<ul class='help-list'>" + "".join(f"<li>{html.escape(item)}</li>" for item in USER_HELP["api"]["flow"]) + "</ul>")

    body_parts.extend(
        [
            "<p>검증 완료:</p>",
            '<ul class="help-list">',
            f"<li>{inline_code('app.py')}, {inline_code('rps_client.py')}, {inline_code('api_client.py')}, {inline_code('sample_api_game.py')} 문법 검사 통과</li>",
            f"<li>Flask test client로 {inline_code(help_url(base_url, '/api/help?format=text'))}, {inline_code(help_url(base_url, '/api/help?section=api_client'))} 정상 응답 확인 완료</li>",
            "</ul>",
        ]
    )

    sections = "".join(
        f"<a href='{help_url(base_url, '/api/help?section=' + html.escape(name))}'>{html.escape(name)}</a>"
        for name in help_sections()
    )
    content = "\n".join(body_parts)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #fff; color: #202124; font-size: 18px; line-height: 1.65; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 30px 42px 64px; }}
    h1 {{ font-size: 30px; margin: 0 0 18px; letter-spacing: 0; }}
    h2 {{ font-size: 24px; margin: 24px 0 10px; letter-spacing: 0; }}
    p {{ margin: 24px 0 12px; }}
    a {{ color: #1a73e8; font-weight: 650; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{ background: #f5f5f5; border-radius: 10px; padding: 2px 10px; font-family: Consolas, "SFMono-Regular", monospace; font-size: 0.95em; }}
    .help-list {{ margin: 0 0 22px 28px; padding: 0; }}
    .help-list li {{ margin: 12px 0; padding-left: 4px; }}
    .section-links {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0 28px; }}
    .section-links a {{ border: 1px solid #e5e7eb; border-radius: 999px; padding: 5px 12px; background: #fafafa; font-size: 15px; }}
    .code-card {{ position: relative; background: #efefef; border-radius: 12px; padding: 18px 18px 16px; margin: 14px 0 22px; overflow-x: auto; }}
    .code-lang {{ color: #666; margin-bottom: 18px; font-size: 16px; }}
    pre {{ margin: 0; white-space: pre-wrap; }}
    pre code {{ display: block; background: transparent; border-radius: 0; padding: 0; color: #111827; font-size: 18px; line-height: 1.65; }}
    .meta {{ color: #5f6368; margin-bottom: 12px; }}
    @media (max-width: 720px) {{
      main {{ padding: 22px 20px 44px; }}
      body {{ font-size: 16px; }}
      pre code {{ font-size: 15px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <div class="meta">일반사용자용 도움말입니다. API용 JSON은 {inline_code('format=json')}으로 조회합니다.</div>
    <div class="section-links">{sections}</div>
    {content}
  </main>
</body>
</html>
"""


def now() -> dt.datetime:
    return dt.datetime.utcnow()


def now_text() -> str:
    return now().isoformat(timespec="seconds")


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with db_connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_id TEXT UNIQUE,
                name TEXT NOT NULL,
                room_id INTEGER NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_id) REFERENCES rooms(room_id)
            );

            CREATE TABLE IF NOT EXISTS matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE,
                game_name TEXT,
                game_serial INTEGER,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT NULL,
                FOREIGN KEY(player1_id) REFERENCES users(user_id),
                FOREIGN KEY(player2_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS rounds (
                round_id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                p1_choice TEXT NOT NULL,
                p2_choice TEXT NOT NULL,
                winner_id INTEGER NULL,
                result_type TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(match_id) REFERENCES matches(match_id)
            );
            """
        )
        columns = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "coupon_id" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN coupon_id TEXT")
        for row in con.execute("SELECT user_id FROM users WHERE coupon_id IS NULL OR coupon_id = ''").fetchall():
            con.execute("UPDATE users SET coupon_id = ? WHERE user_id = ?", (generate_coupon_id(), row["user_id"]))
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_coupon_id ON users(coupon_id)")
        match_columns = {row["name"] for row in con.execute("PRAGMA table_info(matches)").fetchall()}
        if "game_id" not in match_columns:
            con.execute("ALTER TABLE matches ADD COLUMN game_id TEXT")
        if "game_name" not in match_columns:
            con.execute("ALTER TABLE matches ADD COLUMN game_name TEXT")
        if "game_serial" not in match_columns:
            con.execute("ALTER TABLE matches ADD COLUMN game_serial INTEGER")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_game_id ON matches(game_id)")
        for row in con.execute("SELECT match_id, player1_id, player2_id FROM matches WHERE game_id IS NULL OR game_id = ''").fetchall():
            game_name = build_game_name([row["player1_id"], row["player2_id"]])
            serial = int(row["match_id"])
            game_id = format_game_id(game_name, serial)
            con.execute(
                "UPDATE matches SET game_id = ?, game_name = ?, game_serial = ? WHERE match_id = ?",
                (game_id, game_name, serial, row["match_id"]),
            )


def current_user_id() -> int | None:
    user_id = session.get("user_id")
    try:
        return int(user_id) if user_id else None
    except Exception:
        return None


def generate_coupon_id() -> str:
    return "RPS-" + secrets.token_urlsafe(16)


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip().lower())
    return cleaned.strip("-") or "player"


def build_game_name(user_ids: list[int]) -> str:
    with db_connect() as con:
        rows = con.execute(
            f"SELECT user_id, name FROM users WHERE user_id IN ({','.join(['?'] * len(user_ids))})",
            tuple(user_ids),
        ).fetchall()
    participants = sorted((row["name"], row["user_id"]) for row in rows)
    pieces = [f"{slug(name)}-{user_id}" for name, user_id in participants]
    return f"rps-{len(participants)}p-" + "-".join(pieces)


def format_game_id(game_name: str, serial: int) -> str:
    return f"{game_name}-{serial:04d}"


def next_game_identity(user_ids: list[int]) -> tuple[str, str, int]:
    game_name = build_game_name(user_ids)
    with db_connect() as con:
        row = con.execute(
            "SELECT COALESCE(MAX(game_serial), 0) AS max_serial FROM matches WHERE game_name = ?",
            (game_name,),
        ).fetchone()
    serial = int(row["max_serial"] or 0) + 1
    return game_name, format_game_id(game_name, serial), serial


def request_coupon_id() -> str | None:
    data = request.get_json(silent=True) if request.is_json else None
    coupon_id = None
    if isinstance(data, dict):
        coupon_id = data.get("coupon_id")
    coupon_id = coupon_id or request.headers.get("X-Coupon-ID") or request.args.get("coupon_id")
    return str(coupon_id).strip() if coupon_id else None


def create_user(name: str) -> sqlite3.Row:
    for _ in range(10):
        coupon_id = generate_coupon_id()
        try:
            with db_connect() as con:
                cur = con.execute(
                    """
                    INSERT INTO users (coupon_id, name, status, created_at, last_seen_at)
                    VALUES (?, ?, 'idle', ?, ?)
                    """,
                    (coupon_id, name, now_text(), now_text()),
                )
                return con.execute("SELECT * FROM users WHERE user_id = ?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("coupon_id_generation_failed")


def require_user() -> tuple[sqlite3.Row | None, tuple | None]:
    coupon_id = request_coupon_id()
    with db_connect() as con:
        if coupon_id:
            user = con.execute("SELECT * FROM users WHERE coupon_id = ?", (coupon_id,)).fetchone()
        else:
            user_id = current_user_id()
            if not user_id:
                return None, (jsonify(ok=False, error="not_entered"), 401)
            user = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            return None, (jsonify(ok=False, error="user_not_found"), 404)
        con.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (now_text(), user["user_id"]))
    return user, None


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    out = dict(row)
    if "coupon_id" in out:
        out["client_id"] = out["coupon_id"]
    return out


def get_user_name(user_id: int) -> str:
    with db_connect() as con:
        row = con.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["name"] if row else str(user_id)


def judge(c1: str, c2: str) -> int:
    if c1 == c2:
        return 0
    wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    return 1 if (c1, c2) in wins else 2


def push_event(user_id: int, payload: dict) -> None:
    events_by_user[user_id].append(payload)
    if len(events_by_user[user_id]) > 50:
        events_by_user[user_id] = events_by_user[user_id][-50:]


def result_payload(sess: dict, p1_choice: str, p2_choice: str, winner_id: int | None, result_type: str, note: str = "") -> dict:
    return {
        "event": "result",
        "game_id": sess["game_id"],
        "game_name": sess["game_name"],
        "game_serial": sess["game_serial"],
        "match_id": sess["match_id"],
        "round_no": sess["round_no"],
        "played_at": now().isoformat() + "Z",
        "room_id": sess["room_id"],
        "p1": {"id": sess["p1_id"], "name": sess["p1_name"], "choice": p1_choice},
        "p2": {"id": sess["p2_id"], "name": sess["p2_name"], "choice": p2_choice},
        "winner_id": winner_id,
        "result_type": result_type,
        "note": note,
        "next_round": sess["round_no"] + 1,
    }


def save_round(payload: dict) -> None:
    with db_connect() as con:
        con.execute(
            """
            INSERT INTO rounds (match_id, played_at, p1_choice, p2_choice, winner_id, result_type, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["match_id"],
                now_text(),
                payload["p1"]["choice"],
                payload["p2"]["choice"],
                payload["winner_id"],
                payload["result_type"],
                payload.get("note", ""),
            ),
        )


def finish_round(sess: dict, p1_choice: str, p2_choice: str, note: str = "") -> dict:
    if p1_choice == "none" and p2_choice == "none":
        winner_id, result_type = None, "timeout_draw"
    elif p1_choice != "none" and p2_choice == "none":
        winner_id, result_type = sess["p1_id"], "timeout_p1"
    elif p1_choice == "none" and p2_choice != "none":
        winner_id, result_type = sess["p2_id"], "timeout_p2"
    else:
        out = judge(p1_choice, p2_choice)
        if out == 0:
            winner_id, result_type = None, "draw"
        elif out == 1:
            winner_id, result_type = sess["p1_id"], "p1_win"
        else:
            winner_id, result_type = sess["p2_id"], "p2_win"

    payload = result_payload(sess, p1_choice, p2_choice, winner_id, result_type, note)
    save_round(payload)
    sess["round_no"] += 1
    sess["choices"] = {}
    sess["round_started_at"] = time.time()
    push_event(sess["p1_id"], payload)
    push_event(sess["p2_id"], payload)
    return payload


def check_timeouts() -> None:
    with state_lock:
        for sess in list(sessions.values()):
            if time.time() - sess["round_started_at"] < CHOICE_TIMEOUT_SECONDS:
                continue
            choices = sess["choices"]
            if len(choices) >= 2:
                continue
            p1_choice = choices.get(sess["p1_id"], "none")
            p2_choice = choices.get(sess["p2_id"], "none")
            finish_round(sess, p1_choice, p2_choice, note="timeout")


def create_match(p1_id: int, p2_id: int, room_id: int | None) -> dict:
    game_name, game_id, game_serial = next_game_identity([p1_id, p2_id])
    with db_connect() as con:
        cur = con.execute(
            """
            INSERT INTO matches (game_id, game_name, game_serial, player1_id, player2_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (game_id, game_name, game_serial, p1_id, p2_id, now_text()),
        )
        match_id = int(cur.lastrowid)
        con.execute(
            "UPDATE users SET status = 'playing', last_seen_at = ? WHERE user_id IN (?, ?)",
            (now_text(), p1_id, p2_id),
        )

    sess = {
        "match_id": match_id,
        "game_id": game_id,
        "game_name": game_name,
        "game_serial": game_serial,
        "p1_id": p1_id,
        "p2_id": p2_id,
        "p1_name": get_user_name(p1_id),
        "p2_name": get_user_name(p2_id),
        "room_id": room_id,
        "round_no": 1,
        "choices": {},
        "round_started_at": time.time(),
    }
    sessions[match_id] = sess
    active_match_by_user[p1_id] = match_id
    active_match_by_user[p2_id] = match_id
    queued_users.discard(p1_id)
    queued_users.discard(p2_id)
    preferred_opponents.pop(p1_id, None)
    preferred_opponents.pop(p2_id, None)

    push_event(p1_id, {"event": "matched", "game_id": game_id, "game_name": game_name, "game_serial": game_serial, "match_id": match_id, "opponent": {"id": p2_id, "name": sess["p2_name"]}})
    push_event(p2_id, {"event": "matched", "game_id": game_id, "game_name": game_name, "game_serial": game_serial, "match_id": match_id, "opponent": {"id": p1_id, "name": sess["p1_name"]}})
    return sess


def remove_from_waiting_queues(user_id: int) -> None:
    for q in waiting_queues.values():
        while user_id in q:
            q.remove(user_id)


def enqueue_user(user_id: int, room_id: int | None, preferred_opponent_id: int | None = None) -> None:
    rid = int(room_id or 0)
    if user_id not in queued_users:
        queued_users.add(user_id)
        waiting_queues[rid].append(user_id)
    if preferred_opponent_id:
        preferred_opponents[user_id] = preferred_opponent_id
    else:
        preferred_opponents.pop(user_id, None)


def queued_in_room(user_id: int, room_id: int | None) -> bool:
    rid = int(room_id or 0)
    return user_id in queued_users and user_id in waiting_queues[rid]


def user_room_id(user_id: int) -> int | None:
    with db_connect() as con:
        row = con.execute("SELECT room_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["room_id"] if row else None


def create_match_from_queue(p1_id: int, p2_id: int, room_id: int | None) -> dict:
    remove_from_waiting_queues(p1_id)
    remove_from_waiting_queues(p2_id)
    return create_match(p1_id, p2_id, room_id)


def try_preferred_match(user_id: int, preferred_opponent_id: int, room_id: int | None) -> dict | None:
    if user_id in active_match_by_user or preferred_opponent_id in active_match_by_user:
        return None
    if user_room_id(preferred_opponent_id) != room_id:
        return None
    if not queued_in_room(preferred_opponent_id, room_id):
        return None

    target_preference = preferred_opponents.get(preferred_opponent_id)
    if target_preference and target_preference != user_id:
        return None

    return create_match_from_queue(user_id, preferred_opponent_id, room_id)


def try_waiting_preferred_for(user_id: int, room_id: int | None) -> dict | None:
    rid = int(room_id or 0)
    for waiter_id in list(waiting_queues[rid]):
        if waiter_id == user_id:
            continue
        if preferred_opponents.get(waiter_id) != user_id:
            continue
        if waiter_id in active_match_by_user:
            continue
        return create_match_from_queue(waiter_id, user_id, room_id)
    return None


def try_match(room_id: int | None) -> dict | None:
    rid = int(room_id or 0)
    q = waiting_queues[rid]
    candidates: list[int] = []
    deferred: list[int] = []
    while q and len(candidates) < 2:
        uid = q.pop(0)
        if uid not in queued_users or uid in active_match_by_user:
            queued_users.discard(uid)
            preferred_opponents.pop(uid, None)
            continue
        if uid in preferred_opponents:
            deferred.append(uid)
            continue
        if uid in candidates:
            continue
        candidates.append(uid)

    if len(candidates) < 2:
        q[:0] = candidates + deferred
        return None
    q[:0] = deferred

    return create_match_from_queue(candidates[0], candidates[1], room_id)


def end_match(match_id: int) -> dict | None:
    sess = sessions.pop(match_id, None)
    if not sess:
        return None
    active_match_by_user.pop(sess["p1_id"], None)
    active_match_by_user.pop(sess["p2_id"], None)
    with db_connect() as con:
        con.execute("UPDATE matches SET status = 'finished', ended_at = ? WHERE match_id = ?", (now_text(), match_id))
        con.execute("UPDATE users SET status = 'idle', last_seen_at = ? WHERE user_id IN (?, ?)", (now_text(), sess["p1_id"], sess["p2_id"]))
    push_event(sess["p1_id"], {"event": "match_ended", "game_id": sess["game_id"], "match_id": match_id})
    push_event(sess["p2_id"], {"event": "match_ended", "game_id": sess["game_id"], "match_id": match_id})
    return sess


def find_match_by_game_key(game_key: str) -> sqlite3.Row | None:
    with db_connect() as con:
        match = con.execute("SELECT * FROM matches WHERE game_id = ?", (game_key,)).fetchone()
        if match:
            return match
        try:
            numeric_id = int(game_key)
        except ValueError:
            return None
        return con.execute("SELECT * FROM matches WHERE match_id = ?", (numeric_id,)).fetchone()


def game_summary(game_key: str, user_id: int | None = None) -> tuple[dict | None, tuple | None]:
    match = find_match_by_game_key(game_key)
    with db_connect() as con:
        if not match:
            return None, (jsonify(ok=False, error="game_not_found"), 404)

        if user_id is not None and user_id not in (match["player1_id"], match["player2_id"]):
            return None, (jsonify(ok=False, error="not_game_player"), 403)

        p1 = con.execute("SELECT user_id, name FROM users WHERE user_id = ?", (match["player1_id"],)).fetchone()
        p2 = con.execute("SELECT user_id, name FROM users WHERE user_id = ?", (match["player2_id"],)).fetchone()
        rounds = con.execute(
            "SELECT * FROM rounds WHERE match_id = ? ORDER BY round_id ASC",
            (match["match_id"],),
        ).fetchall()

    items = []
    latest = None
    for r in rounds:
        player_result = None
        if user_id is not None:
            if r["winner_id"] is None:
                player_result = "draw"
            elif r["winner_id"] == user_id:
                player_result = "win"
            else:
                player_result = "lose"
        item = {
            "round_id": r["round_id"],
            "played_at": str(r["played_at"]) + "Z",
            "p1_choice": r["p1_choice"],
            "p2_choice": r["p2_choice"],
            "winner_id": r["winner_id"],
            "result_type": r["result_type"],
            "note": r["note"],
            "player_result": player_result,
        }
        items.append(item)
        latest = item

    active_sess = sessions.get(match["match_id"])
    current_round = active_sess["round_no"] if active_sess else None
    if latest is None and active_sess:
        status = "playing"
    elif match["status"] == "finished":
        status = "finished"
    else:
        status = "playing" if active_sess else match["status"]

    return {
        "game_id": match["game_id"] or str(match["match_id"]),
        "game_name": match["game_name"],
        "game_serial": match["game_serial"],
        "match_id": match["match_id"],
        "status": status,
        "current_round": current_round,
        "players": {
            "p1": {"user_id": match["player1_id"], "name": p1["name"] if p1 else str(match["player1_id"])},
            "p2": {"user_id": match["player2_id"], "name": p2["name"] if p2 else str(match["player2_id"])},
        },
        "latest_result": latest,
        "rounds": items,
    }, None


def empty_record() -> dict:
    return {"win": 0, "lose": 0, "draw": 0, "total": 0, "win_rate": 0.0}


def finalize_record(record: dict) -> dict:
    total_decided = record["win"] + record["lose"]
    record["total"] = record["win"] + record["lose"] + record["draw"]
    record["win_rate"] = round((record["win"] / total_decided * 100.0), 2) if total_decided else 0.0
    return record


def player_round_result(row: sqlite3.Row, user_id: int) -> str:
    if row["winner_id"] is None:
        return "draw"
    return "win" if row["winner_id"] == user_id else "lose"


def build_player_analysis(user_id: int) -> dict:
    with db_connect() as con:
        user = con.execute("SELECT user_id, name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        rows = con.execute(
            """
            SELECT r.*, m.player1_id, m.player2_id, m.game_id, m.game_name, m.game_serial
            FROM rounds r
            JOIN matches m ON m.match_id = r.match_id
            WHERE m.player1_id = ? OR m.player2_id = ?
            ORDER BY r.round_id ASC
            """,
            (user_id, user_id),
        ).fetchall()

        opponent_names = {
            row["user_id"]: row["name"]
            for row in con.execute("SELECT user_id, name FROM users").fetchall()
        }

    summary = empty_record()
    choices = {choice: empty_record() for choice in sorted(CHOICES)}
    opponents: dict[int, dict] = {}
    recent: list[dict] = []

    for row in rows:
        result = player_round_result(row, user_id)
        my_choice = row["p1_choice"] if user_id == row["player1_id"] else row["p2_choice"]
        opp_choice = row["p2_choice"] if user_id == row["player1_id"] else row["p1_choice"]
        opponent_id = row["player2_id"] if user_id == row["player1_id"] else row["player1_id"]

        summary[result] += 1
        if my_choice in choices:
            choices[my_choice][result] += 1

        if opponent_id not in opponents:
            opponents[opponent_id] = {
                "opponent_id": opponent_id,
                "opponent_name": opponent_names.get(opponent_id, str(opponent_id)),
                **empty_record(),
            }
        opponents[opponent_id][result] += 1

        recent.append(
            {
                "round_id": row["round_id"],
                "game_id": row["game_id"] or str(row["match_id"]),
                "played_at": str(row["played_at"]) + "Z",
                "opponent_id": opponent_id,
                "opponent_name": opponent_names.get(opponent_id, str(opponent_id)),
                "result": result,
                "my_choice": my_choice,
                "opp_choice": opp_choice,
            }
        )

    summary = finalize_record(summary)
    choices = {choice: finalize_record(record) for choice, record in choices.items()}
    opponent_items = [finalize_record(record) for record in opponents.values()]
    opponent_items.sort(key=lambda item: (item["total"], item["win_rate"]), reverse=True)

    recent_desc = list(reversed(recent[-20:]))
    recent_10 = recent[-10:]
    recent_record = empty_record()
    for item in recent_10:
        recent_record[item["result"]] += 1
    recent_record = finalize_record(recent_record)

    streak_type = None
    streak_count = 0
    for item in reversed(recent):
        if streak_type is None:
            streak_type = item["result"]
            streak_count = 1
        elif item["result"] == streak_type:
            streak_count += 1
        else:
            break

    favorite_choice = max(choices.items(), key=lambda pair: (pair[1]["total"], pair[1]["win"]), default=(None, None))[0]
    played_choices = {choice: record for choice, record in choices.items() if record["total"] > 0}
    best_choice = max(played_choices.items(), key=lambda pair: (pair[1]["win_rate"], pair[1]["win"], pair[1]["total"]), default=(None, None))[0]
    weakest_choice = min(played_choices.items(), key=lambda pair: (pair[1]["win_rate"], -pair[1]["total"]), default=(None, None))[0]

    insights = []
    if summary["total"] == 0:
        insights.append("아직 기록된 라운드가 없습니다. 첫 게임을 진행하면 분석이 표시됩니다.")
    else:
        insights.append(f"전체 {summary['total']}라운드 중 {summary['win']}승 {summary['lose']}패 {summary['draw']}무입니다.")
        if favorite_choice:
            insights.append(f"가장 자주 낸 선택은 {favorite_choice}입니다.")
        if best_choice:
            insights.append(f"현재 가장 성과가 좋은 선택은 {best_choice}이며 승률은 {choices[best_choice]['win_rate']}%입니다.")
        if weakest_choice and weakest_choice != best_choice:
            insights.append(f"가장 보완이 필요한 선택은 {weakest_choice}입니다.")
        if streak_type:
            labels = {"win": "연승", "lose": "연패", "draw": "연속 무승부"}
            insights.append(f"현재 흐름은 {streak_count}{labels.get(streak_type, '연속')}입니다.")
        if recent_record["total"] >= 3:
            insights.append(f"최근 {recent_record['total']}라운드 승률은 {recent_record['win_rate']}%입니다.")

    return {
        "user": {"user_id": user_id, "name": user["name"] if user else str(user_id)},
        "summary": summary,
        "choices": choices,
        "opponents": opponent_items[:20],
        "recent_record": recent_record,
        "recent_rounds": recent_desc,
        "streak": {"type": streak_type, "count": streak_count},
        "favorite_choice": favorite_choice,
        "best_choice": best_choice,
        "weakest_choice": weakest_choice,
        "insights": insights,
    }


@app.before_request
def before_request() -> None:
    check_timeouts()


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/enter")
def enter():
    name = (request.form.get("name") or "").strip()
    if not name:
        return redirect("/")
    user = create_user(name)
    session["user_id"] = int(user["user_id"])
    return redirect("/lobby")


@app.post("/api/players")
def api_create_player():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="name_required"), 400
    user = create_user(name)
    return jsonify(
        ok=True,
        client_id=user["coupon_id"],
        game_id=None,
        user={
            "user_id": user["user_id"],
            "client_id": user["coupon_id"],
            "name": user["name"],
            "coupon_id": user["coupon_id"],
            "status": user["status"],
            "room_id": user["room_id"],
        },
        coupon_id=user["coupon_id"],
    )


@app.get("/lobby")
def lobby():
    user, error = require_user()
    if error:
        return redirect("/")
    return render_template("lobby.html", user=user)


@app.get("/logout")
def logout():
    user_id = current_user_id()
    if user_id:
        with state_lock:
            queued_users.discard(user_id)
            preferred_opponents.pop(user_id, None)
            remove_from_waiting_queues(user_id)
            pending_invites.pop(user_id, None)
        with db_connect() as con:
            con.execute("UPDATE users SET status = 'offline', last_seen_at = ? WHERE user_id = ?", (now_text(), user_id))
    session.clear()
    return redirect("/")


@app.get("/admin")
def admin():
    with db_connect() as con:
        users = con.execute("SELECT * FROM users ORDER BY user_id ASC LIMIT 200").fetchall()
        rooms = con.execute("SELECT * FROM rooms ORDER BY room_id ASC LIMIT 200").fetchall()
        matches = con.execute("SELECT * FROM matches ORDER BY match_id DESC LIMIT 200").fetchall()
        rounds = con.execute("SELECT * FROM rounds ORDER BY round_id DESC LIMIT 200").fetchall()
    return render_template("admin.html", users=users, rooms=rooms, matches=matches, rounds=rounds)


@app.get("/api/me")
def api_me():
    user, error = require_user()
    if error:
        return error
    return jsonify(ok=True, user=row_to_dict(user))


@app.get("/api/help")
def api_help():
    section = (request.args.get("section") or "").strip()
    output_format = (request.args.get("format") or request.args.get("view") or "").strip().lower()
    base_url = request.url_root.rstrip("/")
    wants_json = output_format == "json"
    wants_text = output_format in {"text", "print", "plain"} or request.args.get("print") in {"1", "true", "yes"}
    if section and section not in USER_HELP:
        if wants_text:
            return Response(
                f"help_section_not_found\nsections: {', '.join(help_sections())}\n",
                status=404,
                mimetype="text/plain; charset=utf-8",
            )
        if wants_json:
            return jsonify(ok=False, error="help_section_not_found", sections=help_sections()), 404
        return Response(
            render_user_help_html(base_url=base_url),
            status=404,
            mimetype="text/html; charset=utf-8",
        )
    if wants_text:
        return Response(render_user_help_text(section or None, base_url=base_url), mimetype="text/plain; charset=utf-8")
    if not wants_json:
        return Response(render_user_help_html(section or None, base_url=base_url), mimetype="text/html; charset=utf-8")
    if not section:
        include_print = request.args.get("include_print") in {"1", "true", "yes"}
        payload = {
            "ok": True,
            "help": USER_HELP,
            "sections": help_sections(),
            "print_help_url": help_url(base_url, "/api/help?format=text"),
        }
        if include_print:
            payload["print_version"] = render_user_help_text(base_url=base_url)
        return jsonify(payload)
    payload = {
        "ok": True,
        "section": section,
        "help": USER_HELP[section],
        "print_help_url": help_url(base_url, f"/api/help?section={section}&format=text"),
    }
    if request.args.get("include_print") in {"1", "true", "yes"}:
        payload["print_version"] = render_user_help_text(section, base_url=base_url)
    return jsonify(payload)


@app.get("/api/help/print")
def api_help_print():
    section = (request.args.get("section") or "").strip()
    base_url = request.url_root.rstrip("/")
    if section and section not in USER_HELP:
        return Response(
            f"help_section_not_found\nsections: {', '.join(help_sections())}\n",
            status=404,
            mimetype="text/plain; charset=utf-8",
        )
    return Response(render_user_help_text(section or None, base_url=base_url), mimetype="text/plain; charset=utf-8")


@app.get("/api/state")
def api_state():
    user, error = require_user()
    if error:
        return error
    user_id = int(user["user_id"])
    with state_lock:
        match_id = active_match_by_user.get(user_id)
        sess = sessions.get(match_id) if match_id else None
        waiting_for_user_id = preferred_opponents.get(user_id)
        waiting_for_name = get_user_name(waiting_for_user_id) if waiting_for_user_id else None
        invites = [
            {"from_user_id": from_id, "from_name": get_user_name(from_id)}
            for to_id, from_id in list(pending_invites.items())
            if to_id == user_id
        ]
        events = events_by_user.pop(user_id, [])

    match = None
    if sess:
        opponent_id = sess["p2_id"] if user_id == sess["p1_id"] else sess["p1_id"]
        opponent_name = sess["p2_name"] if user_id == sess["p1_id"] else sess["p1_name"]
        match = {
            "game_id": sess["game_id"],
            "game_name": sess["game_name"],
            "game_serial": sess["game_serial"],
            "match_id": sess["match_id"],
            "round_no": sess["round_no"],
            "opponent": {"id": opponent_id, "name": opponent_name},
            "timer_left": max(0, CHOICE_TIMEOUT_SECONDS - int(time.time() - sess["round_started_at"])),
            "choice_submitted": user_id in sess["choices"],
        }
    waiting_for = None
    if waiting_for_user_id:
        waiting_for = {"user_id": waiting_for_user_id, "name": waiting_for_name}
    return jsonify(ok=True, user=row_to_dict(user), match=match, waiting_for=waiting_for, invites=invites, events=events)


@app.post("/api/match/join")
def api_match_join():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    preferred_opponent_id = data.get("preferred_opponent_id")
    if preferred_opponent_id is not None:
        try:
            preferred_opponent_id = int(preferred_opponent_id)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="invalid_preferred_opponent_id"), 400
        if preferred_opponent_id <= 0:
            preferred_opponent_id = None
    user_id = int(user["user_id"])
    if preferred_opponent_id == user_id:
        return jsonify(ok=False, error="cannot_wait_self"), 400
    room_id = user["room_id"]
    rid = int(room_id or 0)
    game_id = None
    match_id = None
    with state_lock:
        if user_id in active_match_by_user:
            match_id = active_match_by_user[user_id]
            sess = sessions.get(match_id)
            game_id = sess["game_id"] if sess else str(match_id)
            return jsonify(ok=True, status="already_in_match", game_id=game_id, match_id=match_id)
        if preferred_opponent_id:
            with db_connect() as con:
                target = con.execute("SELECT user_id, name, room_id FROM users WHERE user_id = ?", (preferred_opponent_id,)).fetchone()
            if not target:
                return jsonify(ok=False, error="preferred_opponent_not_found"), 404
            if target["room_id"] != room_id:
                return jsonify(ok=False, error="preferred_opponent_different_room"), 400
        enqueue_user(user_id, room_id, preferred_opponent_id)
        with db_connect() as con:
            con.execute("UPDATE users SET status = 'queued', last_seen_at = ? WHERE user_id = ?", (now_text(), user_id))
        if preferred_opponent_id:
            matched = try_preferred_match(user_id, preferred_opponent_id, room_id)
        else:
            matched = try_waiting_preferred_for(user_id, room_id) or try_match(room_id)
        if matched and user_id in active_match_by_user:
            match_id = active_match_by_user[user_id]
            game_id = matched["game_id"]
    if game_id:
        status = "matched"
    elif preferred_opponent_id:
        status = "waiting_preferred"
    else:
        status = "queued"
    return jsonify(
        ok=True,
        status=status,
        game_id=game_id,
        match_id=match_id,
        preferred_opponent_id=preferred_opponent_id,
    )


@app.post("/api/match/choice")
def api_match_choice():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    choice = (data.get("choice") or "").strip()
    if choice not in CHOICES:
        return jsonify(ok=False, error="invalid_choice"), 400

    user_id = int(user["user_id"])
    with state_lock:
        match_id = active_match_by_user.get(user_id)
        sess = sessions.get(match_id) if match_id else None
        if not sess:
            return jsonify(ok=False, error="no_active_match"), 400
        sess["choices"][user_id] = choice
        if len(sess["choices"]) < 2:
            return jsonify(ok=True, status="waiting", game_id=sess["game_id"], match_id=match_id)
        payload = finish_round(
            sess,
            sess["choices"].get(sess["p1_id"], "none"),
            sess["choices"].get(sess["p2_id"], "none"),
        )
    return jsonify(ok=True, status="result", game_id=payload["game_id"], match_id=match_id, result=payload)


@app.post("/api/match/end")
def api_match_end():
    user, error = require_user()
    if error:
        return error
    user_id = int(user["user_id"])
    with state_lock:
        match_id = active_match_by_user.get(user_id)
        if not match_id:
            return jsonify(ok=True, status="no_active_match")
        sess = sessions.get(match_id)
        game_id = sess["game_id"] if sess else None
        end_match(match_id)
    return jsonify(ok=True, status="ended", game_id=game_id, match_id=match_id)


@app.get("/api/games/<path:game_id>/result")
def api_game_result(game_id: str):
    user, error = require_user()
    if error:
        return error
    summary, summary_error = game_summary(game_id, int(user["user_id"]))
    if summary_error:
        return summary_error
    return jsonify(ok=True, **summary)


@app.get("/api/games/<path:game_id>")
def api_game_detail(game_id: str):
    user, error = require_user()
    if error:
        return error
    summary, summary_error = game_summary(game_id, int(user["user_id"]))
    if summary_error:
        return summary_error
    return jsonify(ok=True, **summary)


@app.post("/api/match/invite")
def api_invite():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    to_user_id = int(data.get("to_user_id") or 0)
    from_user_id = int(user["user_id"])
    if not to_user_id or to_user_id == from_user_id:
        return jsonify(ok=False, error="invalid_target"), 400

    with db_connect() as con:
        target = con.execute("SELECT * FROM users WHERE user_id = ?", (to_user_id,)).fetchone()
    if not target:
        return jsonify(ok=False, error="target_not_found"), 404
    if user["status"] != "idle" or target["status"] != "idle":
        return jsonify(ok=False, error="not_idle"), 400
    if user["room_id"] is not None and target["room_id"] is not None and user["room_id"] != target["room_id"]:
        return jsonify(ok=False, error="different_room"), 400

    with state_lock:
        if from_user_id in active_match_by_user or to_user_id in active_match_by_user:
            return jsonify(ok=False, error="already_in_match"), 400
        pending_invites[to_user_id] = from_user_id
        push_event(to_user_id, {"event": "invited", "from": {"user_id": from_user_id, "name": user["name"]}})
    return jsonify(ok=True)


@app.post("/api/match/invite/respond")
def api_invite_respond():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    from_user_id = int(data.get("from_user_id") or 0)
    accepted = bool(data.get("accepted"))
    user_id = int(user["user_id"])
    game_id = None

    with state_lock:
        if pending_invites.get(user_id) != from_user_id:
            return jsonify(ok=False, error="no_pending_invite"), 400
        pending_invites.pop(user_id, None)
        if not accepted:
            push_event(from_user_id, {"event": "invite_declined", "to_user_id": user_id})
            return jsonify(ok=True)
        if user_id in active_match_by_user or from_user_id in active_match_by_user:
            return jsonify(ok=False, error="already_in_match"), 400

        with db_connect() as con:
            inviter = con.execute("SELECT * FROM users WHERE user_id = ?", (from_user_id,)).fetchone()
        if not inviter:
            return jsonify(ok=False, error="inviter_not_found"), 404
        room_id = user["room_id"] if user["room_id"] is not None else inviter["room_id"]
        sess = create_match(from_user_id, user_id, room_id)
        game_id = sess["game_id"]
        match_id = sess["match_id"]
    return jsonify(ok=True, game_id=game_id, match_id=match_id)


@app.get("/api/online")
def api_online():
    user, error = require_user()
    if error:
        return error
    user_id = int(user["user_id"])
    with db_connect() as con:
        if user["room_id"] is None:
            rows = con.execute(
                "SELECT user_id, name, room_id FROM users WHERE status = 'idle' AND user_id != ? ORDER BY user_id ASC",
                (user_id,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT user_id, name, room_id FROM users
                WHERE status = 'idle' AND user_id != ? AND room_id = ?
                ORDER BY user_id ASC
                """,
                (user_id, user["room_id"]),
            ).fetchall()
    return jsonify(ok=True, items=[dict(r) for r in rows])


@app.get("/api/rooms")
def api_rooms():
    with db_connect() as con:
        rows = con.execute("SELECT room_id, room_name FROM rooms ORDER BY room_id ASC").fetchall()
    return jsonify(ok=True, items=[dict(r) for r in rows])


@app.post("/api/rooms")
def api_create_room():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    room_name = (data.get("room_name") or "").strip()
    if not room_name:
        return jsonify(ok=False, error="room_name_required"), 400
    with db_connect() as con:
        cur = con.execute("INSERT INTO rooms (room_name, created_at) VALUES (?, ?)", (room_name, now_text()))
        room = con.execute("SELECT room_id, room_name FROM rooms WHERE room_id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(ok=True, room=dict(room))


@app.post("/api/rooms/join")
def api_join_room():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    room_id = int(data.get("room_id") or 0)
    with db_connect() as con:
        room = con.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
        if not room:
            return jsonify(ok=False, error="room_not_found"), 404
        con.execute("UPDATE users SET room_id = ?, last_seen_at = ? WHERE user_id = ?", (room_id, now_text(), user["user_id"]))
    return jsonify(ok=True, room={"room_id": room["room_id"], "room_name": room["room_name"]})


@app.post("/api/rooms/leave")
def api_leave_room():
    user, error = require_user()
    if error:
        return error
    with db_connect() as con:
        con.execute("UPDATE users SET room_id = NULL, last_seen_at = ? WHERE user_id = ?", (now_text(), user["user_id"]))
    return jsonify(ok=True)


@app.get("/api/history")
def api_history():
    user, error = require_user()
    if error:
        return error
    user_id = int(user["user_id"])
    with db_connect() as con:
        rows = con.execute(
            """
            SELECT r.*, m.player1_id, m.player2_id, m.game_id, m.game_name, m.game_serial
            FROM rounds r
            JOIN matches m ON m.match_id = r.match_id
            WHERE m.player1_id = ? OR m.player2_id = ?
            ORDER BY r.round_id DESC
            LIMIT 20
            """,
            (user_id, user_id),
        ).fetchall()
        items = []
        for r in rows:
            opponent_id = r["player2_id"] if user_id == r["player1_id"] else r["player1_id"]
            opp = con.execute("SELECT name FROM users WHERE user_id = ?", (opponent_id,)).fetchone()
            result = "draw" if r["winner_id"] is None else ("win" if r["winner_id"] == user_id else "lose")
            items.append(
                {
                    "game_id": r["game_id"] if "game_id" in r.keys() else r["match_id"],
                    "game_name": r["game_name"] if "game_name" in r.keys() else None,
                    "game_serial": r["game_serial"] if "game_serial" in r.keys() else None,
                    "played_at": str(r["played_at"]) + "Z",
                    "opponent_id": opponent_id,
                    "opponent_name": opp["name"] if opp else str(opponent_id),
                    "result": result,
                    "my_choice": r["p1_choice"] if user_id == r["player1_id"] else r["p2_choice"],
                    "opp_choice": r["p2_choice"] if user_id == r["player1_id"] else r["p1_choice"],
                    "match_id": r["match_id"],
                    "round_id": r["round_id"],
                }
            )
    return jsonify(ok=True, items=items)


@app.get("/api/opponents/last")
def api_last_opponent():
    user, error = require_user()
    if error:
        return error
    user_id = int(user["user_id"])
    with db_connect() as con:
        row = con.execute(
            """
            SELECT m.*, r.played_at AS last_played_at
            FROM matches m
            JOIN rounds r ON r.match_id = m.match_id
            WHERE m.player1_id = ? OR m.player2_id = ?
            ORDER BY r.round_id DESC
            LIMIT 1
            """,
            (user_id, user_id),
        ).fetchone()
        if not row:
            return jsonify(ok=True, opponent=None)
        opponent_id = row["player2_id"] if user_id == row["player1_id"] else row["player1_id"]
        opponent = con.execute("SELECT user_id, name FROM users WHERE user_id = ?", (opponent_id,)).fetchone()
    return jsonify(
        ok=True,
        opponent={"user_id": opponent_id, "name": opponent["name"] if opponent else str(opponent_id)},
        game_id=row["game_id"] or str(row["match_id"]),
        game_name=row["game_name"],
        game_serial=row["game_serial"],
        last_played_at=str(row["last_played_at"]) + "Z",
    )


@app.get("/api/stats")
def api_stats():
    user, error = require_user()
    if error:
        return error
    analysis = build_player_analysis(int(user["user_id"]))
    return jsonify(ok=True, stats=analysis["summary"])


@app.get("/api/analysis")
def api_analysis():
    user, error = require_user()
    if error:
        return error
    return jsonify(ok=True, analysis=build_player_analysis(int(user["user_id"])))


@app.get("/api/ranking")
def api_ranking():
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    with db_connect() as con:
        users = con.execute("SELECT user_id, name FROM users ORDER BY user_id ASC").fetchall()
        rows = con.execute(
            """
            SELECT r.winner_id, m.player1_id, m.player2_id
            FROM rounds r
            JOIN matches m ON m.match_id = r.match_id
            """
        ).fetchall()
    ranking = []
    for u in users:
        uid = u["user_id"]
        win = lose = draw = 0
        for r in rows:
            if uid not in (r["player1_id"], r["player2_id"]):
                continue
            if r["winner_id"] is None:
                draw += 1
            elif r["winner_id"] == uid:
                win += 1
            else:
                lose += 1
        win_rate = round((win / (win + lose) * 100.0), 2) if (win + lose) else 0.0
        ranking.append({"user_id": uid, "name": u["name"], "win": win, "lose": lose, "draw": draw, "total": win + lose + draw, "win_rate": win_rate})
    ranking.sort(key=lambda x: (x["win_rate"], x["win"], -x["lose"]), reverse=True)
    return jsonify(ok=True, items=ranking[:limit])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True)
