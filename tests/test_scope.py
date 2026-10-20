import pytest

from mtl_analyst.scope import Scope, ScopeError


def test_city_scope_has_no_borough():
    assert Scope().borough is None
    assert Scope().label == "city"


@pytest.mark.parametrize("bad", ["", " ", "x' or 1=1 --", "Plateau; drop table trips"])
def test_malformed_borough_is_refused(bad):
    with pytest.raises(ScopeError):
        Scope(bad)


def test_real_borough_names_pass():
    Scope("Le Plateau-Mont-Royal")
    Scope("Villeray—Saint-Michel—Parc-Extension")
    Scope("Côte-des-Neiges - Notre-Dame-de-Grâce")
