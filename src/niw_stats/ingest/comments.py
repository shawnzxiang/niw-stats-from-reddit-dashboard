"""Fetch the original poster's (OP's) own comments on a post, for the classifier.

OPs often reveal the key details (field, premium vs regular, RFE, citation counts) only in
replies — not the post body — so we feed those comments to the LLM alongside the post.
When the OP reply answers another comment, include that parent comment so a bare answer like
"91" keeps the question it answered.
"""

from __future__ import annotations

from collections.abc import Callable

from niw_stats.config import Settings
from niw_stats.ingest.arctic_client import ArcticClient

_SKIP = {"[removed]", "[deleted]", ""}


def _body(comment: dict) -> str:
    return (comment.get("body") or "").strip()


def _comment_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("_", 1)[1] if "_" in value else value


def _format_op_comment(comment: dict, by_id: dict[str, dict], post_id: str) -> str | None:
    body = _body(comment)
    if body in _SKIP:
        return None

    parent_id = _comment_id(comment.get("parent_id"))
    parent = by_id.get(parent_id or "")
    parent_body = _body(parent or {})
    if parent_id and parent_id != post_id and parent_body not in _SKIP:
        parent_author = (parent or {}).get("author") or "commenter"
        return f"Parent comment ({parent_author}): {parent_body}\nOP reply: {body}"
    return f"OP comment: {body}"


def make_op_comment_enricher(client: ArcticClient, settings: Settings) -> Callable[[object], str]:
    """Return ``enrich(row) -> str`` — OP comments with parent context when available."""
    max_chars = settings.op_comments_max_chars

    def enrich(row) -> str:
        post_id, author = row["id"], row["author"]
        if not author:
            return ""
        try:
            # Fetch all comments so parent comments are available for OP replies.
            comments = client.fetch_comments(link_id=post_id, limit=100)
        except Exception:
            return ""  # never let a comment-fetch failure block classification
        by_id = {
            str(c.get("id")): c for c in comments
            if c.get("id") is not None
        }
        bodies = [
            formatted for c in comments
            if c.get("author") == author
            for formatted in [_format_op_comment(c, by_id, post_id)]
            if formatted is not None
        ]
        return "\n---\n".join(bodies)[:max_chars]

    return enrich
