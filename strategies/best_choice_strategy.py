import random


def choose(context):
    """Use the best historical choice when available, otherwise random."""
    analysis = context.get("analysis") or {}
    best_choice = analysis.get("best_choice")
    if best_choice in context["choices"]:
        return best_choice
    return random.choice(context["choices"])
