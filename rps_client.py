from __future__ import annotations

import argparse
import importlib.util
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CHOICES = ("rock", "paper", "scissors")
DEFAULT_STATE_FILE = Path.home() / ".rps_client.json"


class RpsApiError(RuntimeError):
    pass


class RpsClient:
    def __init__(self, base_url: str, coupon_id: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.coupon_id = coupon_id
        self.timeout = timeout

    def _url(self, path: str, query: dict | None = None) -> str:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def _request(self, method: str, path: str, payload: dict | None = None, query: dict | None = None) -> dict:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.coupon_id:
            headers["X-Coupon-ID"] = self.coupon_id

        req = urllib.request.Request(
            self._url(path, query),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                data = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"ok": False, "error": raw or exc.reason}
            raise RpsApiError(f"{method} {path} failed: {data.get('error', exc.reason)}") from exc

        if data.get("ok") is False:
            raise RpsApiError(f"{method} {path} failed: {data.get('error', 'unknown_error')}")
        return data

    def create_player(self, name: str) -> dict:
        data = self._request("POST", "/api/players", {"name": name})
        self.coupon_id = data["coupon_id"]
        return data

    def me(self) -> dict:
        return self._request("GET", "/api/me")

    def join_match(self, preferred_opponent_id: int | None = None) -> dict:
        payload = {}
        if preferred_opponent_id:
            payload["preferred_opponent_id"] = preferred_opponent_id
        return self._request("POST", "/api/match/join", payload)

    def state(self) -> dict:
        return self._request("GET", "/api/state")

    def choose(self, choice: str) -> dict:
        if choice not in CHOICES:
            raise ValueError(f"choice must be one of: {', '.join(CHOICES)}")
        return self._request("POST", "/api/match/choice", {"choice": choice})

    def end_match(self) -> dict:
        return self._request("POST", "/api/match/end", {})

    def game_result(self, game_id: str) -> dict:
        safe_game_id = urllib.parse.quote(str(game_id), safe="")
        return self._request("GET", f"/api/games/{safe_game_id}/result")

    def last_opponent(self) -> dict:
        return self._request("GET", "/api/opponents/last")

    def analysis(self) -> dict:
        return self._request("GET", "/api/analysis")

    def wait_for_game(self, poll_interval: float = 1.0, max_wait: float = 60.0) -> str:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            state = self.state()
            match = state.get("match")
            if match and match.get("game_id"):
                return str(match["game_id"])
            time.sleep(poll_interval)
        raise TimeoutError("match was not created before timeout")

    def wait_for_latest_result(self, game_id: str, poll_interval: float = 1.0, max_wait: float = 30.0) -> dict:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            result = self.game_result(game_id)
            if result.get("latest_result"):
                return result
            time.sleep(poll_interval)
        raise TimeoutError("game result was not created before timeout")

    def wait_for_next_result(self, game_id: str, previous_round_count: int, poll_interval: float = 1.0, max_wait: float = 30.0) -> dict:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            result = self.game_result(game_id)
            if len(result.get("rounds") or []) > previous_round_count:
                return result
            time.sleep(poll_interval)
        raise TimeoutError("next game result was not created before timeout")


def load_saved_client(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_client_state(state_file: Path, data: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def default_state_file_for_profile(profile: str) -> Path:
    if profile == "default":
        return DEFAULT_STATE_FILE
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in profile.strip())
    safe = safe or "default"
    return Path.home() / f".rps_client_{safe}.json"


def load_strategy(strategy_path: str | None):
    if not strategy_path:
        return None
    path = Path(strategy_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"strategy file not found: {path}")
    spec = importlib.util.spec_from_file_location("rps_user_strategy", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load strategy file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    choose = getattr(module, "choose", None)
    if not callable(choose):
        raise RuntimeError(f"strategy file must define choose(context): {path}")
    return choose


def choose_with_strategy(strategy, context: dict) -> str:
    if not strategy:
        return random.choice(CHOICES)
    choice = strategy(context)
    if choice not in CHOICES:
        raise ValueError(f"strategy returned invalid choice: {choice!r}")
    return choice


def main() -> None:
    parser = argparse.ArgumentParser(description="RPS external API client example")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--name", default="ApiBot")
    parser.add_argument("--coupon-id", default=None)
    parser.add_argument("--choice", choices=CHOICES, default=None)
    parser.add_argument("--strategy-file", default=None, help="Path to a Python file defining choose(context)")
    parser.add_argument("--profile", default="default", help="Local saved client profile name for running multiple clients on one PC")
    parser.add_argument("--state-file", default=None)
    parser.add_argument("--reset-client", action="store_true")
    parser.add_argument("--wait-previous-opponent", action="store_true")
    parser.add_argument("--preferred-opponent-id", type=int, default=None)
    parser.add_argument("--keep-match", action="store_true")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds to play in the same game_id")
    parser.add_argument("--wait", type=float, default=60.0)
    args = parser.parse_args()
    strategy = load_strategy(args.strategy_file)

    state_file = Path(args.state_file).expanduser() if args.state_file else default_state_file_for_profile(args.profile)
    saved = {} if args.reset_client else load_saved_client(state_file)
    coupon_id = args.coupon_id or saved.get("client_id") or saved.get("coupon_id")
    player_name = saved.get("name") or args.name

    client = RpsClient(args.base_url, coupon_id)
    if not client.coupon_id:
        player = client.create_player(player_name)
        user = player["user"]
        save_client_state(state_file, {
            "base_url": args.base_url,
            "name": user["name"],
            "user_id": user["user_id"],
            "client_id": user["client_id"],
            "coupon_id": user["coupon_id"],
            "last_game_id": None,
        })
        print("created player:", json.dumps(player["user"], ensure_ascii=False))
    else:
        print("using saved client:", json.dumps({
            "name": player_name,
            "client_id": client.coupon_id,
            "state_file": str(state_file),
        }, ensure_ascii=False))

    preferred_opponent_id = args.preferred_opponent_id
    if args.wait_previous_opponent and not preferred_opponent_id:
        preferred_opponent_id = saved.get("last_opponent_user_id")
        if not preferred_opponent_id:
            last = client.last_opponent()
            opponent = last.get("opponent")
            preferred_opponent_id = opponent.get("user_id") if opponent else None
    if args.wait_previous_opponent and not preferred_opponent_id:
        raise SystemExit("No previous opponent is known yet.")

    joined = client.join_match(preferred_opponent_id)
    print("join:", json.dumps(joined, ensure_ascii=False))
    if preferred_opponent_id and not joined.get("game_id"):
        print("waiting for previous/preferred opponent:", preferred_opponent_id)

    game_id = joined.get("game_id")
    if not game_id:
        print("waiting for opponent...")
        try:
            game_id = client.wait_for_game(max_wait=args.wait)
        except TimeoutError as exc:
            state = client.state()
            if state.get("user", {}).get("status") == "queued" and state.get("match") is None:
                print("")
                print("No opponent joined before timeout.")
                print("If you are running two clients on the same PC, use a different profile for the second client:")
                print("  python rps_client.py --profile p2 --name ApiBot2")
                print("")
                print(f"Current profile state file: {state_file}")
            raise exc
    print("game_id:", game_id)

    rounds_to_play = max(1, args.rounds)
    result = client.game_result(str(game_id))
    previous_round_count = len(result.get("rounds") or [])
    latest = result.get("latest_result")
    me = client.me()["user"]

    for round_index in range(1, rounds_to_play + 1):
        context = {
            "client": client,
            "game_id": game_id,
            "round_index": round_index,
            "profile": args.profile,
            "state_file": str(state_file),
            "saved": load_saved_client(state_file),
            "me": client.me().get("user"),
            "state": client.state(),
            "analysis": client.analysis().get("analysis"),
            "choices": CHOICES,
        }
        choice = args.choice or choose_with_strategy(strategy, context)
        selected = client.choose(choice)
        print(f"round {round_index} choice:", choice, json.dumps(selected, ensure_ascii=False))

        result = client.wait_for_next_result(str(game_id), previous_round_count, max_wait=args.wait)
        previous_round_count = len(result.get("rounds") or [])
        latest = result["latest_result"]
        print(f"round {round_index} result:", json.dumps({
            "game_id": result["game_id"],
            "player_result": latest["player_result"],
            "p1_choice": latest["p1_choice"],
            "p2_choice": latest["p2_choice"],
            "winner_id": latest["winner_id"],
        }, ensure_ascii=False))

    players = result.get("players", {})
    p1 = players.get("p1", {})
    p2 = players.get("p2", {})
    opponent = p2 if p1.get("user_id") == me.get("user_id") else p1
    current_state = load_saved_client(state_file)
    current_state.update({
        "base_url": args.base_url,
        "name": me.get("name") or player_name,
        "user_id": me.get("user_id"),
        "client_id": client.coupon_id,
        "coupon_id": client.coupon_id,
        "last_game_id": result["game_id"],
        "last_result": latest["player_result"] if latest else None,
        "last_opponent_user_id": opponent.get("user_id"),
        "last_opponent_name": opponent.get("name"),
    })
    save_client_state(state_file, current_state)

    if not args.keep_match:
        ended = client.end_match()
        if ended.get("status") == "no_active_match":
            print("end: already ended by the other client")
        else:
            print("end:", json.dumps(ended, ensure_ascii=False))


if __name__ == "__main__":
    main()
