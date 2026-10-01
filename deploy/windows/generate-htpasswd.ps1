<#
.SYNOPSIS
    Generates the htpasswd file nginx uses for Basic Auth in front of the ops dashboard/API
    (see services/dashboard/nginx.conf). Never commit the output file - deploy/secrets/ is
    gitignored and mounted read-only into the dashboard container by docker-compose.yml.

.EXAMPLE
    .\deploy\windows\generate-htpasswd.ps1 -Username staff
    # prompts for a password, writes deploy/secrets/htpasswd
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Username,

    [string]$OutFile = "deploy/secrets/htpasswd"
)

$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    Write-Error "openssl not found on PATH. Git for Windows bundles it (mingw64/bin) - " `
        "run this from Git Bash, or install OpenSSL for Windows separately."
    exit 1
}

$securePassword = Read-Host -AsSecureString "Password for '$Username'"
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

# APR1-MD5 (openssl passwd -apr1) is one of the formats nginx's ngx_http_auth_basic_module
# supports natively, no extra nginx module needed.
$hash = & openssl passwd -apr1 $plainPassword
$plainPassword = $null  # drop the plaintext copy from memory as soon as we're done with it

$outDir = Split-Path $OutFile -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

"${Username}:${hash}" | Out-File -FilePath $OutFile -Encoding ascii -NoNewline
Write-Host "Wrote $OutFile - restart the dashboard container (docker compose restart dashboard) to pick it up."
