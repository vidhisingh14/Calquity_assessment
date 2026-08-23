"""_tag_cited: which retrieved sources actually back the answer.

The bug this guards against: a vague question ("can I cancel order", no
order ID) can make search_documents retrieve up to RETRIEVAL_K chunks that
the model never draws on -- it may just ask a clarifying question. Showing
all of them as source cards regardless overstates what backs the answer.
"""

from __future__ import annotations

from app.services.chat import _tag_cited


def _source(doc_id: str) -> dict:
    return {"doc_id": doc_id, "tier": 3, "chunk_id": 1}


def test_uncited_clarifying_answer_marks_nothing_cited():
    """The exact case that motivated this: a clarifying question with no
    policy claim should cite nothing, even though chunks were retrieved."""
    sources = [_source("sop_v4"), _source("product_guide")]
    answer = "Could you please provide the Order ID so I can check its status?"
    tagged = _tag_cited(sources, answer, verdicts=[])
    assert all(s["cited"] is False for s in tagged)


def test_prose_mention_marks_cited():
    sources = [_source("sop_v4"), _source("product_guide")]
    answer = "Per `sop_v4`, no fee applies within the free window."
    tagged = _tag_cited(sources, answer, verdicts=[])
    by_doc = {s["doc_id"]: s["cited"] for s in tagged}
    assert by_doc["sop_v4"] is True
    assert by_doc["product_guide"] is False


def test_verdict_governing_source_counts_as_cited_even_without_prose_mention():
    """A computed number's actual source is structural, not just textual --
    the model might not spell out the literal doc_id string in prose even
    though the verdict genuinely came from that document."""
    sources = [_source("contract_northstar")]
    answer = "No cancellation fee applies to this shipment."
    verdicts = [{"governing_source": "contract_northstar", "outcome": "no_fee"}]
    tagged = _tag_cited(sources, answer, verdicts)
    assert tagged[0]["cited"] is True


def test_mutates_and_returns_the_same_list():
    """chat.py relies on this being usable as `_tag_cited(x, ...)` inline in
    the envelope dict, not requiring a separate reassignment."""
    sources = [_source("sop_v4")]
    result = _tag_cited(sources, "cites sop_v4 here", verdicts=[])
    assert result is sources
