from __future__ import annotations

import re

_STOP = {
    "a", "an", "the", "is", "to", "for", "of", "and", "or", "in", "on", "at",
    "can", "i", "my", "what", "how", "many", "do", "does", "be", "with",
    "please", "tell", "me", "about",
}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9$]+", text.lower())
    out: set[str] = set()
    for word in words:
        if word in _STOP or len(word) < 2:
            continue
        out.add(word)
        if len(word) > 3 and word.endswith("s"):
            out.add(word[:-1])
    return out


def units(system: str) -> list[str]:
    found: list[str] = []
    for line in system.splitlines():
        text = line.strip().lstrip("-*").strip()
        if len(text) > 8:
            found.append(text)
    return found or [p.strip() for p in re.split(r"[.\n]", system) if len(p.strip()) > 8]


def overlap(question: str, fact: str) -> int:
    q, f = tokens(question), tokens(fact)
    n = 0
    for a in q:
        for b in f:
            if a == b or (len(a) >= 4 and (a in b or b in a)):
                n += 1
                break
    return n


def answer(system: str, question: str) -> str:
    facts = units(system)
    ranked = sorted(((overlap(question, fact), fact) for fact in facts), reverse=True)
    picked = [fact for score, fact in ranked if score >= 2][:6]
    if not picked:
        picked = [fact for score, fact in ranked if score >= 1][:3]
    if not picked:
        return "I don't know."
    return " ".join(picked)
