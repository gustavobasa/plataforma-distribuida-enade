# Gera .env a partir de .env.example substituindo "trocar-*" por senhas aleatórias.
$raiz = Split-Path -Parent $PSScriptRoot
$destino = Join-Path $raiz ".env"
if (Test-Path $destino) { Write-Host ".env já existe; nada feito."; exit 0 }
$chars = [char[]]"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
$linhas = Get-Content (Join-Path $raiz ".env.example") | ForEach-Object {
  if ($_ -match '^([A-Z0-9_]+)=trocar-') {
    $senha = -join (1..24 | ForEach-Object { $chars | Get-Random })
    "$($Matches[1])=$senha"
  } else { $_ }
}
[System.IO.File]::WriteAllLines($destino, $linhas)
Write-Host ".env criado com senhas aleatórias."
