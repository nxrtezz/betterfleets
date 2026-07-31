import re

from .models import ReviewBlockedPhrase


NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_review_text(value):
    return NON_ALNUM_RE.sub("", (value or "").casefold())


def find_blocked_review_phrases(text):
    normalized_text = normalize_review_text(text)
    if not normalized_text:
        return []

    matches = []
    for blocked_phrase in ReviewBlockedPhrase.objects.filter(is_active=True).only(
        "phrase", "normalized_phrase"
    ):
        normalized_phrase = blocked_phrase.normalized_phrase or normalize_review_text(
            blocked_phrase.phrase
        )
        if normalized_phrase and normalized_phrase in normalized_text:
            matches.append(blocked_phrase.phrase)
    return matches
