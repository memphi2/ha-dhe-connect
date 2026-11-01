"""Coverage gates must fail closed for tests and both measurement scopes."""

from unittest.mock import patch

import pytest

from scripts import check_coverage


@pytest.mark.parametrize("results,expected", [([1], 1), ([0, 1, 0], 1), ([0, 0, 1], 1), ([0, 0, 0], 0)])
def test_coverage_gates(results, expected):
    with patch.object(check_coverage, "_run", side_effect=results) as run:
        assert check_coverage.main() == expected
    assert run.call_count == len(results)
    if len(results) == 3:
        full = run.call_args_list[1].args[0]
        scoped = run.call_args_list[2].args[0]
        assert "--fail-under=85" in full
        assert not any(arg.startswith("--omit") for arg in full)
        assert "--fail-under=95" in scoped
        assert any(arg.startswith("--omit=") for arg in scoped)
