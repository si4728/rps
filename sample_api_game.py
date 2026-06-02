from __future__ import annotations

import argparse
import json
import random

from api_client import CHOICES, RpsApiClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal RPS API game sample")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--name", default="SampleBot")
    parser.add_argument("--coupon-id", default=None)
    parser.add_argument("--choice", choices=CHOICES, default=None)
    parser.add_argument("--wait", type=float, default=60.0)
    args = parser.parse_args()

    client = RpsApiClient(args.base_url, args.coupon_id)
    if not client.coupon_id:
        player = client.create_player(args.name)
        print("created player:", json.dumps(player["user"], ensure_ascii=False))
    else:
        print("using coupon_id:", client.coupon_id)

    joined = client.join_match()
    print("join:", json.dumps(joined, ensure_ascii=False))

    game_id = joined.get("game_id")
    if not game_id:
        print("waiting for opponent...")
        game_id = client.wait_for_game(max_wait=args.wait)
    print("game_id:", game_id)

    before = client.game_result(game_id)
    previous_round_count = len(before.get("rounds") or [])
    choice = args.choice or random.choice(CHOICES)
    submitted = client.submit_choice(choice)
    print("choice:", choice, json.dumps(submitted, ensure_ascii=False))

    result = client.wait_for_next_result(game_id, previous_round_count, max_wait=args.wait)
    latest = result["latest_result"]
    print("result:", json.dumps({
        "game_id": result["game_id"],
        "player_result": latest["player_result"],
        "p1_choice": latest["p1_choice"],
        "p2_choice": latest["p2_choice"],
        "winner_id": latest["winner_id"],
    }, ensure_ascii=False))

    analysis = client.analysis()["analysis"]
    print("analysis:", json.dumps({
        "summary": analysis["summary"],
        "favorite_choice": analysis["favorite_choice"],
        "best_choice": analysis["best_choice"],
        "weakest_choice": analysis["weakest_choice"],
    }, ensure_ascii=False))

    ended = client.end_match()
    print("end:", json.dumps(ended, ensure_ascii=False))


if __name__ == "__main__":
    main()
