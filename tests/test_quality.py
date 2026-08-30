from __future__ import annotations

from soma_data.quality import TOKEN_RE, assert_no_hf_token_in_tree


def test_token_regex_does_not_match_placeholder():
    # .env.example uses hf_your_token_here (15 chars after prefix); scanner wants 20+.
    assert not TOKEN_RE.search("hf_your_token_here")
    assert TOKEN_RE.search("hf_" + ("a" * 20))
    assert not TOKEN_RE.search("not-a-token")


def test_repo_has_no_live_token():
    assert_no_hf_token_in_tree()
