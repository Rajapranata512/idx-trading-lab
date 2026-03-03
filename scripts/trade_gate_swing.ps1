param(
    [switch]$SkipRun,
    [switch]$DebugReasons
)

$ErrorActionPreference = "Stop"
Set-Location "c:\TRADING\idx-trading-lab"

function Get-JsonSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    if (-not (Test-Path $Path)) { return $null }
    try {
        return Get-Content $Path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Show-DebugReasons {
    param(
        [Parameter(Mandatory = $true)]$Summary
    )
    $funnel = Get-JsonSafe -Path "reports/signal_funnel.json"
    $liveFunnel = Get-JsonSafe -Path "reports/signal_funnel_live.json"
    $bt = Get-JsonSafe -Path "reports/backtest_metrics.json"

    Write-Output ""
    Write-Output "=== Debug Reasons ==="

    if ($null -ne $funnel) {
        if ($null -ne $funnel.modes -and $null -ne $funnel.modes.swing) {
            $sw = $funnel.modes.swing
            Write-Output ("swing.rank_candidates      : {0}" -f [int]$sw.rank_candidates)
            Write-Output ("swing.after_score_filter   : {0}" -f [int]$sw.after_score_filter)
            Write-Output ("swing.after_event_risk     : {0}" -f [int]$sw.after_event_risk)
            Write-Output ("swing.small_size_pre       : {0}" -f [int]$sw.small_size_before_filter)
        }
        if ($null -ne $funnel.combined) {
            $cb = $funnel.combined
            Write-Output ("combined.before_size       : {0}" -f [int]$cb.before_size_filter)
            Write-Output ("combined.drop_size         : {0}" -f [int]$cb.dropped_by_size_filter)
            Write-Output ("combined.after_size        : {0}" -f [int]$cb.after_size_filter)
            Write-Output ("combined.after_topn        : {0}" -f [int]$cb.after_top_n_combined)
            Write-Output ("combined.execution_count   : {0}" -f [int]$cb.execution_plan_count)
            Write-Output ("combined.signal_count      : {0}" -f [int]$cb.signal_count)
        }
    }
    else {
        Write-Output "signal_funnel.json not found."
    }

    if ($null -ne $liveFunnel) {
        Write-Output ("live.allowed_modes         : {0}" -f (@($liveFunnel.allowed_modes) -join ","))
        Write-Output ("live.pre_gate_signals      : {0}" -f [int]$liveFunnel.pre_gate.signal_count)
        if ($null -ne $liveFunnel.pre_gate.by_mode) {
            Write-Output ("live.pre_gate_by_mode      : {0}" -f (($liveFunnel.pre_gate.by_mode.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", "))
        }
        Write-Output ("live.post_gate_signals     : {0}" -f [int]$liveFunnel.post_gate.signal_count)
        if ($null -ne $liveFunnel.post_gate.by_mode) {
            Write-Output ("live.post_gate_by_mode     : {0}" -f (($liveFunnel.post_gate.by_mode.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", "))
        }
    }

    if ($null -ne $bt -and $null -ne $bt.gate_pass) {
        Write-Output ("gate_pass.t1               : {0}" -f [bool]$bt.gate_pass.t1)
        Write-Output ("gate_pass.swing            : {0}" -f [bool]$bt.gate_pass.swing)
    }

    $reasons = New-Object System.Collections.Generic.List[string]
    $status = [string]$Summary.status

    if ($status -eq "NO_SIGNAL") {
        if ($null -ne $funnel -and $null -ne $funnel.modes -and $null -ne $funnel.modes.swing) {
            $sw = $funnel.modes.swing
            $afterScore = [int]$sw.after_score_filter
            $afterEvent = [int]$sw.after_event_risk
            if ([int]$sw.rank_candidates -eq 0) {
                $reasons.Add("Tidak ada kandidat awal dari model swing (rank_candidates=0).")
            }
            elseif ($afterScore -eq 0) {
                $reasons.Add("Semua kandidat swing gugur di threshold score live.")
            }
            elseif ($afterEvent -eq 0) {
                $reasons.Add("Semua kandidat swing terblokir event-risk.")
            }
        }

        if ($null -ne $funnel -and $null -ne $funnel.combined) {
            $cb = $funnel.combined
            if ([int]$cb.after_size_filter -eq 0 -and [int]$cb.before_size_filter -gt 0) {
                $reasons.Add("Semua kandidat gugur di size filter (size < lot minimum).")
            }
        }

        if ($null -ne $liveFunnel) {
            $preGate = [int]$liveFunnel.pre_gate.signal_count
            $postGate = [int]$liveFunnel.post_gate.signal_count
            $preSwing = 0
            if ($null -ne $liveFunnel.pre_gate.by_mode -and $null -ne $liveFunnel.pre_gate.by_mode.swing) {
                $preSwing = [int]$liveFunnel.pre_gate.by_mode.swing
            }
            if ($preGate -gt 0 -and $preSwing -eq 0 -and $postGate -eq 0) {
                $reasons.Add("Kandidat ada, tetapi semuanya bukan mode swing (umumnya tersisa t1).")
            }
            elseif ($preGate -gt 0 -and $postGate -eq 0) {
                $reasons.Add("Kandidat ada sebelum gate final, namun habis setelah filtering live.")
            }
        }

        if ($reasons.Count -eq 0) {
            $reasons.Add("Tidak ada kandidat executable setelah seluruh filter aktif.")
        }
    }
    elseif ($status -eq "BLOCKED_BY_GATE") {
        $reasons.Add("Model gate tidak meloloskan mode untuk eksekusi live.")
    }
    elseif ($status -eq "RISK_OFF_REGIME") {
        $reasons.Add("Market regime sedang risk-off.")
    }
    elseif ($status -eq "KILL_SWITCH_ACTIVE") {
        $reasons.Add("Kill-switch aktif (cooldown capital protection).")
    }
    elseif ($status -eq "FAILED" -or $status -eq "SETUP_ERROR") {
        $reasons.Add("Pipeline teknis gagal, cek run_log dan last_output_tail.")
    }

    Write-Output ""
    Write-Output "Likely Causes:"
    foreach ($r in $reasons) {
        Write-Output ("- {0}" -f $r)
    }
}

if (-not $SkipRun) {
    Write-Output "Running daily pipeline with retry..."
    & "c:\TRADING\idx-trading-lab\scripts\run_daily_retry.ps1"
}

$summaryPath = "reports/n8n_last_summary.json"
$signalPath = "reports/daily_signal.json"
if (-not (Test-Path $summaryPath)) {
    throw "Summary file not found: $summaryPath"
}

$s = Get-Content $summaryPath -Raw | ConvertFrom-Json
$allowedModes = @($s.allowed_modes)
$isGateOk = (
    $s.status -eq "SUCCESS" -and
    [bool]$s.trade_ready -eq $true -and
    ($allowedModes -contains "swing") -and
    [int]$s.data_age_days -le 1 -and
    [int]$s.missing_tickers_count -le 5
)

Write-Output "=== Swing Trade Gate ==="
Write-Output ("status               : {0}" -f $s.status)
Write-Output ("trade_ready          : {0}" -f $s.trade_ready)
Write-Output ("allowed_modes        : {0}" -f ($allowedModes -join ","))
Write-Output ("data_age_days        : {0}" -f $s.data_age_days)
Write-Output ("missing_tickers_count: {0}" -f $s.missing_tickers_count)
Write-Output ("vol_regime           : {0}" -f $s.vol_target_market_regime)
Write-Output ("vol_regime_cap       : {0}" -f $s.vol_target_regime_cap)
Write-Output ("decision             : {0}" -f $(if ($isGateOk) { "TRADE_OK" } else { "NO_TRADE" }))
Write-Output ("reason               : {0}" -f $s.action_reason)

if (-not $isGateOk) {
    if ($DebugReasons) {
        Show-DebugReasons -Summary $s
    }
    else {
        Write-Output ""
        Write-Output "Hint: jalankan lagi dengan -DebugReasons untuk melihat alasan kandidat gugur."
    }
    exit 0
}

if (-not (Test-Path $signalPath)) {
    Write-Output "Signal file not found: $signalPath"
    exit 0
}

$signals = (Get-Content $signalPath -Raw | ConvertFrom-Json).signals |
    Where-Object { $_.mode -eq "swing" } |
    Sort-Object { [double]$_.score } -Descending |
    Select-Object -First 3

if (@($signals).Count -eq 0) {
    Write-Output "No swing signals available after filters."
    if ($DebugReasons) {
        Show-DebugReasons -Summary $s
    }
    else {
        Write-Output ""
        Write-Output "Hint: jalankan lagi dengan -DebugReasons untuk melihat detail funnel."
    }
    exit 0
}

Write-Output ""
Write-Output "Top Swing Picks (max 3):"
$signals | Format-Table ticker, mode, score, entry, stop, tp1, tp2, size
