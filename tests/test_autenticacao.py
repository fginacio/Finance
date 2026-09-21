"""Login, sessão, bloqueio por tentativas e proteção global das rotas.

Baseado no roteiro manual usado para validar a autenticação (2026-09-18); portado para
pytest + TestClient para poder rodar a cada mudança, sem precisar subir um servidor à parte.
"""
import hashlib

from conftest import criar_usuario

SENHA_F = "Frase do primeiro usuário 2026"
SENHA_A = "Senha do segundo usuário 77!"


def test_app_fechado_sem_usuarios(app_cliente):
    r = app_cliente.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"

    r = app_cliente.post("/lancamentos/salvar", data={"data": "2026-03-01", "categoria_id": "1",
                          "forma_pagamento": "PIX", "valor": "10", "tipo": "Variável", "status": "Pago"})
    assert r.status_code == 303 and r.headers["location"] == "/login"

    r = app_cliente.get("/login")
    assert r.status_code == 200 and "Nenhum usuário cadastrado" in r.text

    r = app_cliente.post("/login", data={"usuario": "qualquer", "senha": "qualquer coisa"})
    assert r.status_code == 401


def test_docs_desligados(app_cliente):
    for caminho in ("/docs", "/redoc", "/openapi.json"):
        assert app_cliente.get(caminho).status_code == 404


def test_todas_as_rotas_exigem_login(app_cliente, db_path):
    import re
    from starlette.routing import Mount
    import app.main as main

    livres = {"/login"}
    nao_protegidas = []
    for rota in main.app.routes:
        caminho = getattr(rota, "path", "")
        if isinstance(rota, Mount) or caminho in livres or not caminho:
            continue
        for metodo in (getattr(rota, "methods", None) or {"GET"}):
            if metodo in ("HEAD", "OPTIONS"):
                continue
            alvo = re.sub(r"\{[^}]+\}", "1", caminho)
            r = app_cliente.request(metodo, alvo, data={} if metodo != "GET" else None)
            destino = r.headers.get("location") or r.headers.get("hx-redirect") or "/login"
            if not (r.status_code in (303, 401) and "/login" in destino):
                nao_protegidas.append((metodo, caminho, r.status_code))
    assert nao_protegidas == []


def test_login_senha_errada_nao_revela_se_usuario_existe(app_cliente, db_path):
    criar_usuario(db_path, "joao", SENHA_F, "João Silva")

    r1 = app_cliente.post("/login", data={"usuario": "joao", "senha": "errada errada"})
    r2 = app_cliente.post("/login", data={"usuario": "naoexiste", "senha": "errada errada"})
    assert r1.status_code == r2.status_code == 401
    assert "Usuário ou senha incorretos." in r1.text
    assert "Usuário ou senha incorretos." in r2.text
    assert "cg_sessao" not in r1.cookies


def test_login_correto_cookie_seguro_e_sessao(app_cliente, db_path):
    criar_usuario(db_path, "joao", SENHA_F, "João Silva")

    r = app_cliente.post("/login", data={"usuario": "joao", "senha": SENHA_F})
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.cookies.get("cg_sessao")
    assert cookie

    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "max-age" not in set_cookie

    r = app_cliente.get("/")
    assert r.status_code == 200 and "Painel do mês" in r.text
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("x-frame-options") == "DENY"

    import sqlite3
    con = sqlite3.connect(db_path)
    token_hash = hashlib.sha256(cookie.encode()).hexdigest()
    assert con.execute("SELECT COUNT(*) FROM sessoes WHERE token_hash = ?", (token_hash,)).fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM sessoes WHERE token_hash = ?", (cookie,)).fetchone()[0] == 0


def test_logout_invalida_sessao(app_cliente, db_path):
    criar_usuario(db_path, "joao", SENHA_F, "João Silva")
    app_cliente.post("/login", data={"usuario": "joao", "senha": SENHA_F})

    r = app_cliente.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert not app_cliente.cookies.get("cg_sessao")


def test_bloqueio_apos_5_tentativas(app_cliente, db_path):
    criar_usuario(db_path, "maria", SENHA_A, "Maria Souza")

    for i in range(5):
        app_cliente.post("/login", data={"usuario": "maria", "senha": f"tentativa errada {i}"})
    r = app_cliente.post("/login", data={"usuario": "maria", "senha": SENHA_A})
    assert r.status_code == 429 and "Muitas tentativas" in r.text


def test_post_de_outra_origem_e_recusado(app_cliente, db_path):
    criar_usuario(db_path, "joao", SENHA_F, "João Silva")
    app_cliente.post("/login", data={"usuario": "joao", "senha": SENHA_F})

    campos = {"data": "2026-03-01", "categoria_id": "1", "forma_pagamento": "PIX",
              "valor": "10", "tipo": "Variável", "status": "Pago"}
    r = app_cliente.post("/lancamentos/salvar", data=campos, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
