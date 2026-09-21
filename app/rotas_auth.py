"""Login, logout, "Minha conta" e gerenciamento de usuários (Cadastros → Usuários)."""
import time
import urllib.parse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.autenticacao import (BLOQUEIO_MINUTOS, COOKIE, MAX_FALHAS, cookie_seguro, criar_sessao, destino_seguro,
                              encerrar_sessao, encerrar_sessoes_do_usuario, usuario_da_sessao)
from app.database import get_db
from app.seguranca import HASH_FALSO, hash_senha, precisa_refazer_hash, validar_senha, verificar_senha
from app.templating import templates

router = APIRouter()

ERRO_LOGIN = "Usuário ou senha incorretos."


def _tela_login(request, db, erro=None, usuario="", destino="/", status=200):
    sem_usuarios = db.execute("SELECT COUNT(*) FROM usuarios WHERE ativo = 1").fetchone()[0] == 0
    return templates.TemplateResponse(request, "login.html", {"erro": erro, "usuario": usuario, "next": destino,
                                                                "sem_usuarios": sem_usuarios}, status_code=status)


# ---------------------------------------------------------------- login / logout
@router.get("/login")
def login_form(request: Request, next: str = "/", db=Depends(get_db)):
    destino = destino_seguro(next)
    if usuario_da_sessao(db, request.cookies.get(COOKIE)):
        return RedirectResponse(destino, status_code=303)
    return _tela_login(request, db, destino=destino)


@router.post("/login")
def login(request: Request, db=Depends(get_db), usuario: str = Form(""), senha: str = Form(""),
          lembrar: str | None = Form(None), next: str = Form("/")):
    destino = destino_seguro(next)
    nome = usuario.strip()
    u = db.execute("SELECT * FROM usuarios WHERE usuario = ? AND ativo = 1", (nome,)).fetchone() if nome else None

    if u and u["bloqueado_ate"]:
        restante = db.execute("SELECT (julianday(?) - julianday('now')) * 1440", (u["bloqueado_ate"],)).fetchone()[0]
        if restante > 0:
            minutos = int(restante) + 1
            return _tela_login(request, db, f"Muitas tentativas erradas. Tente de novo em {minutos} minuto(s).", nome, destino, 429)

    correta = verificar_senha(senha, u["senha_hash"] if u else HASH_FALSO)  # sempre gasta o mesmo tempo
    if not (u and correta):
        if u:
            falhas = u["falhas"] + 1
            if falhas >= MAX_FALHAS:
                db.execute("UPDATE usuarios SET falhas = 0, bloqueado_ate = datetime('now', ?) WHERE id = ?",
                           (f"+{BLOQUEIO_MINUTOS} minutes", u["id"]))
            else:
                db.execute("UPDATE usuarios SET falhas = ? WHERE id = ?", (falhas, u["id"]))
            db.commit()
        time.sleep(0.4)  # freia tentativas em massa
        return _tela_login(request, db, ERRO_LOGIN, nome, destino, 401)

    db.execute("UPDATE usuarios SET falhas = 0, bloqueado_ate = NULL, ultimo_login = datetime('now') WHERE id = ?", (u["id"],))
    if precisa_refazer_hash(u["senha_hash"]):  # hash antigo/mais fraco: atualiza agora que a senha está em mãos
        db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (hash_senha(senha), u["id"]))
    token, segundos = criar_sessao(db, u["id"], bool(lembrar), request.client.host if request.client else None,
                                   request.headers.get("user-agent"))
    resposta = RedirectResponse(destino, status_code=303)
    resposta.set_cookie(COOKIE, token, max_age=segundos if lembrar else None, httponly=True, samesite="lax",
                        secure=cookie_seguro(request), path="/")
    return resposta


@router.post("/logout")
def logout(request: Request, db=Depends(get_db)):
    encerrar_sessao(db, request.cookies.get(COOKIE))
    resposta = RedirectResponse("/login", status_code=303)
    resposta.delete_cookie(COOKIE, path="/")
    return resposta


# ---------------------------------------------------------------- minha conta
@router.get("/conta")
def conta(request: Request, ok: str | None = None, erro: str | None = None, db=Depends(get_db)):
    ultimo = db.execute("SELECT ultimo_login FROM usuarios WHERE id = ?", (request.state.usuario["id"],)).fetchone()[0]
    sessoes = db.execute("SELECT COUNT(*) FROM sessoes WHERE usuario_id = ? AND expira_em > datetime('now')",
                         (request.state.usuario["id"],)).fetchone()[0]
    return templates.TemplateResponse(request, "conta.html", {"ok": ok, "erro": erro, "ultimo_login": ultimo, "sessoes": sessoes})


