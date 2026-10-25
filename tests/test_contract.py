"""CONTRACT.md and the code must agree (CONTRACT: "If code and contract disagree, fix one of them in the same commit")."""
import re
import sqlite3

import pytest
from conftest import ROOT
from shadeshift.server import db

CONTRACT = (ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8")


def _shape(con):
    tables = {}
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        tables[name] = [(c[1], c[2].upper(), c[3], c[5]) for c in con.execute(f"PRAGMA table_info({name})")]
    indexes = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"))
    return tables, indexes


def _ddl(con):
    """CREATE statements without comments, quotes and layout, so equal schemas compare equal (CHECKs included)."""
    out = {}
    for name, sql in con.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"):
        sql = re.sub(r"--[^\n]*", "", sql).replace('"', "")
        out[name] = re.sub(r"\s+", " ", re.sub(r"\s*([(),])\s*", r"\1", sql)).strip()
    return out


def test_database_schema_matches_contract(tmp_path):
    """The contract DDL is the schema after ALL migrations."""
    contract_sql = re.search(r"## 10\. Database.*?```sql\n(.*?)```", CONTRACT, re.S).group(1)
    contract = sqlite3.connect(":memory:")
    contract.executescript(contract_sql)
    store = db.Database(tmp_path / "s.db")
    assert store.migrate() == db.SCHEMA_VERSION == 5
    assert _shape(contract) == _shape(store.con)
    assert _ddl(contract) == _ddl(store.con)


def _insert_sweep(con, uuid, topology):
    con.execute("INSERT INTO sweeps(uuid,device_id,source,label,topology,captured_at,received_at,n_points,points_json)"
                " VALUES (?,'x','device','l',?,'t','t',1,'{}')", (uuid, topology))


def test_migration_2_keeps_rows_and_accepts_panels(tmp_path):
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript(db.SCHEMA_V1 + "PRAGMA user_version=1;")
    con.execute("INSERT INTO devices VALUES ('x','esp32',NULL,NULL,'t','t','{}')")
    _insert_sweep(con, "u1", "4S")
    con.execute("INSERT INTO decisions(uuid,sweep_id,device_id,decided_by,model_id,choice,scores_json,features_json,"
                "trigger,created_at) VALUES ('d1',1,'x','esp32','m','TCT','[]','[]','observe','t')")
    con.commit()
    con.close()
    store = db.Database(path)
    assert store.migrate() == 5
    c = store.con
    _insert_sweep(c, "u2", "A")
    assert [tuple(r) for r in c.execute("SELECT id, topology FROM sweeps ORDER BY id")] == [(1, "4S"), (2, "A")]
    assert c.execute("SELECT sweep_id FROM decisions").fetchone()[0] == 1
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        _insert_sweep(c, "u3", "E")
    assert store.migrate() == 5                      # a second start changes nothing


def test_every_documented_env_var_is_read_by_config():
    documented = set(re.findall(r"^\| `(SHADESHIFT_[A-Z_]+)`", CONTRACT, re.M))
    source = (ROOT / "shadeshift" / "config.py").read_text(encoding="utf-8")
    assert len(documented) >= 18
    assert {v for v in documented if v not in source} == set()
    assert set(re.findall(r'(?:get|number)\("(SHADESHIFT_[A-Z_]+)"', source)) == documented


def test_every_api_route_is_documented(tmp_path):
    from shadeshift import config
    from shadeshift.server.app import API, create_app
    app = create_app(config.load(env={"SHADESHIFT_DATA_DIR": str(tmp_path)}, env_file=tmp_path / "no.env"))
    doc = re.sub(r"\{[a-z_]+\}", "{id}", CONTRACT)
    paths = {re.sub(r"\{[a-z_]+\}", "{id}", r.path[len(API):]) for r in app.routes if getattr(r, "path", "").startswith(API)}
    assert len(paths) > 30
    assert {p for p in paths if f"`{p}" not in doc and f" {p}" not in doc} == set()
