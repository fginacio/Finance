"""
Leitura do QR de nota fiscal (NFC-e): chave de acesso, consulta na Sefaz e extração do que a página mostra.

Funções sem dependência de HTTP do app, para poder testar com páginas de exemplo. RECURSO EM TESTE.

- O QR da NFC-e é um link para a página pública da Sefaz do estado; o valor NÃO está no QR (só na página).
- A chave de acesso (44 dígitos) traz UF, mês/ano, CNPJ do emitente, série e número.
- A consulta só aceita endereços https de domínios .gov.br (evita usar o servidor para acessar qualquer lugar).
"""
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UFS = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
       "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
       "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
TIMEOUT = 12


def extrair_chave(texto: str) -> str | None:
    """Primeira sequência de 44 dígitos (aceita a chave com espaços/pontos, como vem impressa na nota)."""
    m = re.search(r"(?<!\d)\d{44}(?!\d)", texto or "")
    if m:
        return m.group(0)
    m = re.search(r"(?<!\d)(?:\d{4}[ .]?){11}(?!\d)", texto or "")
    return re.sub(r"\D", "", m.group(0)) if m else None


def decodificar_chave(chave: str) -> dict:
    """Campos embutidos na chave de acesso (não inclui o valor)."""
    cnpj = chave[6:20]
    return {
        "uf": UFS.get(chave[:2], chave[:2]),
        "mes_ano": f"{chave[4:6]}/20{chave[2:4]}",
        "cnpj": f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}",
        "modelo": chave[20:22], "serie": str(int(chave[22:25])), "numero": str(int(chave[25:34])),
    }


