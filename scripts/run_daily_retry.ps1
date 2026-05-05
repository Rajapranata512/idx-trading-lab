param(
    [string]$SettingsPath = "config/settings.json"
)

$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )
    $v = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    $v = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    $v = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    return $null
}

function Ensure-RequiredEnv {
    $required = @("EODHD_API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    $missing = @()
    foreach ($name in $required) {
        $value = Get-EnvValue -Name $name
        if ([string]::IsNullOrWhiteSpace($value)) {
            $missing += $name
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    if ($missing.Count -gt 0) {
        throw ("Missing environment variables: " + ($missing -join ", "))
    }
}

function Build-Summary {
    param(
        [bool]$Ok,
        [string]$Status,
        [string]$Message,
        [int]$Attempts,
        [int]$ExitCode,
        [string]$RunId
    )
    $summary = [ordered]@{
        ok = $Ok
        status = $Status
        message = $Message
        attempts = $Attempts
        exit_code = $ExitCode
        run_id = $RunId
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        signal_count = 0
        gate_t1 = $false
        gate_swing = $false
        gate_model_t1 = $false
        gate_model_swing = $false
        regime_ok = $true
        regime_status = "unknown"
        regime_reason = ""
        kill_switch_active = $false
        kill_switch_modes = @()
        kill_switch_status = "unknown"
        kill_switch_cooldown_until = ""
        universe_update_status = ""
        universe_update_message = ""
        event_risk_update_status = ""
        event_risk_update_message = ""
        event_risk_update_updated = $false
        event_risk_update_rows = 0
        volatility_recalibration_status = ""
        volatility_recalibration_message = ""
        volatility_recalibration_updated = $false
        volatility_recalibration_atr_ref = 0.0
        volatility_recalibration_realized_ref = 0.0
        event_risk_status = ""
        event_risk_excluded_count = 0
        vol_target_market_regime = ""
        vol_target_regime_cap = 0.0
        vol_target_market_vol_index = 0.0
        vol_target_multiplier_avg = 0.0
        vol_target_multiplier_min = 0.0
        vol_target_multiplier_max = 0.0
        data_max_date = ""
        data_age_days = -1
        missing_tickers_count = 0
        allowed_modes = @()
        trade_ready = $false
        action = "NO_TRADE"
        action_reason = "Not evaluated"
    }

    if (Test-Path "reports/backtest_metrics.json") {
        try {
            $bt = Get-Content "reports/backtest_metrics.json" -Raw | ConvertFrom-Json
            if ($null -ne $bt.gate_pass) {
                $summary.gate_t1 = [bool]$bt.gate_pass.t1
                $summary.gate_swing = [bool]$bt.gate_pass.swing
            }
            if ($null -ne $bt.gate_pass_model) {
                $summary.gate_model_t1 = [bool]$bt.gate_pass_model.t1
                $summary.gate_model_swing = [bool]$bt.gate_pass_model.swing
            }
            if ($null -ne $bt.regime) {
                $summary.regime_ok = [bool]$bt.regime.pass
                $summary.regime_status = [string]$bt.regime.status
                $summary.regime_reason = [string]$bt.regime.reason
            }
            if ($null -ne $bt.kill_switch) {
                $summary.kill_switch_active = [bool]$bt.kill_switch.active
                $summary.kill_switch_status = [string]$bt.kill_switch.status
                $summary.kill_switch_cooldown_until = [string]$bt.kill_switch.cooldown_until
                if ($null -ne $bt.kill_switch.active_modes) {
                    $summary.kill_switch_modes = @($bt.kill_switch.active_modes)
                }
            }
        }
        catch { }
    }
    if (Test-Path "reports/daily_signal.json") {
        try {
            $sig = Get-Content "reports/daily_signal.json" -Raw | ConvertFrom-Json
            if ($null -ne $sig.signals) {
                $summary.signal_count = @($sig.signals).Count
            }
        }
        catch { }
    }
    if (Test-Path "reports/daily_report.csv") {
        try {
            $planRows = Import-Csv "reports/daily_report.csv"
            if ($planRows.Count -gt 0) {
                $first = $planRows | Select-Object -First 1
                if ($null -ne $first.vol_target_market_regime) {
                    $summary.vol_target_market_regime = [string]$first.vol_target_market_regime
                }
                if ($null -ne $first.vol_target_regime_cap -and -not [string]::IsNullOrWhiteSpace([string]$first.vol_target_regime_cap)) {
                    $summary.vol_target_regime_cap = [math]::Round([double]$first.vol_target_regime_cap, 4)
                }
                if ($null -ne $first.vol_target_market_vol_index -and -not [string]::IsNullOrWhiteSpace([string]$first.vol_target_market_vol_index)) {
                    $summary.vol_target_market_vol_index = [math]::Round([double]$first.vol_target_market_vol_index, 4)
                }

                $mult = @(
                    $planRows |
                    Where-Object { $null -ne $_.vol_target_multiplier -and -not [string]::IsNullOrWhiteSpace([string]$_.vol_target_multiplier) } |
                    ForEach-Object { [double]$_.vol_target_multiplier }
                )
                if ($mult.Count -gt 0) {
                    $summary.vol_target_multiplier_avg = [math]::Round((($mult | Measure-Object -Average).Average), 4)
                    $summary.vol_target_multiplier_min = [math]::Round((($mult | Measure-Object -Minimum).Minimum), 4)
                    $summary.vol_target_multiplier_max = [math]::Round((($mult | Measure-Object -Maximum).Maximum), 4)
                }
            }
        }
        catch { }
    }

    if (Test-Path "data/raw/prices_daily.csv") {
        try {
            $prices = Import-Csv "data/raw/prices_daily.csv"
            if ($prices.Count -gt 0) {
                $maxDate = ($prices | ForEach-Object { [datetime]$_.date } | Sort-Object -Descending | Select-Object -First 1)
                $summary.data_max_date = $maxDate.ToString("yyyy-MM-dd")
                $summary.data_age_days = [int]((Get-Date).Date - $maxDate.Date).TotalDays
            }
        }
        catch { }
    }
    if (Test-Path "reports/run_log_$(Get-Date -Format yyyyMMdd).json") {
        try {
            $logPath = "reports/run_log_$(Get-Date -Format yyyyMMdd).json"
            $events = Get-Content $logPath -Raw | ConvertFrom-Json
            $ingest = $events | Where-Object { $_.message -eq "ingest_done" } | Select-Object -Last 1
            if ($null -ne $ingest -and $null -ne $ingest.extra.missing_tickers_count) {
                $summary.missing_tickers_count = [int]$ingest.extra.missing_tickers_count
            }
            $uni = $events | Where-Object { $_.message -eq "universe_update_done" } | Select-Object -Last 1
            if ($null -ne $uni -and $null -ne $uni.extra) {
                if ($null -ne $uni.extra.status) { $summary.universe_update_status = [string]$uni.extra.status }
                if ($null -ne $uni.extra.message) { $summary.universe_update_message = [string]$uni.extra.message }
            }
            $evu = $events | Where-Object { $_.message -eq "event_risk_update_done" } | Select-Object -Last 1
            if ($null -ne $evu -and $null -ne $evu.extra) {
                if ($null -ne $evu.extra.status) { $summary.event_risk_update_status = [string]$evu.extra.status }
                if ($null -ne $evu.extra.message) { $summary.event_risk_update_message = [string]$evu.extra.message }
                if ($null -ne $evu.extra.updated) { $summary.event_risk_update_updated = [bool]$evu.extra.updated }
                if ($null -ne $evu.extra.counts -and $null -ne $evu.extra.counts.rows) { $summary.event_risk_update_rows = [int]$evu.extra.counts.rows }
            }
            $vrec = $events | Where-Object { $_.message -eq "volatility_recalibration_done" } | Select-Object -Last 1
            if ($null -ne $vrec -and $null -ne $vrec.extra) {
                if ($null -ne $vrec.extra.status) { $summary.volatility_recalibration_status = [string]$vrec.extra.status }
                if ($null -ne $vrec.extra.message) { $summary.volatility_recalibration_message = [string]$vrec.extra.message }
                if ($null -ne $vrec.extra.updated) { $summary.volatility_recalibration_updated = [bool]$vrec.extra.updated }
                if ($null -ne $vrec.extra.new_targets) {
                    if ($null -ne $vrec.extra.new_targets.volatility_reference_atr_pct) {
                        $summary.volatility_recalibration_atr_ref = [double]$vrec.extra.new_targets.volatility_reference_atr_pct
                    }
                    if ($null -ne $vrec.extra.new_targets.volatility_reference_realized_pct) {
                        $summary.volatility_recalibration_realized_ref = [double]$vrec.extra.new_targets.volatility_reference_realized_pct
                    }
                }
            }
            $ev = $events | Where-Object { $_.message -eq "event_risk_filtered" } | Select-Object -Last 1
            if ($null -ne $ev -and $null -ne $ev.extra) {
                if ($null -ne $ev.extra.status) { $summary.event_risk_status = [string]$ev.extra.status }
                if ($null -ne $ev.extra.excluded_count) { $summary.event_risk_excluded_count = [int]$ev.extra.excluded_count }
            }
        }
        catch { }
    }

    return $summary
}

function Test-RunCompletedFromLog {
    param(
        [string]$RunId
    )
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        return $false
    }
    $logPath = "reports/run_log_$(Get-Date -Format yyyyMMdd).json"
    if (-not (Test-Path $logPath)) {
        return $false
    }
    try {
        $events = Get-Content $logPath -Raw | ConvertFrom-Json
        $runEvents = @($events | Where-Object { $_.run_id -eq $RunId })
        if ($runEvents.Count -eq 0) { return $false }

        $hasError = @($runEvents | Where-Object { $_.level -eq "ERROR" }).Count -gt 0
        if ($hasError) { return $false }

        $hasBacktest = @($runEvents | Where-Object { $_.message -eq "backtest_done" }).Count -gt 0
        $hasTerminal = @(
            $runEvents |
            Where-Object { $_.message -eq "telegram_skipped" -or $_.message -eq "telegram_done" }
        ).Count -gt 0

        return [bool]($hasBacktest -and $hasTerminal)
    }
    catch {
        return $false
    }
}

$maxAttempts = 3
$delays = @(60, 120, 240)
$attempt = 0
$lastExitCode = 1
$runId = ""
$lastOutput = ""
$softSuccessDetected = $false

try {
    if (-not (Test-Path $SettingsPath)) {
        throw "Settings file not found: $SettingsPath"
    }

    Ensure-RequiredEnv

    while ($attempt -lt $maxAttempts) {
        $attempt += 1
        $lastOutput = (& python -m src.cli --settings $SettingsPath run-daily --skip-telegram 2>&1 | Out-String)
        $lastExitCode = $LASTEXITCODE
        if ($lastOutput -match '"run_id"\s*:\s*"([^"]+)"') {
            $runId = $matches[1]
        }
        if ($lastExitCode -ne 0) {
            $softOk = Test-RunCompletedFromLog -RunId $runId
            if ($softOk) {
                $softSuccessDetected = $true
                $lastExitCode = 0
            }
        }

        if ($lastExitCode -eq 0) {
            $baseMessage = "run-daily completed"
            if ($softSuccessDetected) {
                $baseMessage = "run-daily completed (soft success via run log fallback)"
            }
            $summary = Build-Summary -Ok $true -Status "SUCCESS" -Message $baseMessage -Attempts $attempt -ExitCode $lastExitCode -RunId $runId
            if ($summary.data_age_days -gt 3) {
                $summary.status = "STALE_DATA"
                $summary.message = "Latest data is stale (>3 days)"
            }
            elseif ($summary.missing_tickers_count -gt 5) {
                $summary.status = "PARTIAL_DATA"
                $summary.message = "Missing tickers above threshold"
            }
            elseif ($summary.event_risk_update_status -eq "error") {
                $summary.status = "EVENT_RISK_UPDATE_ERROR"
                $summary.message = "Event-risk auto-update failed"
            }
            elseif ((-not $summary.gate_t1) -and (-not $summary.gate_swing)) {
                if ($summary.kill_switch_active) {
                    $summary.status = "KILL_SWITCH_ACTIVE"
                    $modes = @($summary.kill_switch_modes) -join ","
                    if ([string]::IsNullOrWhiteSpace($modes)) { $modes = "-" }
                    $summary.message = ("Kill-switch active for modes: {0}" -f $modes)
                }
                elseif (-not $summary.regime_ok) {
                    $summary.status = "RISK_OFF_REGIME"
                    $summary.message = "Risk-off regime filter blocked live signals"
                }
                else {
                    $summary.status = "BLOCKED_BY_GATE"
                    $summary.message = "Backtest gate blocked live signals"
                }
            }
            elseif ($summary.signal_count -eq 0) {
                if ($summary.event_risk_excluded_count -gt 0) {
                    $summary.status = "BLOCKED_BY_EVENT_RISK"
                    $summary.message = "All candidate signals were filtered by event-risk blacklist"
                }
                else {
                    $summary.status = "NO_SIGNAL"
                    $summary.message = "No executable signals after filtering"
                }
            }

            $allowedModes = @()
            if ([bool]$summary.gate_t1) { $allowedModes += "t1" }
            if ([bool]$summary.gate_swing) { $allowedModes += "swing" }
            $summary.allowed_modes = $allowedModes

            $isFresh = ($summary.data_age_days -ge 0 -and $summary.data_age_days -le 1)
            $isHealthy = ($summary.missing_tickers_count -le 5)
            $canTrade = (
                $summary.status -eq "SUCCESS" -and
                $summary.signal_count -gt 0 -and
                $allowedModes.Count -gt 0 -and
                $isFresh -and
                $isHealthy
            )
            $summary.trade_ready = [bool]$canTrade

            if ($canTrade) {
                $summary.action = "EXECUTE_MAX_3"
                $summary.action_reason = "Gate passed, signals available, and data is fresh"
            }
            else {
                $summary.action = "NO_TRADE"
                switch ($summary.status) {
                    "BLOCKED_BY_GATE" { $summary.action_reason = "Gate blocked live execution" }
                    "RISK_OFF_REGIME" { $summary.action_reason = "Risk-off regime, do not open new position" }
                    "KILL_SWITCH_ACTIVE" { $summary.action_reason = "Kill-switch cooldown active, preserve capital" }
                    "BLOCKED_BY_EVENT_RISK" { $summary.action_reason = "Event-risk blacklist blocked all candidates" }
                    "NO_SIGNAL" { $summary.action_reason = "No executable signal after filters" }
                    "STALE_DATA" { $summary.action_reason = "Data is stale" }
                    "PARTIAL_DATA" { $summary.action_reason = "Too many missing tickers" }
                    "EVENT_RISK_UPDATE_ERROR" { $summary.action_reason = "Event-risk source update failed" }
                    "FAILED" { $summary.action_reason = "Pipeline failed after retries" }
                    "SETUP_ERROR" { $summary.action_reason = "Environment/setup issue" }
                    default { $summary.action_reason = "Conditions not eligible for execution" }
                }
            }

            $summaryJson = $summary | ConvertTo-Json -Depth 8 -Compress
            $summaryPath = "reports/n8n_last_summary.json"
            $summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8
            Write-Output ("N8N_SUMMARY=" + $summaryJson)
            exit 0
        }

        if ($attempt -lt $maxAttempts) {
            Start-Sleep -Seconds $delays[$attempt - 1]
        }
    }

    $failedSummary = Build-Summary -Ok $false -Status "FAILED" -Message "run-daily failed after retries" -Attempts $attempt -ExitCode $lastExitCode -RunId $runId
    $failedSummary.last_output_tail = ($lastOutput -split "`r?`n" | Select-Object -Last 30) -join "`n"
    $failedJson = $failedSummary | ConvertTo-Json -Depth 8 -Compress
    $failedSummary | ConvertTo-Json -Depth 8 | Set-Content -Path "reports/n8n_last_summary.json" -Encoding UTF8
    Write-Output ("N8N_SUMMARY=" + $failedJson)
    exit 0
}
catch {
    $summary = [ordered]@{
        ok = $false
        status = "SETUP_ERROR"
        message = $_.Exception.Message
        attempts = $attempt
        exit_code = 99
        run_id = $runId
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        signal_count = 0
        gate_t1 = $false
        gate_swing = $false
        gate_model_t1 = $false
        gate_model_swing = $false
        regime_ok = $true
        regime_status = "unknown"
        regime_reason = ""
        kill_switch_active = $false
        kill_switch_modes = @()
        kill_switch_status = "unknown"
        kill_switch_cooldown_until = ""
        universe_update_status = ""
        universe_update_message = ""
        event_risk_update_status = ""
        event_risk_update_message = ""
        event_risk_update_updated = $false
        event_risk_update_rows = 0
        volatility_recalibration_status = ""
        volatility_recalibration_message = ""
        volatility_recalibration_updated = $false
        volatility_recalibration_atr_ref = 0.0
        volatility_recalibration_realized_ref = 0.0
        event_risk_status = ""
        event_risk_excluded_count = 0
        vol_target_market_regime = ""
        vol_target_regime_cap = 0.0
        vol_target_market_vol_index = 0.0
        vol_target_multiplier_avg = 0.0
        vol_target_multiplier_min = 0.0
        vol_target_multiplier_max = 0.0
        data_max_date = ""
        data_age_days = -1
        missing_tickers_count = 0
        allowed_modes = @()
        trade_ready = $false
        action = "NO_TRADE"
        action_reason = "Environment/setup issue"
    }
    $summaryJson = $summary | ConvertTo-Json -Depth 8 -Compress
    $summary | ConvertTo-Json -Depth 8 | Set-Content -Path "reports/n8n_last_summary.json" -Encoding UTF8
    Write-Output ("N8N_SUMMARY=" + $summaryJson)
    exit 0
}
