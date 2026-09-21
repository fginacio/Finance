# Envia uma mensagem de status para o Telegram (bot configurado em telegram.token/telegram.chat). Nunca inclui dados financeiros.
# O token e o chat ficam FORA do projeto (e de qualquer pasta sincronizada, como OneDrive/Dropbox):
# %USERPROFILE%\.controle-gastos\telegram.token e telegram.chat
# Uso: . .\scripts\notificar.ps1 ; Enviar-Telegram "texto"
function Enviar-Telegram([string]$Texto) {
    try {
        $dir = Join-Path $env:USERPROFILE ".controle-gastos"
        $token = (Get-Content (Join-Path $dir "telegram.token") -Raw).Trim()
        $chat = (Get-Content (Join-Path $dir "telegram.chat") -Raw).Trim()
        $corpo = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chat; text = $Texto } | ConvertTo-Json -Compress))
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" -Method Post -Body $corpo -ContentType "application/json; charset=utf-8" | Out-Null
    } catch { Write-Warning "Nao foi possivel enviar o aviso ao Telegram: $($_.Exception.Message)" }
}
