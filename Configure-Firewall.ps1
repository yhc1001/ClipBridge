param(
    [Parameter(Mandatory=$true)][string]$PeerIp,
    [ValidateRange(1024,65535)][int]$Port = 45832,
    [string]$ExePath = ''
)
$ErrorActionPreference = 'Stop'
$taskAddress = [System.Net.IPAddress]::Parse($PeerIp)
$taskBytes = $taskAddress.GetAddressBytes()
$taskAllowed = [System.Net.IPAddress]::IsLoopback($taskAddress)
if ($taskBytes.Length -eq 4) {
    $taskAllowed = $taskAllowed -or $taskBytes[0] -eq 10 -or ($taskBytes[0] -eq 172 -and $taskBytes[1] -ge 16 -and $taskBytes[1] -le 31) -or ($taskBytes[0] -eq 192 -and $taskBytes[1] -eq 168) -or ($taskBytes[0] -eq 100 -and $taskBytes[1] -ge 64 -and $taskBytes[1] -le 127) -or ($taskBytes[0] -eq 169 -and $taskBytes[1] -eq 254)
} else {
    $taskAllowed = $taskAllowed -or (($taskBytes[0] -band 254) -eq 252) -or $taskAddress.IsIPv6LinkLocal
}
if (!$taskAllowed) { throw 'LAN/Tailscale IP only.' }
if (!$ExePath) {
    $ExePath = Join-Path $PSScriptRoot 'ClipBridge.exe'
    if (!(Test-Path -LiteralPath $ExePath)) { $ExePath = Join-Path $PSScriptRoot 'dist\ClipBridge.exe' }
}
$taskExe = (Resolve-Path -LiteralPath $ExePath).Path
$taskRule = 'ClipBridge-v1-Private'
Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name $taskRule -DisplayName 'ClipBridge (Private, paired PC only)' -Direction Inbound -Action Allow -Program $taskExe -Protocol TCP -LocalPort $Port -RemoteAddress $taskAddress.ToString() -Profile Private -EdgeTraversalPolicy Block | Out-Null
Write-Output 'Private TCP firewall rule created. Public profile remains blocked.'
