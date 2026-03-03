$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

$summaryPath = "reports/n8n_last_summary.json"
$signalPath = "reports/daily_signal.json"

if (-not (Test-Path $summaryPath)) {
    throw "Summary file not found: $summaryPath. Run scripts/run_daily_retry.ps1 first."
}

$summary = Get-Content $summaryPath -Raw | ConvertFrom-Json

$allowedModes = @()
if ($null -ne $summary.allowed_modes) {
    $allowedModes = @($summary.allowed_modes)
}

$tradeReady = $false
if ($null -ne $summary.trade_ready) {
    $tradeReady = [bool]$summary.trade_ready
}
else {
    $isSuccess = ($summary.status -eq "SUCCESS")
    $hasSignals = ([int]$summary.signal_count -gt 0)
    $hasGate = ([bool]$summary.gate_t1 -or [bool]$summary.gate_swing)
    $isFresh = ([int]$summary.data_age_days -ge 0 -and [int]$summary.data_age_days -le 1)
    $isHealthy = ([int]$summary.missing_tickers_count -le 5)
    $tradeReady = ($isSuccess -and $hasSignals -and $hasGate -and $isFresh -and $isHealthy)
}

$action = $summary.action
if ([string]::IsNullOrWhiteSpace($action)) {
    $action = if ($tradeReady) { "EXECUTE_MAX_3" } else { "NO_TRADE" }
}

$actionReason = $summary.action_reason
if ([string]::IsNullOrWhiteSpace($actionReason)) {
    $actionReason = if ($tradeReady) { "Summary fallback decision: eligible for execution" } else { "Summary fallback decision: not eligible for execution" }
}

Write-Output "=== IDX Daily Ops Check ==="
Write-Output ("generated_at : {0}" -f $summary.generated_at)
Write-Output ("status       : {0}" -f $summary.status)
Write-Output ("trade_ready  : {0}" -f $tradeReady)
Write-Output ("action       : {0}" -f $action)
Write-Output ("reason       : {0}" -f $actionReason)
Write-Output ("allowed_modes: {0}" -f ($allowedModes -join ","))
Write-Output ("signals      : {0}" -f $summary.signal_count)
Write-Output ("gate_t1      : {0}" -f $summary.gate_t1)
Write-Output ("gate_swing   : {0}" -f $summary.gate_swing)
if ($null -ne $summary.gate_model_t1 -or $null -ne $summary.gate_model_swing) {
    Write-Output ("gate_model_t1: {0}" -f $summary.gate_model_t1)
    Write-Output ("gate_model_sw: {0}" -f $summary.gate_model_swing)
}
if ($null -ne $summary.regime_ok) {
    Write-Output ("regime_ok    : {0}" -f $summary.regime_ok)
    Write-Output ("regime_status: {0}" -f $summary.regime_status)
}
if ($null -ne $summary.kill_switch_active) {
    Write-Output ("kill_active  : {0}" -f $summary.kill_switch_active)
    Write-Output ("kill_modes   : {0}" -f (@($summary.kill_switch_modes) -join ","))
    Write-Output ("kill_until   : {0}" -f $summary.kill_switch_cooldown_until)
}
if ($null -ne $summary.universe_update_status) {
    Write-Output ("universe_upd : {0}" -f $summary.universe_update_status)
}
if ($null -ne $summary.event_risk_update_status) {
    Write-Output ("event_upd    : {0}" -f $summary.event_risk_update_status)
    if ($null -ne $summary.event_risk_update_rows) {
        Write-Output ("event_rows   : {0}" -f $summary.event_risk_update_rows)
    }
}
if ($null -ne $summary.volatility_recalibration_status) {
    Write-Output ("vol_recalib  : {0}" -f $summary.volatility_recalibration_status)
    if ($null -ne $summary.volatility_recalibration_atr_ref -or $null -ne $summary.volatility_recalibration_realized_ref) {
        Write-Output ("vol_refs     : atr={0} rv={1}" -f $summary.volatility_recalibration_atr_ref, $summary.volatility_recalibration_realized_ref)
    }
}
if ($null -ne $summary.event_risk_status) {
    Write-Output ("event_risk   : {0}" -f $summary.event_risk_status)
    Write-Output ("event_excl   : {0}" -f $summary.event_risk_excluded_count)
}
Write-Output ("max_date     : {0}" -f $summary.data_max_date)
Write-Output ("data_age_days: {0}" -f $summary.data_age_days)
Write-Output ("missing_tkrs : {0}" -f $summary.missing_tickers_count)
Write-Output ""

if (-not $tradeReady) {
    Write-Output "Decision: NO TRADE today."
    exit 0
}

if (-not (Test-Path $signalPath)) {
    Write-Output "Signal file not found, cannot print picks: reports/daily_signal.json"
    exit 0
}

$payload = Get-Content $signalPath -Raw | ConvertFrom-Json
$signals = @($payload.signals)
if ($signals.Count -eq 0) {
    Write-Output "Decision: NO TRADE (signal list is empty)."
    exit 0
}

$top = $signals | Select-Object -First 3
Write-Output "Top picks (max 3):"
foreach ($s in $top) {
    Write-Output ("- {0} [{1}] score={2} entry={3} stop={4} tp1={5} tp2={6} size={7}" -f `
            $s.ticker, $s.mode, $s.score, $s.entry, $s.stop, $s.tp1, $s.tp2, $s.size)
}

Write-Output ""
Write-Output "Execution rule:"
Write-Output "1) Entry only near entry level."
Write-Output "2) Always set SL/TP using Auto Order/Bracket."
Write-Output "3) Max open positions: 3, do not override SL manually."
