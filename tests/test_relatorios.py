"""Lógica de app/relatorios.py: período configurável, linhas zeradas somem,
e os cards/percentuais usam o mês certo (não o período inteiro).
"""
from datetime import date

from app.relatorios import dados_relatorios, meses_anteriores


def _cadastrar_categoria(db, nome, grupo="Casa", essencial=1, orcamento_mensal=0.0):
    db.execute("INSERT INTO categorias (nome, grupo, essencial, orcamento_mensal, ativa) VALUES (?, ?, ?, ?, 1)",
               (nome, grupo, essencial, orcamento_mensal))
    db.commit()
    return db.execute("SELECT id FROM categorias WHERE nome = ?", (nome,)).fetchone()["id"]


def _lancar(db, data, categoria_id, valor, forma_pagamento="PIX"):
    db.execute("""INSERT INTO lancamentos (data, categoria_id, forma_pagamento, valor, tipo, status)
                  VALUES (?, ?, ?, ?, 'Variável', 'Pago')""", (data, categoria_id, forma_pagamento, valor))
    db.commit()


def test_meses_anteriores_termina_no_mes_informado():
    assert meses_anteriores("2026-09", 3) == ["2026-07", "2026-08", "2026-09"]
    assert meses_anteriores("2026-01", 3) == ["2025-11", "2025-12", "2026-01"]


def test_periodo_configuravel_muda_tamanho_das_tabelas(db):
    cat = _cadastrar_categoria(db, "Teste Mercado", orcamento_mensal=500)
    _lancar(db, "2026-09-10", cat, 300)

    r1 = dados_relatorios(db, "2026-09", n_meses=1)
    r3 = dados_relatorios(db, "2026-09", n_meses=3)
    assert r1["meses"] == ["2026-09"]
    assert r3["meses"] == ["2026-07", "2026-08", "2026-09"]


def test_linhas_zeradas_nao_aparecem(db):
    _cadastrar_categoria(db, "Teste Mercado", orcamento_mensal=500)
    com_gasto = _cadastrar_categoria(db, "Teste Luz", orcamento_mensal=100)
    _lancar(db, "2026-09-10", com_gasto, 90)

    r = dados_relatorios(db, "2026-09", n_meses=1)
    nomes = [l["nome"] for l in r["por_categoria"]]
    assert "Teste Luz" in nomes
    assert "Teste Mercado" not in nomes  # sem gasto no período: não aparece


def test_ratio_mensal_usa_orcamento_do_mes_nao_do_periodo(db):
    cat = _cadastrar_categoria(db, "Teste Luz", orcamento_mensal=100)
    _lancar(db, "2026-09-10", cat, 90)  # só o mês atual tem gasto

    r = dados_relatorios(db, "2026-09", n_meses=3)
    linha = next(l for l in r["por_categoria"] if l["nome"] == "Teste Luz")
    assert linha["orcado_mensal"] == 100
    assert linha["orcado"] == 300  # orçado do período de 3 meses (informativo)
    assert linha["valores"][-1] == 90  # gasto do mês selecionado


def test_cards_comparam_com_mes_anterior_mesmo_com_periodo_de_1_mes(db):
    cat = _cadastrar_categoria(db, "Teste Mercado", orcamento_mensal=500)
    _lancar(db, "2026-08-05", cat, 200)
    _lancar(db, "2026-09-05", cat, 300)

    r = dados_relatorios(db, "2026-09", n_meses=1)
    assert r["cards"]["total_mes"] == 300
    assert r["cards"]["variacao"] == 100
    assert round(r["cards"]["variacao_pct"], 1) == 50.0


def test_titular_filtrado_zera_orcamento(db):
    titular_id = db.execute("INSERT INTO titulares (nome) VALUES ('Maria')").lastrowid
    db.execute("INSERT INTO titulares (nome) VALUES ('João')")  # p/ o filtro ser parcial (nem todos selecionados)
    db.commit()
    cat = _cadastrar_categoria(db, "Teste Mercado", orcamento_mensal=500)
    _lancar(db, "2026-09-10", cat, 100)
    db.execute("UPDATE lancamentos SET titular_id = ? WHERE categoria_id = ?", (titular_id, cat))
    db.commit()

    r = dados_relatorios(db, "2026-09", titulares_sel=["Maria"], n_meses=1)
    assert r["filtrado"] is True
    linha = next(l for l in r["por_categoria"] if l["nome"] == "Teste Mercado")
    assert linha["orcado"] == 0  # orçamento é da família toda: não faz sentido no filtro
