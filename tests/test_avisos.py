"""Alertas derivados dos eventos de lançamento: orçamento estourado, gasto alto, lembrete de vencimento."""
from datetime import date, timedelta

from app import avisos, lembretes


def _cat(db, nome, orcamento_mensal=0.0):
    db.execute("INSERT INTO categorias (nome, grupo, orcamento_mensal, ativa) VALUES (?, 'Casa', ?, 1)", (nome, orcamento_mensal))
    db.commit()


def _gasto_ja_existente(db, categoria, data, valor):
    """Um gasto validado que já está no banco (não passa pelos triggers de evento, só serve de base pro total)."""
    cat_id = db.execute("SELECT id FROM categorias WHERE nome = ?", (categoria,)).fetchone()["id"]
    db.execute("""INSERT INTO lancamentos (data, categoria_id, forma_pagamento, valor, tipo, status)
                  VALUES (?, ?, 'PIX', ?, 'Variável', 'Pago')""", (data, cat_id, valor))
    db.commit()


def _evento(tipo, data, valor, categoria, valor_antes=None, descricao=None):
    return {"tipo": tipo, "data": data, "valor": valor, "valor_antes": valor_antes, "categoria": categoria, "descricao": descricao}


def test_alerta_orcamento_so_dispara_ao_cruzar_a_linha(db):
    _cat(db, "Teste Mercado", orcamento_mensal=200)
    _gasto_ja_existente(db, "Teste Mercado", "2026-09-05", 150)  # já gastou 150 de 200
    _gasto_ja_existente(db, "Teste Mercado", "2026-09-10", 30)  # o lançamento do evento (o trigger já o gravou)

    # 30 não estoura (total vira 180)
    sem_estouro = avisos.alertas_orcamento(db, [_evento("novo", "2026-09-10", 30, "Teste Mercado")])
    assert sem_estouro == []


def test_alerta_orcamento_dispara_quando_passa(db):
    _cat(db, "Teste Mercado", orcamento_mensal=200)
    _gasto_ja_existente(db, "Teste Mercado", "2026-09-05", 150)
    _gasto_ja_existente(db, "Teste Mercado", "2026-09-10", 80)  # o lançamento do evento (o trigger já o gravou)

    # este lançamento de 80 estoura (total vira 230)
    alerta = avisos.alertas_orcamento(db, [_evento("novo", "2026-09-10", 80, "Teste Mercado")])
    assert len(alerta) == 1
    assert "Teste Mercado" in alerta[0] and "230,00" in alerta[0] and "200,00" in alerta[0]


def test_alerta_orcamento_categoria_sem_orcamento_nao_dispara(db):
    _cat(db, "Lazer", orcamento_mensal=0)
    alerta = avisos.alertas_orcamento(db, [_evento("novo", "2026-09-10", 999, "Lazer")])
    assert alerta == []


def test_alerta_gasto_alto(db):
    eventos = [_evento("novo", "2026-09-10", 800, "Viagem", descricao="Passagem")]
    assert avisos.alertas_gasto_alto(eventos, 500) == ["💰 Gasto alto: R$ 800,00 em Viagem (Passagem)."]
    assert avisos.alertas_gasto_alto(eventos, 1000) == []
    assert avisos.alertas_gasto_alto(eventos, 0) == []  # limiar 0 desliga


def test_alerta_gasto_alto_so_para_lancamento_novo(db):
    editado = [_evento("editado", "2026-09-10", 800, "Viagem", valor_antes=700)]
    assert avisos.alertas_gasto_alto(editado, 500) == []


def test_lembrete_so_avisa_nos_dias_certos():
    hoje = date(2026, 9, 21)

    def linha(dias):
        return {"data": str(hoje + timedelta(days=dias)), "valor": 100, "categoria": "Cat", "descricao": f"d{dias}"}

    pendentes = [linha(d) for d in (5, 3, 2, 1, 0, -1, -10)]
    texto = lembretes.montar_mensagem(pendentes, hoje)
    assert "d5" not in texto and "d2" not in texto  # fora da janela de aviso
    for esperado in ("d3", "d1", "d0", "d-1", "d-10"):
        assert esperado in texto


def test_lembrete_sem_pendentes_nao_manda_nada():
    assert lembretes.montar_mensagem([], date(2026, 9, 21)) is None