@router.post("/conta/senha")
def trocar_senha(request: Request, db=Depends(get_db), atual: str = Form(""), nova: str = Form(""), confirmacao: str = Form("")):
    eu = request.state.usuario
    linha = db.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (eu["id"],)).fetchone()
    if not verificar_senha(atual, linha["senha_hash"]):
        time.sleep(0.4)
        return RedirectResponse("/conta?erro=" + urllib.parse.quote("A senha atual está incorreta."), status_code=303)
    if nova != confirmacao:
        return RedirectResponse("/conta?erro=" + urllib.parse.quote("A confirmação não confere com a nova senha."), status_code=303)
    problema = validar_senha(nova, eu["usuario"])
    if problema:
        return RedirectResponse("/conta?erro=" + urllib.parse.quote(problema), status_code=303)
    db.execute("UPDATE usuarios SET senha_hash = ?, falhas = 0, bloqueado_ate = NULL WHERE id = ?", (hash_senha(nova), eu["id"]))
    db.commit()
    encerrar_sessoes_do_usuario(db, eu["id"], manter_token=request.cookies.get(COOKIE))  # derruba os outros aparelhos
    return RedirectResponse("/conta?ok=" + urllib.parse.quote("Senha alterada. Os outros aparelhos foram desconectados."), status_code=303)


# ---------------------------------------------------------------- gerenciar usuários
def _volta(erro: str | None = None, ok: str | None = None) -> RedirectResponse:
    q = "erro=" + urllib.parse.quote(erro) if erro else ("ok=" + urllib.parse.quote(ok) if ok else "")
    return RedirectResponse("/cadastros/usuarios" + (f"?{q}" if q else ""), status_code=303)


@router.post("/cadastros/usuarios/criar")
def criar_usuario(db=Depends(get_db), nome: str = Form(...), usuario: str = Form(...), senha: str = Form(...)):
    usuario = usuario.strip()
    if not usuario or not nome.strip() or " " in usuario:
        return _volta(erro="Informe o nome e um usuário sem espaços.")
    problema = validar_senha(senha, usuario)
    if problema:
        return _volta(erro=problema)
    if db.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
        return _volta(erro="Já existe um usuário com esse nome de acesso.")
    db.execute("INSERT INTO usuarios (usuario, nome, senha_hash) VALUES (?, ?, ?)", (usuario, nome.strip(), hash_senha(senha)))
    db.commit()
    return _volta(ok=f"Usuário {usuario} criado.")


@router.post("/cadastros/usuarios/{uid}/senha")
def redefinir_senha(uid: int, request: Request, db=Depends(get_db), nova: str = Form(...)):
    alvo = db.execute("SELECT usuario FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if alvo is None:
        return _volta(erro="Usuário não encontrado.")
    problema = validar_senha(nova, alvo["usuario"])
    if problema:
        return _volta(erro=problema)
    db.execute("UPDATE usuarios SET senha_hash = ?, falhas = 0, bloqueado_ate = NULL WHERE id = ?", (hash_senha(nova), uid))
    db.commit()
    eu = request.state.usuario["id"] == uid
    encerrar_sessoes_do_usuario(db, uid, manter_token=request.cookies.get(COOKIE) if eu else None)
    return _volta(ok=f"Senha de {alvo['usuario']} redefinida.")


@router.post("/cadastros/usuarios/{uid}/alternar")
def alternar_usuario(uid: int, request: Request, db=Depends(get_db)):
    alvo = db.execute("SELECT usuario, ativo FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if alvo is None:
        return _volta(erro="Usuário não encontrado.")
    if alvo["ativo"]:
        if uid == request.state.usuario["id"]:
            return _volta(erro="Você não pode desativar o próprio usuário.")
        if db.execute("SELECT COUNT(*) FROM usuarios WHERE ativo = 1").fetchone()[0] <= 1:
            return _volta(erro="É preciso manter pelo menos um usuário ativo.")
    db.execute("UPDATE usuarios SET ativo = 1 - ativo WHERE id = ?", (uid,))
    db.commit()
    if alvo["ativo"]:
        encerrar_sessoes_do_usuario(db, uid)
    return _volta(ok=f"Usuário {alvo['usuario']} {'desativado' if alvo['ativo'] else 'reativado'}.")
