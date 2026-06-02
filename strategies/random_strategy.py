import random


def choose(context):
    """Return one of: rock, paper, scissors."""
    return random.choice(context["choices"])
