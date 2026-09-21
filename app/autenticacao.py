"""
Autenticação: sessão guardada no servidor, dependência que protege TODAS as rotas e cabeçalhos de segurança.

- O cookie carrega só um token aleatório; no banco fica o hash dele (dá para encerrar uma sessão a qualquer hora).
- Cookie HttpOnly + SameSite=Lax (o navegador não envia o cookie em POSTs vindos de outro site).
- Além disso, POST/PUT/PATCH/DELETE com cabeçalho Origin de outro endereço são recusados.
"""
import os
from urllib.parse import quote, urlparse

from fastapi import Depends, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from app import avisos
from app.database import get_db
from app.seguranca import hash_token, novo_token

COOKIE = "cg_sessao"
PUBLICAS = {"/login"}
PREFIXOS_LIVRES = ("/static/",)
MAX_FALHAS = 5
BLOQUEIO_MINUTOS = 15
HORAS_SESSAO = 12
DIAS_LEMBRAR = 30
METODOS_QUE_ALTERAM = {"POST", "PUT", "PATCH", "DELETE"}

# O app não carrega nada de fora (Bootstrap e HTMX são servidos por /static/vendor). O CSP proíbe qualquer origem
# externa, formulários que enviem dados para outro site e a página dentro de moldura de outro site.
# 'unsafe-inline' fica em script/style porque as telas usam pequenos handlers e estilos inline.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")


class NaoAutenticado(Exception):
    """Levantada quando a rota exige login e a sessão não existe ou expirou."""


# ---------------------------------------------------------------- sessões
def criar_sessao(db, usuario_id: int, lembrar: bool, ip: str | None, agente: str | None) -> tuple[str, int]:
    """Cria a sessão e devolve (token, duração em segundos)."""
    segundos = DIAS_LEMBRAR * 86400 if lembrar else HORAS_SESSAO * 3600
    token = novo_token()
    db.execute("DELETE FROM sessoes WHERE expira_em <= datetime('now')")
    db.execute("INSERT INTO sessoes (token_hash, usuario_id, expira_em, ip, agente) VALUES (?, ?, datetime('now', ?), ?, ?)",
               (hash_token(token), usuario_id, f"+{segundos} seconds", ip, (agente or "")[:200]))
    db.commit()
    return token, segundos


def usuario_da_sessao(db, token: str | None):
    if not token:
        return None
    return db.execute(
        """SELECT u.id, u.usuario, u.nome FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = ? AND s.expira_em > datetime('now') AND u.ativo = 1""", (hash_token(token),)).fetchone()


def encerrar_sessao(db, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessoes WHERE token_hash = ?", (hash_token(token),))
        db.commit()


def encerrar_sessoes_do_usuario(db, usuario_id: int, manter_token: str | None = None) -> None:
    """Encerra todas as sessões do usuário (exceto, se informada, a atual)."""
    if manter_token:
        db.execute("DELETE FROM sessoes WHERE usuario_id = ? AND token_hash != ?", (usuario_id, hash_token(manter_token)))
    else:
        db.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
    db.commit()


def cookie_seguro(request: Request) -> bool:
    """Cookie 'Secure' quando a página é HTTPS (direto ou atrás de proxy) ou se COOKIE_SECURE=1."""
    return request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"


# ---------------------------------------------------------------- proteção das rotas
def exigir_login(request: Request, db=Depends(get_db)) -> None:
    """Dependência global: sem sessão válida, nada é servido (exceto /login e /static)."""
    caminho = request.url.path
    if caminho in PUBLICAS or caminho.startswith(PREFIXOS_LIVRES):
        return
    usuario = usuario_da_sessao(db, request.cookies.get(COOKIE))
    if usuario is None:
        raise NaoAutenticado()
    request.state.usuario = usuario


def destino_seguro(destino: str | None) -> str:
    """Só aceita caminho interno (evita redirecionar para outro site depois do login)."""
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino and "\n" not in destino:
        return destino
    return "/"


def resposta_nao_autenticado(request: Request, exc: NaoAutenticado) -> Response:
    if request.headers.get("hx-request"):  # ação do HTMX: manda o navegador inteiro para o login
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    destino = "/login"
    if request.method == "GET":
        atual = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if atual != "/":
            destino += "?next=" + quote(atual, safe="")
    return RedirectResponse(destino, status_code=303)


async def protecao_basica(request: Request, call_next):
    """Recusa POST/DELETE... de outra origem e acrescenta cabeçalhos de segurança."""
    if request.method in METODOS_QUE_ALTERAM:
        origem = request.headers.get("origin")
        if origem and origem != "null":
            permitidos = {request.headers.get("host", "").lower()}
            permitidos |= {o.strip().lower() for o in os.environ.get("ORIGENS_PERMITIDAS", "").split(",") if o.strip()}
            if urlparse(origem).netloc.lower() not in permitidos:
                return PlainTextResponse("Origem não permitida.", status_code=403)
    resposta = await call_next(request)
    if request.method in METODOS_QUE_ALTERAM and resposta.status_code < 400:
        usuario = getattr(request.state, "usuario", None)
        if usuario is not None:
            avisos.enviar_pendentes(usuario["nome"])  # Telegram: quem cadastrou/alterou/excluiu (não atrapalha se falhar)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "same-origin"
    resposta.headers["Content-Security-Policy"] = CSP
    resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    resposta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resposta.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if not request.url.path.startswith(PREFIXOS_LIVRES):
        resposta.headers["Cache-Control"] = "no-store"  # dados financeiros não ficam em cache do navegador/proxy
    return resposta
