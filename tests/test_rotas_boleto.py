"""Upload de arquivo em /lancamentos/boleto/arquivo: extração da linha digitável do texto de um PDF."""
from tests.conftest import criar_usuario


def _pdf_com_texto(texto: str) -> bytes:
    """Monta um PDF mínimo e válido (sem depender de reportlab) com uma única linha de texto na página."""
    conteudo = f"BT /F1 12 Tf 10 50 Td ({texto}) Tj ET".encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 400 100] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(conteudo), conteudo),
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


def _logar(cliente, db_path):
    criar_usuario(db_path, "boleto_teste", "SenhaForte123!")
    cliente.post("/login", data={"usuario": "boleto_teste", "senha": "SenhaForte123!"})


def test_upload_de_pdf_extrai_valor(app_cliente, db_path):
    _logar(app_cliente, db_path)
    pdf = _pdf_com_texto("83620000001 3 49920221202 7 61014000000 7 00008588439 3")
    r = app_cliente.post("/lancamentos/boleto/arquivo", files={"arquivo": ("conta.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    assert "149,92" in r.text


def test_upload_de_pdf_sem_linha_digitavel_avisa(app_cliente, db_path):
    _logar(app_cliente, db_path)
    pdf = _pdf_com_texto("nada de util aqui")
    r = app_cliente.post("/lancamentos/boleto/arquivo", files={"arquivo": ("conta.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    assert "Não encontrei uma linha digit" in r.text


def test_colar_linha_abre_formulario_preenchido(app_cliente, db_path):
    _logar(app_cliente, db_path)
    r = app_cliente.post("/lancamentos/boleto", data={"linha": "83620000001 3 49920221202 7 61014000000 7 00008588439 3"})
    assert r.status_code == 200
    assert "149,92" in r.text
