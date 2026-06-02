from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


CHOICES = ("rock", "paper", "scissors")


class RpsApiError(RuntimeError):
    pass


class RpsApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", coupon_id: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.coupon_id = coupon_id
        self.timeout = timeout

    def _url(self, path: str, query: dict | None = None) -> str:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def request(self, method: str, path: str, payload: dict | None = None, query: dict | None = None) -> dict:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.coupon_id:
            headers["X-Coupon-ID"] = self.coupon_id

        req = urllib.request.Request(self._url(path, query), data=body, headers=headers, method=method)
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
        data = self.request("POST", "/api/players", {"name": name})
        self.coupon_id = data["coupon_id"]
        return data

    def me(self) -> dict:
        return self.request("GET", "/api/me")

    def join_match(self, preferred_opponent_id: int | None = None) -> dict:
        payload = {}
        if preferred_opponent_id:
            payload["preferred_opponent_id"] = preferred_opponent_id
        return self.request("POST", "/api/match/join", payload)

    def state(self) -> dict:
        return self.request("GET", "/api/state")

    def submit_choice(self, choice: str) -> dict:
        if choice not in CHOICES:
            raise ValueError(f"choice must be one of: {', '.join(CHOICES)}")
        return self.request("POST", "/api/match/choice", {"choice": choice})

    def game_result(self, game_id: str) -> dict:
        safe_game_id = urllib.parse.quote(str(game_id), safe="")
        return self.request("GET", f"/api/games/{safe_game_id}/result")

    def analysis(self) -> dict:
        return self.request("GET", "/api/analysis")

    def end_match(self) -> dict:
        return self.request("POST", "/api/match/end", {})

    def wait_for_game(self, poll_interval: float = 1.0, max_wait: float = 60.0) -> str:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            state = self.state()
            match = state.get("match")
            if match and match.get("game_id"):
                return str(match["game_id"])
            time.sleep(poll_interval)
        raise TimeoutError("match was not created before timeout")

    def wait_for_next_result(
        self,
        game_id: str,
        previous_round_count: int,
        poll_interval: float = 1.0,
        max_wait: float = 30.0,
    ) -> dict:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            result = self.game_result(game_id)
            if len(result.get("rounds") or []) > previous_round_count:
                return result
            time.sleep(poll_interval)
        raise TimeoutError("next game result was not created before timeout")