def url_permitida(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host.endswith(".gov.br") or host == "gov.br") and p.port in (None, 443)


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def baixar_pagina(url: str) -> tuple[str, dict]:
    """Baixa a página (seguindo até 3 redirecionamentos, sempre dentro dos domínios permitidos)."""
    info = {"url_final": url, "status": None, "bytes": 0, "erro": None}
    opener = urllib.request.build_opener(_SemRedirecionar)
    atual = url
    for _ in range(MAX_REDIRECTS + 1):
        if not url_permitida(atual):
            info["erro"] = f"Endereço fora dos permitidos (só https em .gov.br): {urllib.parse.urlparse(atual).hostname}"
            return "", info
        req = urllib.request.Request(atual, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                                                                   "Chrome/120 Mobile Safari/537.36",
                                                     "Accept": "text/html,*/*", "Accept-Language": "pt-BR,pt;q=0.9"})
        try:
            resp = opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                atual = urllib.parse.urljoin(atual, e.headers["Location"])
                continue
            info["status"], info["erro"] = e.code, f"A Sefaz respondeu HTTP {e.code}."
            return "", info
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            info["erro"] = f"Não foi possível acessar a Sefaz: {getattr(e, 'reason', e)}"
            return "", info
        dados = resp.read(MAX_BYTES + 1)
        info.update(url_final=atual, status=resp.status, bytes=len(dados))
        if len(dados) > MAX_BYTES:
            info["erro"] = "Página grande demais."
            return "", info
        tipo = resp.headers.get_content_charset() or "utf-8"
        try:
            return dados.decode(tipo, errors="replace"), info
        except LookupError:
            return dados.decode("utf-8", errors="replace"), info
    info["erro"] = "Redirecionamentos demais."
    return "", info


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes, self._ignorar = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._ignorar += 1
        elif tag in ("br", "tr", "div", "p", "li", "td", "th", "h1", "h2", "h3"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._ignorar:
            self._ignorar -= 1

    def handle_data(self, dado):
        if not self._ignorar:
            self.partes.append(dado)


def html_para_texto(html: str) -> str:
    p = _Texto()
    try:
        p.feed(html)
    except Exception:  # HTML muito quebrado: usa o que deu para ler
        pass
    texto = re.sub(r"[ \t\xa0]+", " ", "".join(p.partes))
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


_VALOR = r"(\d{1,3}(?:\.\d{3})*,\d{2})"


def extrair_dados(html: str) -> dict:
    """Melhor esforço: valor total, data de emissão e estabelecimento. Devolve só o que encontrou."""
    texto = html_para_texto(html)
    plano = re.sub(r"\s+", " ", texto)
    achado: dict = {"texto_tamanho": len(texto)}
    for rotulo in (r"valor\s*a\s*pagar", r"valor\s*total(?:\s*da\s*nota|\s*da\s*nfc?-?e)?", r"total\s*(?:a\s*pagar|geral)?\s*r\$", r"total"):
        m = re.search(rotulo + r"[^\d]{0,40}" + _VALOR, plano, re.I)
        if m:
            achado["valor"] = m.group(m.lastindex).replace(".", "").replace(",", ".")
            break
    m = re.search(r"emiss[aã]o[^\d]{0,30}(\d{2})/(\d{2})/(\d{4})", plano, re.I) or re.search(r"(\d{2})/(\d{2})/(\d{4})\s+\d{2}:\d{2}", plano)
    if m:
        achado["data"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r'class="[^"]*txtTopo[^"]*"[^>]*>\s*([^<]{3,80}?)\s*<', html, re.I)
    if m:
        achado["estabelecimento"] = re.sub(r"\s+", " ", m.group(1)).strip()
    achado["captcha"] = bool(re.search(r"captcha|recaptcha|hcaptcha", html, re.I))
    achado["amostra"] = texto[:600]
    return achado


# ---------------------------------------------------------------- memória no banco (recebe a conexão)
_RE_OBS = re.compile(r"NFC-e chave (\d{44})")


def cnpj_da_chave(chave: str) -> str:
    return chave[6:20]


def categoria_do_local(db, chave: str):
    """Categoria que você usou da última vez neste estabelecimento (ou None)."""
    return db.execute("SELECT categoria_id, estabelecimento FROM notas_locais WHERE cnpj = ?", (cnpj_da_chave(chave),)).fetchone()


def aprender_local(db, observacoes: str, categoria_id: int, descricao: str) -> None:
    """Chamado ao salvar um lançamento: se veio de uma nota lida, lembra a categoria escolhida para o CNPJ."""
    m = _RE_OBS.search(observacoes or "")
    if not m or not categoria_id:
        return
    db.execute("""INSERT INTO notas_locais (cnpj, categoria_id, estabelecimento) VALUES (?, ?, ?)
                  ON CONFLICT(cnpj) DO UPDATE SET categoria_id = excluded.categoria_id,
                      estabelecimento = COALESCE(NULLIF(excluded.estabelecimento, ''), estabelecimento),
                      atualizado_em = datetime('now')""", (cnpj_da_chave(m.group(1)), categoria_id, (descricao or "").strip()))
    db.commit()


def registrar_leitura(db, chave: str, dados: dict | None) -> str | None:
    """Anota que a nota foi consultada; devolve a data/hora da leitura anterior, se houver."""
    antes = db.execute("SELECT lida_em FROM notas_lidas WHERE chave = ?", (chave,)).fetchone()
    d = dados or {}
    valor = float(d["valor"]) if d.get("valor") else None
    db.execute("""INSERT INTO notas_lidas (chave, data, valor, estabelecimento) VALUES (?, ?, ?, ?)
                  ON CONFLICT(chave) DO UPDATE SET lida_em = datetime('now'),
                      data = COALESCE(excluded.data, data), valor = COALESCE(excluded.valor, valor),
                      estabelecimento = COALESCE(excluded.estabelecimento, estabelecimento)""",
               (chave, d.get("data"), valor, d.get("estabelecimento")))
    db.commit()
    return antes["lida_em"] if antes else None


def ja_cadastrada(db, chave: str):
    """Lançamento que já carrega esta chave nas observações (cadastrado a partir desta nota)."""
    return db.execute("SELECT id, data, valor, descricao FROM lancamentos WHERE observacoes LIKE ? LIMIT 1",
                      (f"%NFC-e chave {chave}%",)).fetchone()


def parecidos(db, chave: str, valor: float | None, data: str | None) -> list:
    """Lançamentos de mesmo valor em datas próximas (ex.: o mesmo gasto vindo do extrato ou da fatura do cartão)."""
    if not valor or not data:
        return []
    return db.execute(
        """SELECT id, data, valor, descricao, origem FROM lancamentos
           WHERE abs(valor - ?) < 0.005 AND abs(julianday(data) - julianday(?)) <= 3
             AND COALESCE(observacoes, '') NOT LIKE ? ORDER BY data LIMIT 5""",
        (valor, data, f"%NFC-e chave {chave}%")).fetchall()
