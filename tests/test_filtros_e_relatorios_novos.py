"""Filtros do Painel (lembrados em cookie), relatório do vale e relatório Personalizado (montar e salvar)."""
import sqlite3

from starlette.datastructures import QueryParams

from app.filtros import Filtro
from tests.conftest import criar_usuario

SENHA = "senha-de-teste-123"


def _categoria(con, nome, grupo="Casa", essencial=1):
    con.execute("INSERT INTO categorias (nome, grupo, essencial, orcamento_mensal, ativa) VALUES (?, ?, ?, 0, 1)",
                (nome, grupo, essencial))
    return con.execute("SELECT id FROM categorias WHERE nome = ?", (nome,)).fetchone()[0]


def _lancar(con, data, categoria_id, valor, descricao=None, forma="PIX", titular_id=None):
    con.execute("""INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento, valor, tipo, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'Variável', 'Pago')""", (data, categoria_id, descricao, titular_id, forma, valor))


def _base(db_path):
    con = sqlite3.connect(db_path)
    mercado = _categoria(con, "Teste Mercado", "Alimentação")
    cinema = _categoria(con, "Teste Cinema", "Lazer", essencial=0)
    _lancar(con, "2026-09-05", mercado, 300, "Supermercado X")
    _lancar(con, "2026-09-06", cinema, 80, "Cinema Y", forma="Débito")
    _lancar(con, "2026-08-10", mercado, 200, "Supermercado X")
    con.commit()
    con.close()


def _logar(cliente, db_path):
    criar_usuario(db_path, "teste", SENHA)
    assert cliente.post("/login", data={"usuario": "teste", "senha": SENHA}).status_code == 303


# ---------------------------------------------------------------- Filtro (unidade)
def test_filtro_ida_e_volta_pela_query():
    f = Filtro({"grupo": {"Lazer"}, "forma": {"PIX", "Débito"}}, busca="uber")
    g = Filtro.da_query(QueryParams(f.para_query()).multi_items())
    assert g.excluidos == f.excluidos and g.busca == "uber" and g.ativo
    assert not Filtro().ativo


def test_formulario_vira_lista_de_excluidos():
    ops = {"grupo": ["Alimentação", "Lazer"], "forma": ["PIX", "Débito"]}
    f = Filtro.do_formulario([("com_grupo", "Alimentação"), ("com_forma", "PIX"), ("com_forma", "Débito")], ops)
    assert f.excluidos["grupo"] == {"Lazer"} and not f.excluidos["forma"]


def test_sql_do_filtro_so_tem_parametros(db):
    _categoria(db, "Teste Mercado", "Alimentação")
    _categoria(db, "Teste Cinema", "Lazer", essencial=0)
    cats = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM categorias")}
    _lancar(db, "2026-09-05", cats["Teste Mercado"], 300, "Supermercado")
    _lancar(db, "2026-09-06", cats["Teste Cinema"], 80, "Cinema'; DROP TABLE x;--")
    db.commit()

    def total(f):
        sql, params = f.sql()
        return db.execute(f"SELECT SUM(valor) FROM vw_lancamentos WHERE conta = 1 {sql}", params).fetchone()[0]

    assert total(Filtro()) == 380
    assert total(Filtro({"grupo": {"Lazer"}})) == 300
    assert total(Filtro({"essencial": {"Essencial"}})) == 80
    assert total(Filtro(busca="drop table")) == 80


# ---------------------------------------------------------------- Painel
def test_painel_aplica_e_lembra_o_filtro(app_cliente, db_path):
    _base(db_path)
    _logar(app_cliente, db_path)

    r = app_cliente.get("/?mes=2026-09")
    assert r.status_code == 200 and "R$ 380,00" in r.text and "Filtro ativo" not in r.text

    # o formulário manda tudo marcado, menos o grupo Lazer e as categorias dele
    from app import filtros
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ops = filtros.opcoes(con)
    con.close()
    marcados = [(f"com_{d}", v) for d in filtros.DIMENSOES for v in ops[d]
                if not (d == "grupo" and v == "Lazer") and not (d == "categoria" and v in ops["categorias_por_grupo"]["Lazer"])]
    r = app_cliente.get("/", params=[("mes", "2026-09"), ("filtrar", "1")] + marcados)
    assert r.status_code == 200 and "Filtro ativo" in r.text and "R$ 300,00" in r.text

    # visita seguinte, sem parâmetros: o cookie traz o filtro de volta
    r = app_cliente.get("/?mes=2026-09")
    assert "Filtro ativo" in r.text

    r = app_cliente.get("/?mes=2026-09&limpar=1")
    assert "Filtro ativo" not in r.text
    assert "Filtro ativo" not in app_cliente.get("/?mes=2026-09").text


