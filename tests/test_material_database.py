import pytest
from src.materials.database import MaterialDatabase

@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    MaterialDatabase.seed(path)
    return MaterialDatabase(path)

def test_search_returns_results(db):
    results = db.search("steel")
    assert len(results) > 0

def test_search_case_insensitive(db):
    assert len(db.search("Aluminum")) > 0

def test_get_by_id_returns_material(db):
    m = db.get_by_id(db.search("structural steel")[0]["id"])
    assert "E_GPa" in m and m["E_GPa"] > 0

def test_get_by_id_missing_returns_none(db):
    assert db.get_by_id(99999) is None

def test_all_materials_have_required_fields(db):
    for m in db.search(""):
        assert m["nu"] > 0 and m["rho_kgm3"] > 0
