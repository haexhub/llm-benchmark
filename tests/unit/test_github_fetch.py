from __future__ import annotations

import subprocess
from unittest.mock import patch

from benchmark.github.fetch import fetch_diff_for_refs


def test_fetches_a_diff_for_explicit_immutable_refs() -> None:
    with patch(
        "benchmark.github.fetch.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="immutable diff", stderr=""),
    ) as run:
        diff = fetch_diff_for_refs("alice", "repo", "a" * 40, "b" * 40)

    assert diff == "immutable diff"
    assert "compare/" + "a" * 40 + "..." + "b" * 40 in run.call_args.args[0][-1]