# ---------------------------------------------------------------- Vale
def test_relatorio_vale_saldo_mes_a_mes(app_cliente, db_path):
    _base(db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO titulares (nome) VALUES ('Fulano de Tal')")
    tid = con.execute("SELECT id FROM titulares WHERE nome = 'Fulano de Tal'").fetchone()[0]
    con.execute("""INSERT INTO beneficios (titular_id, nome, valor_mensal, dia_recarga, inicio, saldo_inicial)
                   VALUES (?, 'VR Teste', 1000, 1, '2026-08-01', 0)""", (tid,))
    bid = con.execute("SELECT id FROM beneficios").fetchone()[0]
    cat = con.execute("SELECT id FROM categorias WHERE nome = 'Teste Mercado'").fetchone()[0]
    con.execute("INSERT INTO beneficio_usos (beneficio_id, data, valor, descricao, categoria_id) VALUES (?, '2026-08-15', 400, 'Padaria', ?)", (bid, cat))
    con.execute("INSERT INTO beneficio_usos (beneficio_id, data, valor, descricao) VALUES (?, '2026-09-15', 250, 'Restaurante')", (bid,))
    con.commit()
    con.close()

    from app.relatorio_vale import dados_vale
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    v = dados_vale(db, "2026-09", 2)
    db.close()
    assert [t["usado"] for t in v["totais"]] == [400, 250]
    assert [t["restante"] for t in v["totais"]] == [600, 1350]  # 1000 - 400; 600 + 1000 - 250
    assert {l["nome"]: l["total"] for l in v["por_categoria"]} == {"Teste Mercado": 400, "Sem categoria": 250}
    assert len(v["usos"]) == 2

    _logar(app_cliente, db_path)
    r = app_cliente.get("/relatorios?aba=vale&mes=2026-09&meses=3")
    assert r.status_code == 200 and "Saldo mês a mês" in r.text and "Restaurante" in r.text


# ---------------------------------------------------------------- Personalizado
def test_personalizado_agrupa_filtra_e_salva(app_cliente, db_path):
    _base(db_path)
    _logar(app_cliente, db_path)

    r = app_cliente.get("/relatorios?aba=personalizado&agrupar=forma_pagamento_invalido&de=2026-08&ate=2026-09")
    assert r.status_code == 200  # agrupamento inválido cai no padrão (categoria)

    r = app_cliente.get("/relatorios?aba=personalizado&agrupar=descricao&de=2026-08&ate=2026-09&sem_grupo=Lazer")
    assert r.status_code == 200 and "Supermercado X" in r.text and "Cinema Y" not in r.text and "R$ 500,00" in r.text

    params = "agrupar=grupo&ultimos=6&colunas=total&grafico=pizza&limite=5&sem_forma=D%C3%A9bito"
    r = app_cliente.post("/relatorios/salvos", data={"nome": "Sem débito", "params": params})
    assert r.status_code == 303 and "ultimos=6" in r.headers["location"]
    r = app_cliente.get("/relatorios?aba=personalizado")
    assert "Sem débito" in r.text

    # mesmo nome substitui
    app_cliente.post("/relatorios/salvos", data={"nome": "Sem débito", "params": "agrupar=titular"})
    con = sqlite3.connect(db_path)
    linhas = con.execute("SELECT id, params FROM relatorios_salvos").fetchall()
    assert len(linhas) == 1 and "agrupar=titular" in linhas[0][1]

    assert app_cliente.post(f"/relatorios/salvos/{linhas[0][0]}/excluir").status_code == 303
    assert con.execute("SELECT COUNT(*) FROM relatorios_salvos").fetchone()[0] == 0
    con.close()


def test_abas_antigas_continuam_funcionando(app_cliente, db_path):
    _base(db_path)
    _logar(app_cliente, db_path)
    for aba in ("resumo", "analise"):
        r = app_cliente.get(f"/relatorios?aba={aba}&mes=2026-09&meses=3")
        assert r.status_code == 200
