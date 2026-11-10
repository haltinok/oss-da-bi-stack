"""The rule-based stand-in and the prompt's examples on the second model (models/distributor): what PLAN-decouple.md phase 4 has to make pass.

Each test is a strict xfail today: the composer knows only the AdventureWorks sales cubes. When phase 4 lands, the xfail marks fail ("unexpectedly passed") and must be removed.
"""
import pathlib

import pytest
from dashspec import catalog as cat
from dashspec.validate import validate

from builder import composer, core

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "models" / "distributor" / "cube")
PHASE_4 = pytest.mark.xfail(strict=True, reason="phase 4: the composer and the prompt's examples are written for the AdventureWorks sales cubes")


@PHASE_4
@pytest.mark.parametrize("prompt", ["revenue by month", "orders by region", "aylık ciro"])
def test_the_stand_in_builds_a_valid_dashboard_on_another_model(prompt):
    comp = composer.compose(prompt, CATALOG, "admin")
    assert comp.spec, comp.reason
    assert validate(comp.spec, CATALOG)[0] == []


@PHASE_4
def test_the_models_prompt_carries_a_valid_example_on_another_model():
    assert "panels:" in core.example_spec(CATALOG, "admin")
