"""
Leitura de extratos bancários e faturas (funções puras, sem banco de dados).

Extrato: OFX, CSV, XLSX ou PDF -> lista de saídas {data, descricao, valor, chave}.
Fatura (PDF): texto -> valor, vencimento, referência.
Os arquivos reais variam por banco/emissor; por isso tudo que é extraído passa por uma
tela de revisão antes de virar lançamento.
"""
import csv
import hashlib
import io
import re
import unicodedata
from datetime import date

# Limites contra arquivos maliciosos ou defeituosos: uma linha gigante (ex.: 200 mil dígitos) fazia a leitura de
# fatura levar ~50 s, porque as expressões regulares de valores testam cada posição da linha.
MAX_PAGINAS = 300
MAX_TEXTO = 3_000_000
MAX_LINHAS = 30_000
MAX_LINHA = 600

# ---------------------------------------------------------------- normalização
_STOP_PADRAO = {
    "PIX", "ENVIADO", "ENVIADA", "ENVIO", "RECEBIDO", "RECEBIDA", "TRANSF", "TRANSFERENCIA", "PAGAMENTO",
    "PAGTO", "PGTO", "PAG", "COMPRA", "COMPRAS", "DEBITO", "CARTAO", "DEB", "DE", "DA", "DO", "EM", "NO", "NA",
    "PARA", "COM", "TED", "DOC", "QRCODE", "QR", "CODE", "CHAVE", "LTDA", "SA", "ME",
}


