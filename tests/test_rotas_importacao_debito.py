"""Reconhecimento de 'débito automático' no texto da fatura (Revisar faturas) e efeito na gravação."""
from tests.conftest import criar_usuario


def _logar(cliente, db_path):
    criar_usuario(db_path, "fatura_teste", "SenhaForte123!")
    cliente.post("/login", data={"usuario": "fatura_teste", "senha": "SenhaForte123!"})


def _pdf_com_texto(texto: str) -> bytes:
    conteudo = texto.encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 400 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\nBT /F1 10 Tf 10 150 Td (%s) Tj ET\nendstream" % (len(conteudo) + 20, conteudo),
    ]
    partes = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objetos, start=1):
        offsets.append(sum(len(p) for p in partes))
        partes.append(b"%d 0 obj\n%s\nendobj\n" % (i, obj))
    xref_offset = sum(len(p) for p in partes)
    n = len(objetos) + 1
    xref = [b"xref\n%d %d\n" % (0, n), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(b"%010d 00000 n \n" % off)
    partes.extend(xref)
    partes.append(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (n, xref_offset))
    return b"".join(partes)


def test_fatura_com_debito_automatico_vem_com_checkbox_marcada(app_cliente, db_path):
    _logar(app_cliente, db_path)
    texto = "Id Deb Autom Consigaz Valor a Pagar R$ 149,92 Vencimento 14/10/2026"
    pdf = _pdf_com_texto(texto)
    r = app_cliente.post("/importar/faturas", files={"arquivos": ("conta.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    assert 'name="debito_automatico" value="1"' in r.text


def test_confirmar_com_debito_automatico_grava_forma_pagamento(app_cliente, db, db_path):
    _logar(app_cliente, db_path)
    db.execute("INSERT INTO categorias (nome, grupo) VALUES ('Gás teste', 'Moradia')")
    db.commit()
    cat_id = db.execute("SELECT id FROM categorias WHERE nome = 'Gás teste'").fetchone()["id"]

    r = app_cliente.post("/importar/faturas/confirmar", data={
        "arquivo": ["conta.pdf"], "acao": ["incluir"], "valor": ["149,92"],
        "data_pagamento": ["2026-10-14"], "vencimento": ["2026-10-14"], "referencia": ["2026-09"],
        "recorrente_id": [""], "categoria_id": [str(cat_id)], "status": ["Agendado"],
        "descricao": [""], "cartao_id": [""], "debito_automatico": ["1"],
    })
    assert r.status_code == 200
    lanc = db.execute("SELECT forma_pagamento, valor FROM lancamentos WHERE categoria_id = ?", (cat_id,)).fetchone()
    assert lanc["forma_pagamento"] == "Débito automático"
    assert lanc["valor"] == 149.92
