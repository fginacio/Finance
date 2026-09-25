"""Leitura da linha digitável de boleto/conta de consumo a partir de "Novo lançamento"."""
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pypdf import PdfReader

from app.boleto import extrair_linha_de_texto, parse_linha_digitavel
from app.database import get_db
from app.templating import templates

router = APIRouter(prefix="/lancamentos/boleto")

MAX_BYTES_PDF = 15_000_000


def _tela(request: Request, db, r: dict):
    from app.main import _opcoes  # import tardio: main importa este módulo

    l = {"id": None, "data": r["vencimento"] or date.today().isoformat(),
         "valor": r["valor"] if r["valor"] is not None else "",
         "descricao": "", "observacoes": ""}
    erro = None
    if r["erro"]:
        erro = r["erro"]
    elif r["avisos"]:
        erro = " ".join(r["avisos"]) + (" Confira o valor antes de salvar." if r["valor"] is not None else "")
    return templates.TemplateResponse(request, "lancamento_form.html",
                                      {"l": l, "hoje": date.today().isoformat(), "erro": erro, **_opcoes(db)})


@router.post("")
def ler_boleto(request: Request, db=Depends(get_db), linha: str = Form("")):
    """Recebe a linha digitável colada (ou já lida da foto no navegador) e abre o formulário de lançamento
    já preenchido; nada é gravado ainda."""
    return _tela(request, db, parse_linha_digitavel(linha))


@router.post("/arquivo")
def ler_boleto_pdf(request: Request, db=Depends(get_db), arquivo: UploadFile = File(None)):
    """Recebe o PDF do boleto/conta e procura a linha digitável no texto do documento (não decodifica
    o código de barras: a maioria dos boletos em PDF traz a linha digitável como texto selecionável)."""
    dados = arquivo.file.read(MAX_BYTES_PDF + 1) if arquivo else b""
    if not dados:
        return _tela(request, db, {"tipo": None, "valor": None, "vencimento": None, "avisos": [],
                                    "erro": "Nenhum arquivo recebido."})
    if len(dados) > MAX_BYTES_PDF:
        return _tela(request, db, {"tipo": None, "valor": None, "vencimento": None, "avisos": [],
                                    "erro": "Arquivo grande demais."})
    try:
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(dados)).pages)
    except Exception:  # PDF corrompido/protegido/formato inesperado: melhor esforço, trata como "não achou"
        texto = ""
    linha = extrair_linha_de_texto(texto)
    if not linha:
        return _tela(request, db, {"tipo": None, "valor": None, "vencimento": None, "avisos": [],
                                    "erro": "Não encontrei uma linha digitável dentro desse PDF (talvez seja só uma "
                                            "imagem escaneada); tente colar os números manualmente ou enviar uma foto do código de barras."})
    return _tela(request, db, parse_linha_digitavel(linha))
