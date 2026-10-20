import pytest

from mtl_analyst.evals import find_evals_root, load_cases, run_suite
from mtl_analyst.fakes import ScriptedChatClient
from mtl_analyst.orchestrator import Orchestrator
from mtl_analyst.runtime import RunBudget

CASES = load_cases(find_evals_root() / "cases.json")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_case_passes_every_check(case, tmp_path):
    report = await run_suite(
        [case],
        lambda store, budget: Orchestrator(ScriptedChatClient(), store, budget=budget),
        "fake",
        "scripted-fake",
        tmp_path,
        RunBudget(),
    )

    failed = [f"{c.name}: {c.detail}" for c in report.cases[0].checks if not c.passed]
    assert not failed, "\n".join(failed)
