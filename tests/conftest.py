"""Fixtures compartilhadas: cada teste roda num banco SQLite novo, em arquivo temporário
(nunca no banco real). `DATABASE_PATH` precisa ser definida ANTES de importar app.database
ou qualquer módulo que dependa dele (o caminho é lido uma vez, na importação).
"""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.db"
    monkeypatch.setenv("DATABASE_PATH", str(caminho))
    # reimporta o módulo do banco apontando pro caminho novo (ele lê DATABASE_PATH só na importação)
    import importlib
    import app.database as database
    importlib.reload(database)
    database.init_db()
    return caminho


@pytest.fixture
def db(db_path):
    import app.database as database
    con = database.get_db()
    conexao = next(con)
    yield conexao
    try:
        next(con)
    except StopIteration:
        pass


@pytest.fixture
def app_cliente(db_path):
    """TestClient com o app apontando pro banco de teste (reimporta app.main após fixar DATABASE_PATH)."""
    import importlib
    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app, follow_redirects=False) as cliente:
        yield cliente


def criar_usuario(db_path, usuario: str, senha: str, nome: str | None = None, ativo: bool = True):
    """Cria um usuário direto no banco de teste (sem passar pelo terminal)."""
    import sqlite3
    from app.seguranca import hash_senha
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO usuarios (usuario, nome, senha_hash, ativo) VALUES (?, ?, ?, ?)",
                (usuario, nome or usuario, hash_senha(senha), 1 if ativo else 0))
    con.commit()
    con.close()
