import random


BEATS = {
    "rock": "paper",
    "paper": "scissors",
    "scissors": "rock",
}


def choose(context):
    """
    Look at recent rounds against the last opponent.
    If the opponent has a frequent recent choice, play the counter.
    """
    saved = context.get("saved") or {}
    last_opponent_id = saved.get("last_opponent_user_id")
    analysis = context.get("analysis") or {}
    recent_rounds = analysis.get("recent_rounds") or []

    counts = {"rock": 0, "paper": 0, "scissors": 0}
    for item in recent_rounds:
        if last_opponent_id and item.get("opponent_id") != last_opponent_id:
            continue
        opp_choice = item.get("opp_choice")
        if opp_choice in counts:
            counts[opp_choice] += 1

    if max(counts.values()) == 0:
        return random.choice(context["choices"])

    predicted = max(counts, key=counts.get)
    return BEATS[predicted]
