param(
    [Parameter(Mandatory=$true)][ValidateCount(1,16)][string[]]$PeerIp,
    [ValidateRange(1024,65535)][int]$Port = 45832,
    [string]$ExePath = '',
    [switch]$InputOnly
)
$ErrorActionPreference = 'Stop'
$taskAddresses = foreach ($taskPeerIp in $PeerIp) {
$taskAddress = [System.Net.IPAddress]::Parse($taskPeerIp)
$taskBytes = $taskAddress.GetAddressBytes()
$taskAllowed = [System.Net.IPAddress]::IsLoopback($taskAddress)
if ($taskBytes.Length -eq 4) {
    $taskAllowed = $taskAllowed -or $taskBytes[0] -eq 10 -or ($taskBytes[0] -eq 172 -and $taskBytes[1] -ge 16 -and $taskBytes[1] -le 31) -or ($taskBytes[0] -eq 192 -and $taskBytes[1] -eq 168) -or ($taskBytes[0] -eq 100 -and $taskBytes[1] -ge 64 -and $taskBytes[1] -le 127) -or ($taskBytes[0] -eq 169 -and $taskBytes[1] -eq 254)
} else {
    $taskAllowed = $taskAllowed -or (($taskBytes[0] -band 254) -eq 252) -or $taskAddress.IsIPv6LinkLocal
}
if (!$taskAllowed) { throw 'LAN/Tailscale IP only.' }
$taskAddress.ToString()
}
if (!$InputOnly -and !$ExePath) {
    $ExePath = Join-Path $PSScriptRoot 'ClipBridge.exe'
    if (!(Test-Path -LiteralPath $ExePath)) { $ExePath = Join-Path $PSScriptRoot 'dist\v1.5.0\ClipBridge.exe' }
}
$taskRule = if ($InputOnly) { 'ClipBridge-v1-Input-Private' } else { 'ClipBridge-v1-Private' }
$taskOptions = @{
    Name = $taskRule
    DisplayName = if ($InputOnly) { 'ClipBridge input (Private, paired PCs only)' } else { 'ClipBridge (Private, paired PCs only)' }
    Direction = 'Inbound'
    Action = 'Allow'
    Protocol = 'TCP'
    LocalPort = $Port
    RemoteAddress = $taskAddresses
    Profile = 'Private'
    EdgeTraversalPolicy = 'Block'
}
if (!$InputOnly) { $taskOptions.Program = (Resolve-Path -LiteralPath $ExePath).Path }
Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule @taskOptions | Out-Null
Write-Output 'Private TCP firewall rule created. Public profile remains blocked.'
