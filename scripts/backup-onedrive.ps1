# Copia o backup do banco (que fica no volume do Docker) para a pasta "backups" do projeto, que o OneDrive sincroniza.
# Gera um backup novo e consistente, confere a integridade, CIFRA o arquivo (scripts\cifrar_backup.py; senha fora do
# OneDrive em %USERPROFILE%\.controle-gastos\backup.senha - rode gerar_senha_backup.py uma vez antes) e mantem so os
# ultimos 30 arquivos cifrados.
# Avisa no Telegram se deu certo ou se falhou (ver scripts\notificar.ps1).
# Uso: .\scripts\backup-onedrive.ps1      (agendado semanalmente: ver README)
param([int]$Manter = 30)
$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
. (Join-Path $PSScriptRoot "notificar.ps1")
$destino = Join-Path $raiz "backups"
$python = Join-Path $raiz ".venv\Scripts\python.exe"
try {
    New-Item -ItemType Directory -Force $destino | Out-Null
    docker compose exec -T db backup.sh | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "falha ao gerar o backup no servico db (o Docker esta ligado?)" }
    $nome = (docker compose exec -T db sh -c "ls -1t /backups/*.db | head -1").Trim()
    if (-not $nome) { throw "nenhum backup encontrado no volume" }
    $arquivo = Split-Path $nome -Leaf
    $ErrorActionPreference = "Continue"   # o docker escreve o progresso no stderr
    docker compose cp "db:$nome" (Join-Path $destino $arquivo) *>$null
    $copiou = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($copiou -ne 0) { throw "falha ao copiar $arquivo" }
    & $python (Join-Path $PSScriptRoot "cifrar_backup.py") cifrar (Join-Path $destino $arquivo)
    if ($LASTEXITCODE -ne 0) { throw "falha ao cifrar $arquivo (rode scripts\gerar_senha_backup.py se ainda nao gerou a senha)" }
    $arquivo = "$arquivo.enc"
    Get-ChildItem $destino -Filter "controle-gastos-*.db.enc" | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Manter | Remove-Item -Force
    $tam = [math]::Round((Get-Item (Join-Path $destino $arquivo)).Length / 1KB)
    Write-Host "Backup cifrado salvo em $destino\$arquivo"
    Enviar-Telegram "Controle de Gastos: backup OK ($arquivo, $tam KB, cifrado) salvo no OneDrive."
} catch {
    Enviar-Telegram "Controle de Gastos: BACKUP FALHOU - $($_.Exception.Message)"
    throw
}