def sem_acentos_upper(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def padrao(descricao: str) -> str:
    """Chave de aprendizado: só as palavras que identificam o favorecido/estabelecimento."""
    n = re.sub(r"[^A-Z0-9 ]", " ", sem_acentos_upper(descricao))
    palavras = [p for p in n.split() if not any(ch.isdigit() for ch in p) and p not in _STOP_PADRAO and len(p) > 1]
    return " ".join(palavras) or re.sub(r"\s+", " ", n).strip()


def limpar_descricao(descricao: str) -> str:
    return re.sub(r"\s+", " ", descricao or "").strip()


# ---------------------------------------------------------------- números e datas
_RE_VALOR = re.compile(r"\(?-?\s?(?:R\$\s?)?\d{1,3}(?:\.\d{3})*,\d{2}\)?|\(?-?\s?(?:R\$\s?)?\d+,\d{2}\)?")


def parse_valor_br(texto: str) -> float | None:
    """'R$ 1.234,56', '-1.234,56', '(123,45)', '1234.56' -> float (com sinal)."""
    if texto is None:
        return None
    t = str(texto).strip()
    if not t:
        return None
    negativo = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    t = re.sub(r"[^\d,.]", "", t)
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if negativo else v


def parse_data(texto, ano_padrao: int | None = None) -> str | None:
    """dd/mm/aaaa, dd/mm/aa, dd-mm-aaaa, aaaa-mm-dd, aaaammdd, dd/mm (com ano_padrao) -> 'YYYY-MM-DD'."""
    if hasattr(texto, "strftime"):
        return texto.strftime("%Y-%m-%d")
    t = str(texto or "").strip()
    padroes = [
        (r"^(\d{4})-(\d{2})-(\d{2})", "ymd"), (r"^(\d{4})(\d{2})(\d{2})", "ymd"),
        (r"^(\d{2})[/.-](\d{2})[/.-](\d{4})", "dmy"), (r"^(\d{2})[/.-](\d{2})[/.-](\d{2})\b", "dmy2"),
        (r"^(\d{2})[/.-](\d{2})\b", "dm"),
    ]
    for rx, tipo in padroes:
        m = re.match(rx, t)
        if not m:
            continue
        try:
            g = [int(x) for x in m.groups()]
            if tipo == "ymd":
                return date(g[0], g[1], g[2]).isoformat()
            if tipo == "dmy":
                return date(g[2], g[1], g[0]).isoformat()
            if tipo == "dmy2":
                return date(2000 + g[2], g[1], g[0]).isoformat()
            if ano_padrao:
                return date(ano_padrao, g[1], g[0]).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- PDF
class PdfSenhaErro(Exception):
    """PDF protegido sem senha ou com senha incorreta."""


def ler_pdf_texto(conteudo: bytes, senhas: list[str] | None = None) -> str:
    from pypdf import PdfReader  # import tardio: só é necessário para PDFs

    leitor = PdfReader(io.BytesIO(conteudo))
    if leitor.is_encrypted:
        tentativas = [s for s in (senhas or []) if s] or [""]
        if not any(leitor.decrypt(s) for s in tentativas):
            raise PdfSenhaErro("PDF protegido: senha ausente ou incorreta." if not senhas
                               else "Senha incorreta para este PDF.")
    if len(leitor.pages) > MAX_PAGINAS:
        raise ValueError(f"PDF com mais de {MAX_PAGINAS} páginas: não vou ler.")
    return "\n".join((p.extract_text() or "") for p in leitor.pages)[:MAX_TEXTO]


# ---------------------------------------------------------------- forma de pagamento e alertas
_FORMAS = [  # ordem importa: mais específico primeiro
    ("Débito automático", r"DEB(ITO)?\.? ?AUT|DEBITO AUTOMATICO|DEB AUTOM"),
    ("PIX", r"\bPIX\b"),
    ("Boleto", r"BOLETO|PAGAMENTO DE TITULO|PAGTO? TITULO|PAG TIT|COBRANCA"),
    ("Transferência / TED", r"\bTED\b|\bDOC\b|TRANSF"),
    ("Débito", r"DEBITO|COMPRA DEB|\bDEB\b"),
]


def detectar_forma(descricao: str) -> str | None:
    n = sem_acentos_upper(descricao)
    for forma, rx in _FORMAS:
        if re.search(rx, n):
            return forma
    return None


_RX_FATURA_CARTAO = r"FATURA|PAG(TO|AMENTO)? CARTAO|PGTO CARTAO|CARTAO DE CREDITO|CARTAO CREDITO"

_ALERTAS = [
    (_RX_FATURA_CARTAO,
     "Pagamento de fatura de cartão: confira se a fatura já foi lançada, para não contar duas vezes."),
    (r"MESMA TITULARIDADE|ENTRE CONTAS|TRANSF(ERENCIA)? PROPRIA|APLICACAO|RESGATE|INVESTIMENTO",
     "Possível transferência entre contas ou investimento: talvez não seja um gasto."),
]


def eh_pagamento_fatura_cartao(descricao: str) -> bool:
    return bool(re.search(_RX_FATURA_CARTAO, sem_acentos_upper(descricao)))


def detectar_alerta(descricao: str) -> str | None:
    n = sem_acentos_upper(descricao)
    achados = [msg for rx, msg in _ALERTAS if re.search(rx, n)]
    return " ".join(achados) or None


# ---------------------------------------------------------------- extratos
def _ler_texto(conteudo: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1", errors="replace")


def _ofx(texto: str, ano: int) -> list[dict]:
    brutos = []
    for bloco in re.findall(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>|$)", texto, re.S | re.I):
        def tag(nome):
            m = re.search(rf"<{nome}>\s*([^<\r\n]*)", bloco, re.I)
            return m.group(1).strip() if m else ""
        valor = parse_valor_br(tag("TRNAMT").replace(",", "."))  # OFX usa ponto; alguns bancos usam vírgula
        if valor is None and tag("TRNAMT"):
            valor = parse_valor_br(tag("TRNAMT"))
        data = parse_data(tag("DTPOSTED"), ano)
        if valor is None or not data:
            continue
        brutos.append({"data": data, "descricao": limpar_descricao(tag("MEMO") or tag("NAME")),
                       "valor": valor, "fitid": tag("FITID")})
    return _so_saidas(brutos)


def _so_saidas(brutos: list[dict]) -> list[dict]:
    """Saída = valor negativo. Se o arquivo não tem nenhum negativo (extrato só de saídas), todos são saídas."""
    tem_negativo = any(b["valor"] < 0 for b in brutos)
    saidas = [b for b in brutos if (b["valor"] < 0 if tem_negativo else b["valor"] != 0)]
    for b in saidas:
        b["valor"] = abs(b["valor"])
    return saidas


_COLUNAS = {
    "data": r"^(data|dt|date)\b",
    "descricao": r"(descri|hist[oó]ric|lan[cç]amento|estabelecimento|detalhe|memo|favorecido|benefici)",
    "valor": r"^(valor|montante|quantia|amount)",
    "debito": r"(d[eé]bito|sa[ií]da|saidas)",
    "credito": r"(cr[eé]dito|entrada)",
    "tipo": r"^(tipo|natureza|d/c|dc|cd)\b",
}


def _tabela(linhas: list[list], ano: int) -> list[dict]:
    """Localiza o cabeçalho (data + valor/débito) e converte as linhas seguintes."""
    idx = {}
    inicio = None
    for i, linha in enumerate(linhas[:40]):
        cel = [sem_acentos_upper(str(c or "")).strip().lower() for c in linha]
        achados = {}
        for nome, rx in _COLUNAS.items():
            for j, c in enumerate(cel):
                if c and re.search(rx, c, re.I) and j not in achados.values():
                    achados[nome] = j
                    break
        if "data" in achados and ("valor" in achados or "debito" in achados):
            idx, inicio = achados, i
            break
    if inicio is None:
        return []

    brutos = []
    for linha in linhas[inicio + 1:]:
        def cel(nome):
            j = idx.get(nome)
            return linha[j] if j is not None and j < len(linha) else None
        data = parse_data(cel("data"), ano)
        if not data:
            continue
        desc = limpar_descricao(str(cel("descricao") or ""))
        if "debito" in idx:
            d = parse_valor_br(cel("debito"))
            if not d:
                continue  # linha só de crédito
            valor = -abs(d)
        else:
            valor = parse_valor_br(cel("valor")) if not isinstance(cel("valor"), (int, float)) else float(cel("valor"))
            if valor is None:
                continue
            tipo = sem_acentos_upper(str(cel("tipo") or "")).strip()
            if tipo in {"D", "DEBITO", "SAIDA", "DEB"}:
                valor = -abs(valor)
            elif tipo in {"C", "CREDITO", "ENTRADA", "CRED"}:
                valor = abs(valor)
        if "SALDO" in sem_acentos_upper(desc):
            continue
        brutos.append({"data": data, "descricao": desc, "valor": valor})
    return _so_saidas(brutos)


def _csv(texto: str, ano: int) -> list[dict]:
    amostra = texto[:4000]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t|")
    except csv.Error:
        dialeto = csv.excel
        dialeto.delimiter = ";" if amostra.count(";") > amostra.count(",") else ","
    return _tabela(list(csv.reader(io.StringIO(texto), dialeto)), ano)


def _xlsx(conteudo: bytes, ano: int) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    for ws in wb.worksheets:
        saidas = _tabela([list(r) for r in ws.iter_rows(values_only=True)], ano)
        if saidas:
            return saidas
    return []


_RE_LINHA_PDF = re.compile(
    r"^(?P<data>\d{2}[/.-]\d{2}(?:[/.-]\d{2,4})?)\s+(?P<desc>.+?)\s+"
    r"(?P<valor>[-+(]?\s?(?:R\$\s?)?\d{1,3}(?:\.\d{3})*,\d{2}\)?\s?[-CD]?)"
    r"(?:\s+[-+(]?\s?\d{1,3}(?:\.\d{3})*,\d{2}\)?\s?[-CD]?)?\s*$")


def _pdf_extrato(texto: str, ano: int) -> list[dict]:
    anos = re.findall(r"\b(20\d{2})\b", texto)
    ano = int(anos[0]) if anos else (ano or date.today().year)
    brutos = []
    for linha in texto[:MAX_TEXTO].splitlines()[:MAX_LINHAS]:
        m = _RE_LINHA_PDF.match(linha.strip()) if len(linha) <= MAX_LINHA else None
        if not m:
            continue
        data = parse_data(m["data"], ano)
        if not data or "SALDO" in sem_acentos_upper(m["desc"]):
            continue
        v = m["valor"].strip()
        valor = parse_valor_br(re.sub(r"[CD]$", "", v))
        if valor is None:
            continue
        if v.endswith("D"):
            valor = -abs(valor)
        elif v.endswith("C"):
            valor = abs(valor)
        brutos.append({"data": data, "descricao": limpar_descricao(m["desc"]), "valor": valor})
    return _so_saidas(brutos)


def ler_extrato(nome_arquivo: str, conteudo: bytes, senhas: list[str] | None = None,
                ano: int | None = None) -> list[dict]:
    """Devolve as saídas do extrato: [{data, descricao, valor(>0), chave}]. Levanta PdfSenhaErro/ValueError."""
    ano = ano or date.today().year
    nome = nome_arquivo.lower()
    if nome.endswith(".pdf"):
        saidas = _pdf_extrato(ler_pdf_texto(conteudo, senhas), ano)
    elif nome.endswith((".xlsx", ".xlsm")):
        saidas = _xlsx(conteudo, ano)
    else:
        texto = _ler_texto(conteudo)
        if "<STMTTRN>" in texto.upper():
            saidas = _ofx(texto, ano)
        elif nome.endswith((".csv", ".txt")) or ";" in texto[:2000] or "," in texto[:2000]:
            saidas = _csv(texto, ano)
        else:
            raise ValueError("Formato não reconhecido. Use OFX, CSV, XLSX ou PDF.")

    vistos: dict[str, int] = {}
    for s in saidas:
        fitid = s.pop("fitid", "")
        base = (f"ofx:{fitid}|{s['data']}|{s['valor']:.2f}" if fitid
                else f"{s['data']}|{s['valor']:.2f}|{padrao(s['descricao'])}")
        vistos[base] = vistos.get(base, 0) + 1
        s["chave"] = "ext:" + hashlib.sha1(f"{base}|{vistos[base]}".encode(), usedforsecurity=False).hexdigest()[:20]
    return saidas


# ---------------------------------------------------------------- faturas
# Rótulos que indicam o valor a pagar. "TOTAL" sozinho de propósito NÃO entra: em contas de energia há
# "Total Distribuidora" (subtotal) e em outras "Total consolidado", que enganam.
_LABELS_VALOR = ["TOTAL A PAGAR", "TOTAL DESTA FATURA", "TOTAL DA SUA FATURA", "VALOR DA SUA FATURA", "FATURA ATUAL", "VALOR A PAGAR", "VALOR DO DOCUMENTO", "VALOR TOTAL", "TOTAL DA FATURA",
                 "TOTAL DA CONTA", "VALOR COBRADO", "VALOR DA FATURA", "VALOR DA CONTA", "VALOR LIQUIDO"]
_RE_DATA = re.compile(r"\b(\d{2}[/.-]\d{2}[/.-]\d{4}|\d{2}[/.-]\d{2}[/.-]\d{2})\b")
_MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
          "NOV": 11, "DEZ": 12}
_MES_REGEX = (r"(?:0[1-9]|1[0-2])[/.-]20\d{2}|(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[A-Z]*[/. -]+20\d{2}")
_VALOR_REGEX = r"\d{1,3}(?:\.\d{3})*,\d{2}"
# Linha-resumo comum em contas: "[mês/ano] dd/mm/aaaa R$ 999,99" (sem rótulos no texto extraído).
_RE_RESUMO = re.compile(rf"(?:(?P<ref>{_MES_REGEX})\s+)?(?P<data>\d{{2}}/\d{{2}}/\d{{4}})\s+R\$\s*(?P<valor>{_VALOR_REGEX})")
_RE_SO_VALOR = re.compile(rf"^(?:R\$\s*)?({_VALOR_REGEX})$")
_RE_SO_DATA = re.compile(r"^(\d{2}/\d{2}/\d{4})$")


# Linhas cujos valores nunca são o total a pagar (limites, taxas, pontos...).
_RE_ROTULO_NEGATIVO = re.compile(r"LIMITE|SAQUE|TAXA|JUROS|IOF|CET|PONTOS|SALDO|MINIMO|DISPONIVEL|UTILIZADO|CREDITOS?/|MULTA|^COMPRAS ")


def _valores_na_linha(linha: str) -> list[float]:
    return [v for v in (parse_valor_br(m.group(0)) for m in _RE_VALOR.finditer(linha[:MAX_LINHA])) if v is not None]


def _mes_token_para_iso(token: str) -> str | None:
    m = re.match(r"(0[1-9]|1[0-2])[/.-](20\d{2})$", token)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    m = re.match(r"(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[A-Z]*[/. -]+(20\d{2})$", token)
    return f"{m.group(2)}-{_MESES[m.group(1)]:02d}" if m else None


def _candidatos_valor(linhas: list[str]) -> list[dict]:
    """Valores possíveis para o total, cada um com a força da evidência e (se houver) vencimento/referência."""
    cands = []
    # 1) rótulo explícito ("TOTAL A PAGAR", "VALOR DO DOCUMENTO"...) com o valor na mesma linha ou nas seguintes
    for label in _LABELS_VALOR:
        for i, l in enumerate(linhas):
            if label not in l:
                continue
            for k, cand in enumerate(linhas[i:i + 3]):
                vals = _valores_na_linha(cand.split(label, 1)[-1] if label in cand else cand)
                if vals and not (vals[0] == 0 and k > 1):  # um 0,00 distante do rótulo costuma ser outro campo
                    cands.append({"valor": vals[0], "peso": 3, "venc": None, "ref": None, "origem": "rótulo"})
                    break
    # 2) linha-resumo "AGO/2026 08/09/2026 R$ 401,45"
    for l in linhas:
        for m in _RE_RESUMO.finditer(l):
            cands.append({"valor": parse_valor_br(m["valor"]), "peso": 3, "venc": parse_data(m["data"]),
                          "ref": _mes_token_para_iso(m["ref"]) if m["ref"] else None, "origem": "resumo"})
    # 3) bloco de pagamento: valor e data isolados em linhas vizinhas (canhoto/ficha de compensação)
    for i, l in enumerate(linhas):
        mv = _RE_SO_VALOR.match(l)
        if not mv or (i > 0 and _RE_ROTULO_NEGATIVO.search(linhas[i - 1])):
            continue
        for viz in linhas[max(0, i - 1):i] + linhas[i + 1:i + 2]:  # só a linha imediatamente antes/depois
            md = _RE_SO_DATA.match(viz)
            if md:
                cands.append({"valor": parse_valor_br(mv.group(1)), "peso": 3, "venc": parse_data(md.group(1)),
                              "ref": None, "origem": "canhoto"})
                break
    return [c for c in cands if c["valor"] is not None]


def analisar_fatura(texto: str) -> dict:
    """Extrai valor, vencimento (ISO) e mês de referência ('YYYY-MM') de um texto de fatura.

    Junta evidências de vários tipos (rótulo, linha-resumo, canhoto): o valor com mais apoio vence.
    Em `alternativas` vêm os outros valores frequentes no documento, para o usuário corrigir com um clique.
    """
    linhas = [l.strip()[:MAX_LINHA] for l in sem_acentos_upper(texto[:MAX_TEXTO]).splitlines()[:MAX_LINHAS] if l.strip()]
    res = {"valor": None, "vencimento": None, "referencia": None, "alternativas": []}

    cands = _candidatos_valor(linhas)
    if cands:
        pontos: dict[float, int] = {}
        for c in cands:
            pontos[c["valor"]] = pontos.get(c["valor"], 0) + c["peso"]
        # empate: vale o que apareceu primeiro (rótulo > resumo > canhoto, na ordem de coleta)
        res["valor"] = max(pontos, key=lambda v: (pontos[v], -[c["valor"] for c in cands].index(v)))
        vencedores = [c for c in cands if c["valor"] == res["valor"]]
        res["vencimento"] = next((c["venc"] for c in vencedores if c["venc"]), None)
        res["referencia"] = next((c["ref"] for c in vencedores if c["ref"]), None)

    if not res["vencimento"]:
        for i, l in enumerate(linhas):
            if "VENCIMENTO" in l:
                for cand in linhas[i:i + 3]:
                    m = _RE_DATA.search(cand)
                    if m:
                        res["vencimento"] = parse_data(m.group(1))
                        break
            if res["vencimento"]:
                break

    if not res["referencia"]:
        for i, l in enumerate(linhas):
            if re.search(r"REFER|COMPETENCIA|PERIODO", l):
                for cand in linhas[i:i + 2]:
                    m = re.search(_MES_REGEX, cand)
                    if m and _mes_token_para_iso(m.group(0)):
                        res["referencia"] = _mes_token_para_iso(m.group(0))
                        break
            if res["referencia"]:
                break
    if not res["referencia"] and res["vencimento"]:
        res["referencia"] = res["vencimento"][:7]

    # valores que se repetem no documento (candidatos a correção manual), sem o escolhido
    contagem: dict[float, int] = {}
    for l in linhas:
        if _RE_ROTULO_NEGATIVO.search(l):
            continue
        for v in _valores_na_linha(l):
            contagem[v] = contagem.get(v, 0) + 1
    res["alternativas"] = [v for v, n in sorted(contagem.items(), key=lambda kv: -kv[1])
                           if n >= 2 and v != res["valor"] and v > 0][:4]
    return res


_SINAIS_CARTAO = ["PAGAMENTO MINIMO", "LIMITE DE CREDITO", "LIMITE TOTAL", "LIMITE DISPONIVEL", "FECHAMENTO DA FATURA",
                  "FATURA DO CARTAO", "CARTAO DE CREDITO", "ROTATIVO", "PARCELAMENTO DA FATURA", "MELHOR DIA DE COMPRA",
                  "LIMITE DE COMPRAS", "PARCELAMENTO DE FATURA", "OPCOES DE PAGAMENTO", "PAGAMENTO TOTAL"]


def parece_fatura_cartao(texto: str) -> bool:
    n = sem_acentos_upper(texto)
    return sum(1 for s in _SINAIS_CARTAO if s in n) >= 2


def reconhecer_cartao(texto: str, cartoes) -> object | None:
    """Cartão citado no texto: palavra-chave do cadastro (ex.: final do cartão) > nome do banco.

    Só o banco pode ser ambíguo (dois titulares no mesmo banco): tenta desempatar pelo primeiro nome do titular.
    """
    n = sem_acentos_upper(texto)
    melhor, tamanho = None, 0
    for c in cartoes:
        for kw in (c["palavra_chave"] or "").split(","):
            kw = sem_acentos_upper(kw).strip()
            if kw and kw in n and len(kw) > tamanho:
                melhor, tamanho = c, len(kw)
    if melhor:
        return melhor
    por_banco = [c for c in cartoes if re.search(rf"\b{re.escape(sem_acentos_upper(c['banco']))}\b", n)]
    if len(por_banco) > 1:
        por_banco = [c for c in por_banco if sem_acentos_upper(c["titular_nome"]).split()[0] in n]
    return por_banco[0] if len(por_banco) == 1 else None


def reconhecer_recorrente(texto: str, recorrentes) -> object | None:
    """Recorrente cuja palavra-chave aparece no texto (vence a palavra mais longa)."""
    n = sem_acentos_upper(texto)
    melhor, tamanho = None, 0
    for r in recorrentes:
        for kw in (r["palavra_chave"] or "").split(","):
            kw = sem_acentos_upper(kw).strip()
            if kw and kw in n and len(kw) > tamanho:
                melhor, tamanho = r, len(kw)
    return melhor
