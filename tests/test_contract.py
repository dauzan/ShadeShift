"""CONTRACT.md and the code must agree (CONTRACT: "If code and contract disagree, fix one of them in the same commit")."""
import re
import sqlite3

from conftest import ROOT
from shadeshift.server import db

CONTRACT = (ROOT / "CONTRACT.md").read_text(encoding="utf-8")


def _shape(sql):
    con = sqlite3.connect(":memory:")
    con.executescript(sql)
    tables = {}
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        tables[name] = [(c[1], c[2].upper(), c[3], c[5]) for c in con.execute(f"PRAGMA table_info({name})")]
    indexes = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"))
    return tables, indexes


def test_database_schema_matches_contract():
    contract_sql = re.search(r"## 10\. Database.*?```sql\n(.*?)```", CONTRACT, re.S).group(1)
    assert _shape(contract_sql) == _shape(db.SCHEMA_V1)


def test_every_documented_env_var_is_read_by_config():
    documented = set(re.findall(r"^\| `(SHADESHIFT_[A-Z_]+)`", CONTRACT, re.M))
    source = (ROOT / "shadeshift" / "config.py").read_text(encoding="utf-8")
    assert len(documented) >= 18
    assert {v for v in documented if v not in source} == set()
    assert set(re.findall(r'(?:get|number)\("(SHADESHIFT_[A-Z_]+)"', source)) == documented
