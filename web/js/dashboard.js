(function(){
'use strict';
const S={page:'overview',data:{},charts:{}};
const P={
  backtest:'./reports/backtest_metrics.json',
  kpi:'./reports/weekly_kpi.json',
  funnel:'./reports/signal_funnel.json',
  shadow:'./reports/model_v2_shadow_signals.json',
  promo:'./reports/model_v2_promotion_state.json',
  accuracy:'./reports/model_v2_accuracy_audit.json',
  recon:'./reports/live_reconciliation.json',
  topT1:'./reports/top_t1.csv',
  topSwing:'./reports/top_swing.csv',
  eventActive:'./reports/event_risk_active.csv'
};

// ── Helpers ──
const $=s=>document.querySelector(s);
const fmt=(n,d=2)=>n==null?'—':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtPct=n=>n==null?'—':fmt(n,2)+'%';
const fmtIDR=n=>n==null?'—':'Rp'+Number(n).toLocaleString('id-ID');
const scoreClass=s=>s>=95?'high':s>=80?'mid':'low';
const scoreBadge=s=>s>=95?'success':s>=80?'warning':'danger';
const asNum=n=>{const v=Number(n);return Number.isFinite(v)?v:null;};
const fmtNum=(n,d=2)=>{const v=asNum(n);return v==null?'-':v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});};
const fmtPctNum=(n,d=2)=>{const v=asNum(n);return v==null?'-':fmtNum(v,d)+'%';};
const fmtSignedR=(n,d=4)=>{const v=asNum(n);if(v==null)return '-';return `${v>=0?'+':''}${fmtNum(v,d)}R`;};

async function fetchJSON(p){try{const r=await fetch(p + '?t=' + Date.now());if(!r.ok)return null;return r.json();}catch{return null;}}
async function fetchCSV(p){return new Promise(r=>{Papa.parse(p + '?t=' + Date.now(),{download:true,header:true,dynamicTyping:true,skipEmptyLines:true,complete:d=>r(d.data),error:()=>r([])});});}

function toast(msg,type='info'){
  const c=$('#toastContainer'),t=document.createElement('div');
  t.className='toast '+type;t.textContent=msg;c.appendChild(t);
  setTimeout(()=>{t.classList.add('toast-exit');setTimeout(()=>t.remove(),300);},3500);
}

// ── Data Loading ──
async function loadAll(){
  const[bt,kpi,fun,shd,prm,acc,rec,t1,sw,ev]=await Promise.all([
    fetchJSON(P.backtest),fetchJSON(P.kpi),fetchJSON(P.funnel),
    fetchJSON(P.shadow),fetchJSON(P.promo),fetchJSON(P.accuracy),fetchJSON(P.recon),
    fetchCSV(P.topT1),fetchCSV(P.topSwing),fetchCSV(P.eventActive)
  ]);
  S.data={backtest:bt,kpi:kpi,funnel:fun,shadow:shd,promo:prm,accuracy:acc,recon:rec,topT1:t1,topSwing:sw,eventActive:ev};
  const gen=bt?.generated_at||'';
  // ── Data Freshness Warning ──
  let freshnessClass='freshness-dot';
  let staleWarning='';
  if(gen){
    const genDate=new Date(gen);
    const now=new Date();
    const ageDays=Math.floor((now-genDate)/(1000*60*60*24));
    if(ageDays>7){
      freshnessClass='freshness-dot stale-critical';
      staleWarning=`<div class="stale-banner stale-critical-bg" id="staleBanner">⚠️ Data terakhir diupdate <strong>${ageDays} hari lalu</strong> (${gen.slice(0,10)}). Pipeline harian mungkin berhenti. Jangan gunakan sinyal ini untuk keputusan trading.</div>`;
    }else if(ageDays>1){
      freshnessClass='freshness-dot stale-warning';
      staleWarning=`<div class="stale-banner stale-warning-bg" id="staleBanner">⚠️ Data sudah <strong>${ageDays} hari</strong> tidak diperbarui (${gen.slice(0,10)}). Sinyal mungkin tidak akurat.</div>`;
    }
  }else{
    staleWarning='<div class="stale-banner stale-critical-bg" id="staleBanner">❌ Tidak ada data tersedia. Pastikan pipeline harian berjalan.</div>';
  }
  // Remove old banner if exists, then inject new one
  document.getElementById('staleBanner')?.remove();
  if(staleWarning){
    const main=$('#mainContent');
    if(main) main.insertAdjacentHTML('afterbegin',staleWarning);
  }
  $('#dataFreshness').innerHTML=`<div class="${freshnessClass}"></div><span>${gen?gen.slice(0,16):'No data'}</span>`;
  const st=$('#systemStatus');
  const regime=bt?.regime;
  if(regime){
    const ok=regime.pass;
    st.innerHTML=`<div class="status-dot ${ok?'pulse':'offline'}"></div><span>Regime: ${ok?'Risk On':'Risk Off'}</span>`;
  }
  $('#loadingScreen')?.remove();
  toast('Data loaded','success');
}

// ── Router ──
function navigate(page){
  S.page=page;
  Object.values(S.charts).forEach(c=>{try{c.destroy();}catch{}});S.charts={};
  document.querySelectorAll('.nav-item').forEach(n=>{
    n.classList.toggle('active',n.dataset.page===page);
  });
  const titles={overview:['Overview','Real-time trading signal dashboard'],signals:['Signals','T+1 and Swing signal picks'],
    performance:['Performance','Backtest metrics & walk-forward analysis'],risk:['Risk & Regime','Market regime and risk parameters'],
    model:['Model v2','Shadow model monitoring'],operations:['Operations','Event risk & reconciliation']};
  const[t,sub]=titles[page]||['',''];
  $('#pageTitle').textContent=t;$('#pageSubtitle').textContent=sub;
  const area=$('#contentArea');
  area.innerHTML='';area.style.animation='none';area.offsetHeight;area.style.animation='fadeIn 0.35s var(--ease)';
  const renderers={overview:renderOverview,signals:renderSignals,performance:renderPerformance,
    risk:renderRisk,model:renderModel,operations:renderOperations};
  (renderers[page]||renderOverview)();
}

// ═══ PAGE: OVERVIEW ═══
function renderOverview(){
  const d=S.data,bt=d.backtest||{},r=bt.regime||{},ks=bt.kill_switch||{},fun=d.funnel||{},kpi=d.kpi||{};
  const sw=bt.metrics?.swing||{},t1=bt.metrics?.t1||{};
  const nT1=(d.topT1||[]).length,nSw=(d.topSwing||[]).length;
  const regimeOk=r.pass;
  const ksActive=ks.active;
  const html=`
<div class="grid grid-4 mb-24">
  ${kpiCard('Total Signals',nT1+nSw,'⚡','accent')}
  ${kpiCard('Regime',regimeOk?'RISK ON':'RISK OFF',regimeOk?'✓':'✕',regimeOk?'success':'danger')}
  ${kpiCard('Kill Switch',ksActive?'ACTIVE':'OK',ksActive?'⚠':'✓',ksActive?'danger':'success')}
  ${kpiCard('Swing Win%',fmtPct(sw.WinRate),'📊','info')}
</div>
<div class="grid grid-2 mb-24">
  <div class="card">
    <div class="card-header"><span class="card-title">Market Regime</span>${badgeHtml(regimeOk?'Risk On':'Risk Off',regimeOk?'success':'danger')}</div>
    <div class="checks-grid">
      ${regimeCheck('MA50 Breadth',r.values?.breadth_ma50_pct,r.thresholds?.min_breadth_ma50_pct,r.checks?.breadth_ma50_ok,'≥')}
      ${regimeCheck('MA20 Breadth',r.values?.breadth_ma20_pct,r.thresholds?.min_breadth_ma20_pct,r.checks?.breadth_ma20_ok,'≥')}
      ${regimeCheck('Avg Ret 20D',r.values?.avg_ret20_pct,r.thresholds?.min_avg_ret20_pct,r.checks?.avg_ret20_ok,'≥')}
      ${regimeCheck('Median ATR',r.values?.median_atr_pct,r.thresholds?.max_median_atr_pct,r.checks?.median_atr_ok,'≤')}
    </div>
  </div>
  <div class="card">
    <div class="card-header"><span class="card-title">Signal Funnel</span></div>
    ${renderFunnel(fun)}
  </div>
</div>
<div class="grid grid-2">
  <div class="card">
    <div class="card-header"><span class="card-title">Gate Status</span></div>
    ${gateTable(bt)}
  </div>
  <div class="card">
    <div class="card-header"><span class="card-title">Backtest Summary</span></div>
    <div class="grid grid-2 gap-12">
      <div>
        <div class="mb-8"><span class="badge badge-info">T+1</span></div>
        ${metricRow('Win Rate',fmtPct(t1.WinRate))}${metricRow('Profit Factor',fmt(t1.ProfitFactor))}
        ${metricRow('Expectancy',fmt(t1.Expectancy,4))}${metricRow('Max DD',fmtPct(t1.MaxDD))}
        ${metricRow('Trades',t1.Trades)}
      </div>
      <div>
        <div class="mb-8"><span class="badge badge-accent">Swing</span></div>
        ${metricRow('Win Rate',fmtPct(sw.WinRate))}${metricRow('Profit Factor',fmt(sw.ProfitFactor))}
        ${metricRow('Expectancy',fmt(sw.Expectancy,4))}${metricRow('Max DD',fmtPct(sw.MaxDD))}
        ${metricRow('Trades',sw.Trades)}
      </div>
    </div>
  </div>
</div>`;
  $('#contentArea').innerHTML=html;
}

// ═══ PAGE: SIGNALS ═══
function renderSignals(){
  const t1=S.data.topT1||[],sw=S.data.topSwing||[];
  let html=`<div class="section-header"><div><div class="section-title">Top T+1 Picks</div><div class="section-subtitle">${t1.length} signals</div></div></div>`;
  if(!t1.length)html+=emptyState('No T+1 signals');
  else html+=`<div class="grid grid-auto mb-24">${t1.map(s=>signalCard(s,'t1')).join('')}</div>`;
  html+=`<div class="section-header mt-24"><div><div class="section-title">Top Swing Picks</div><div class="section-subtitle">${sw.length} signals</div></div></div>`;
  if(!sw.length)html+=emptyState('No Swing signals');
  else html+=`<div class="grid grid-auto">${sw.map(s=>signalCard(s,'swing')).join('')}</div>`;
  $('#contentArea').innerHTML=html;
}

// ═══ PAGE: PERFORMANCE ═══
function renderPerformance(){
  const bt=S.data.backtest||{},wf=bt.walk_forward||{};
  const html=`
<div class="grid grid-2 mb-24">
  <div class="card"><div class="card-header"><span class="card-title">Walk-Forward: T+1</span></div>
    <div class="chart-container"><canvas id="chartWfT1"></canvas></div></div>
  <div class="card"><div class="card-header"><span class="card-title">Walk-Forward: Swing</span></div>
    <div class="chart-container"><canvas id="chartWfSwing"></canvas></div></div>
</div>
<div class="grid grid-2">
  <div class="card"><div class="card-header"><span class="card-title">Win Rate Comparison</span></div>
    <div class="chart-container"><canvas id="chartWR"></canvas></div></div>
  <div class="card"><div class="card-header"><span class="card-title">CAGR by Fold</span></div>
    <div class="chart-container"><canvas id="chartCAGR"></canvas></div></div>
</div>`;
  $('#contentArea').innerHTML=html;
  setTimeout(()=>{
    renderWFChart('chartWfT1',wf.modes?.t1);
    renderWFChart('chartWfSwing',wf.modes?.swing);
    renderCompChart('chartWR','WinRate',bt);
    renderCAGRChart('chartCAGR',wf);
  },50);
}

// ═══ PAGE: RISK ═══
function renderRisk(){
  const bt=S.data.backtest||{},r=bt.regime||{},ks=bt.kill_switch_eval||{};
  const html=`
<div class="grid grid-2 mb-24">
  <div class="card">
    <div class="card-header"><span class="card-title">Regime Status</span>${badgeHtml(r.status||'unknown',r.pass?'success':'danger')}</div>
    <div class="checks-grid">
      ${regimeCheck('MA50 Breadth',r.values?.breadth_ma50_pct,r.thresholds?.min_breadth_ma50_pct,r.checks?.breadth_ma50_ok,'≥')}
      ${regimeCheck('MA20 Breadth',r.values?.breadth_ma20_pct,r.thresholds?.min_breadth_ma20_pct,r.checks?.breadth_ma20_ok,'≥')}
      ${regimeCheck('Avg Ret 20D',r.values?.avg_ret20_pct,r.thresholds?.min_avg_ret20_pct,r.checks?.avg_ret20_ok,'≥')}
      ${regimeCheck('Median ATR',r.values?.median_atr_pct,r.thresholds?.max_median_atr_pct,r.checks?.median_atr_ok,'≤')}
    </div>
  </div>
  <div class="card">
    <div class="card-header"><span class="card-title">Kill Switch Evaluation</span></div>
    ${Object.entries(ks.modes||{}).map(([m,v])=>`
      <div class="mb-16"><span class="badge badge-${v.triggered?'danger':'success'}">${m.toUpperCase()}</span>
      ${metricRow('Rolling PF',fmt(v.rolling_pf))}${metricRow('Rolling Exp.',fmt(v.rolling_expectancy,4))}
      ${metricRow('Trades',v.trades_recent)}${metricRow('Triggered',v.triggered?'YES':'NO')}
      </div>`).join('')}
  </div>
</div>
<div class="card">
  <div class="card-header"><span class="card-title">Gate Components</span></div>
  ${gateTable(bt)}
</div>`;
  $('#contentArea').innerHTML=html;
}

// ═══ PAGE: MODEL V2 ═══
function renderModel(){
  const sh=S.data.shadow||{},pr=S.data.promo||{},audit=S.data.accuracy||{};
  const sigs=sh.signals||[];
  const modelSigs=sigs.filter(s=>String(s.shadow_model_source||'').toLowerCase()==='model');
  const blockedCount=sigs.length-modelSigs.length;
  const modelReady=blockedCount===0&&modelSigs.length>0;
  const sourceWarning=blockedCount>0?`<div class="stale-banner stale-critical-bg mb-24">Model V2 BLOCKED: ${blockedCount} kandidat tidak memakai model terlatih. P(Win), E[R], rekomendasi, dan final decision dinonaktifkan untuk kandidat tersebut.</div>`:'';
  const html=`
<div class="grid grid-3 mb-24">
  ${kpiCard('Model Ready',modelReady?'YES':'NO','🤖',modelReady?'success':'danger')}
  ${kpiCard('Train Status',sh.train?.status||'—','📊','info')}
  ${kpiCard('Rollout',pr.current_rollout_pct!=null?pr.current_rollout_pct+'%':'0%','🚀','success')}
</div>
${sourceWarning}
<div class="card mb-24">
  <div class="card-header"><span class="card-title">Shadow Signals</span></div>
  <div class="table-wrapper"><table class="data-table"><thead><tr>
    <th>Rank</th><th>Ticker</th><th>Mode</th><th>Source</th><th>Score</th><th>P(Win)</th><th>E[R]</th><th>Threshold</th><th>Recommended</th><th>Entry</th><th>Stop</th><th>TP1</th>
  </tr></thead><tbody>
    ${sigs.map(s=>`<tr>
      <td>${s.shadow_rank}</td><td class="fw-700">${s.ticker}</td>
      <td><span class="badge badge-${s.mode==='swing'?'accent':'info'}">${s.mode}</span></td>
      <td>${String(s.shadow_model_source||'').toLowerCase()==='model'?'<span class="badge badge-success">MODEL</span>':'<span class="badge badge-danger">BLOCKED</span>'}</td>
      <td class="mono">${fmt(s.score)}</td>
      <td class="mono ${String(s.shadow_model_source||'').toLowerCase()==='model'&&s.shadow_p_win>=s.shadow_threshold?'text-success':'text-danger'}">${fmt(s.shadow_p_win,4)}</td>
      <td class="mono">${fmt(s.shadow_expected_r,4)}</td>
      <td class="mono text-muted">${fmt(s.shadow_threshold,2)}</td>
      <td>${String(s.shadow_model_source||'').toLowerCase()!=='model'?'<span class="badge badge-danger">BLOCKED</span>':s.shadow_recommended?'<span class="badge badge-success">YES</span>':'<span class="badge badge-neutral">NO</span>'}</td>
      <td class="mono">${fmtIDR(s.entry)}</td><td class="mono text-danger">${fmtIDR(s.stop)}</td><td class="mono text-success">${fmtIDR(s.tp1)}</td>
    </tr>`).join('')}
  </tbody></table></div>
</div>
${renderAccuracyAudit(audit)}
<div class="grid grid-2">
  <div class="card"><div class="card-header"><span class="card-title">Model Training Info</span></div>
    ${Object.entries(sh.train?.modes||{}).map(([m,v])=>`<div class="mb-16"><span class="badge badge-info">${m}</span>
      ${metricRow('Rows',v.train_rows)}${metricRow('AUC',fmt(v.auc_train,4))}${metricRow('Positive Rate',fmtPct(v.positive_rate*100))}
    </div>`).join('')}
  </div>
  <div class="card"><div class="card-header"><span class="card-title">Promotion State</span></div>
    ${metricRow('Current Rollout',pr.current_rollout_pct!=null?pr.current_rollout_pct+'%':'0%')}
    ${metricRow('Consecutive Passes',pr.consecutive_passes||0)}
    ${metricRow('Final Decision',pr.final_decision_ready?'READY':'BLOCKED')}
    ${metricRow('Last Eval',pr.last_evaluated_at||'—')}
  </div>
</div>`;
  $('#contentArea').innerHTML=html;
}

// ═══ PAGE: OPERATIONS ═══
function renderOperations(){
  const rec=S.data.recon||{},ev=S.data.eventActive||[];
  const html=`
<div class="grid grid-3 mb-24">
  ${kpiCard('Recon Status',rec.status||'—','🔄',rec.status==='ok'?'success':'warning')}
  ${kpiCard('Match Rate',fmtPct(rec.coverage?.entry_match_rate_pct),'🎯','info')}
  ${kpiCard('Active Events',ev.length,'⚠','warning')}
</div>
<div class="grid grid-2 mb-24">
  <div class="card"><div class="card-header"><span class="card-title">Reconciliation Summary</span></div>
    ${metricRow('Signals Total',rec.counts?.signals_total||0)}
    ${metricRow('Matched',rec.counts?.matched_signals||0)}
    ${metricRow('Unmatched',rec.counts?.unmatched_signals||0)}
    ${metricRow('Win Rate',fmtPct(rec.realized_kpi?.win_rate_pct))}
    ${metricRow('Expectancy (R)',fmt(rec.realized_kpi?.expectancy_r,4))}
    ${metricRow('PF (R)',fmt(rec.realized_kpi?.profit_factor_r))}
  </div>
  <div class="card"><div class="card-header"><span class="card-title">Cost Analysis</span></div>
    ${metricRow('Avg Entry Slippage',fmtPct(rec.cost_kpi?.avg_entry_slippage_pct))}
    ${metricRow('Avg Roundtrip Cost',fmtPct(rec.cost_kpi?.avg_est_roundtrip_cost_pct))}
    ${metricRow('Total Fees',fmtIDR(rec.cost_kpi?.total_fee_idr))}
  </div>
</div>
<div class="card">
  <div class="card-header"><span class="card-title">Active Event Risk</span><span class="badge badge-warning">${ev.length} active</span></div>
  ${ev.length?`<div class="table-wrapper"><table class="data-table"><thead><tr>
    <th>Ticker</th><th>Status</th><th>Reason</th><th>Start</th><th>End</th><th>Source</th>
  </tr></thead><tbody>${ev.map(e=>`<tr>
    <td class="fw-700">${e.ticker||''}</td>
    <td><span class="badge badge-danger">${e.status||''}</span></td>
    <td>${e.reason||''}</td><td class="mono">${e.start_date||''}</td>
    <td class="mono">${e.end_date||''}</td><td class="text-muted">${e.source||''}</td>
  </tr>`).join('')}</tbody></table></div>`:emptyState('No active events')}
</div>`;
  $('#contentArea').innerHTML=html;
}

// ── Component Builders ──
function kpiCard(title,value,icon,color){
  return`<div class="card kpi-card ${color}"><div class="card-header"><span class="card-title">${title}</span><div class="card-icon ${color}">${icon}</div></div><div class="card-value">${value}</div></div>`;
}
function badgeHtml(text,type){return`<span class="badge badge-${type}"><span class="badge-dot"></span>${text}</span>`;}
function metricRow(label,value){return`<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${value}</span></div>`;}
function emptyState(msg){return`<div class="empty-state"><div class="empty-icon">∅</div><p>${msg}</p></div>`;}

function regimeCheck(name,val,thresh,ok,op){
  return`<div class="check-item ${ok?'pass':'fail'}"><span class="check-icon">${ok?'✓':'✕'}</span>
    <span>${name} (${op}${fmt(thresh,1)})</span><span class="check-value">${fmt(val,1)}</span></div>`;
}

function signalCard(s,mode){
  const sc=s.score||0;const cls=scoreClass(sc);
  return`<div class="card signal-card score-${cls}">
    <div class="signal-header"><div>
      <div class="signal-ticker">${s.ticker}</div>
      <div class="signal-meta"><span class="badge badge-${mode==='swing'?'accent':'info'}">${mode==='swing'?'Swing 1-4w':'T+1'}</span>
        <span class="badge badge-neutral">Rank #${s.rank||'—'}</span></div>
    </div><div class="signal-score ${cls}">${fmt(sc,1)}</div></div>
    <div class="signal-prices">
      <div class="price-item"><label>Entry</label><div class="price-val entry">${fmtIDR(s.entry)}</div></div>
      <div class="price-item"><label>Stop</label><div class="price-val stop">${fmtIDR(s.stop)}</div></div>
      <div class="price-item"><label>TP1</label><div class="price-val tp">${fmtIDR(s.tp1)}</div></div>
      <div class="price-item"><label>TP2</label><div class="price-val tp">${fmtIDR(s.tp2)}</div></div>
    </div>
    <div class="signal-details">
      <div class="signal-detail"><span class="detail-label">Size</span>${s.size} lots</div>
      <div class="signal-detail"><span class="detail-label">Vol Mult</span>${fmt(s.vol_target_multiplier,2)}x</div>
      <div class="signal-detail"><span class="detail-label">Regime</span>${s.vol_target_market_regime||'—'}</div>
    </div>
    <div class="signal-reason">${s.reason||'—'}</div>
  </div>`;
}

function firstMetric(row,keys){
  for(const key of keys){if(row?.[key]!=null)return row[key];}
  return null;
}

function metricTone(value,good,warn){
  const v=asNum(value);
  if(v==null)return 'neutral';
  if(v>=good)return 'success';
  if(v>=warn)return 'warning';
  return 'danger';
}

function inverseMetricTone(value,goodMax,warnMax){
  const v=asNum(value);
  if(v==null)return 'neutral';
  if(v<=goodMax)return 'success';
  if(v<=warnMax)return 'warning';
  return 'danger';
}

function bestThresholdRecord(thresholds){
  const rows=Object.values(thresholds||{}).filter(Boolean);
  rows.sort((a,b)=>{
    const ae=asNum(a.expectancy_r),be=asNum(b.expectancy_r);
    const ap=asNum(a.profit_factor_r),bp=asNum(b.profit_factor_r);
    return (be??-999)-(ae??-999)||(bp??-999)-(ap??-999);
  });
  return rows[0]||{};
}

function auditMetric(label,value,sub,tone){
  return`<div class="audit-metric ${tone||'neutral'}">
    <div class="audit-label">${label}</div>
    <div class="audit-value">${value}</div>
    <div class="audit-sub">${sub||'&nbsp;'}</div>
  </div>`;
}

function weakTickerRows(audit){
  const weak=audit.false_positive_summary?.weak_groups?.ticker||[];
  const fallback=(audit.by_ticker_preview||[]).filter(r=>
    (asNum(r.v2_recommended_count)||0)>0 &&
    ((asNum(r.v2_expectancy_r)||0)<0 || (asNum(r.v2_precision_pct)||0)<50)
  );
  const rows=(weak.length?weak:fallback).slice();
  rows.sort((a,b)=>(asNum(firstMetric(a,['v2_expectancy_r','expectancy_r']))??999)-(asNum(firstMetric(b,['v2_expectancy_r','expectancy_r']))??999));
  return rows.slice(0,6);
}

function weakRegimeRows(audit){
  const weak=audit.false_positive_summary?.weak_groups?.regime||[];
  const fallback=(audit.by_regime||[]).filter(r=>(asNum(r.v2_recommended_count)||0)>0);
  const rows=(weak.length?weak:fallback).slice();
  rows.sort((a,b)=>(asNum(firstMetric(a,['v2_expectancy_r','expectancy_r']))??999)-(asNum(firstMetric(b,['v2_expectancy_r','expectancy_r']))??999));
  return rows.slice(0,6);
}

function renderWeakTickerTable(rows){
  if(!rows.length)return emptyState('No weak ticker groups');
  return`<div class="table-wrapper audit-table"><table class="data-table"><thead><tr>
    <th>Ticker</th><th>Trades</th><th>Precision</th><th>E[R]</th><th>PF</th>
  </tr></thead><tbody>${rows.map(r=>`<tr>
    <td class="fw-700">${r.ticker||'-'}</td>
    <td class="mono">${firstMetric(r,['v2_recommended_count','trade_count'])??0}</td>
    <td class="mono">${fmtPctNum(firstMetric(r,['v2_precision_pct','precision_pct']))}</td>
    <td class="mono ${asNum(firstMetric(r,['v2_expectancy_r','expectancy_r']))>=0?'text-success':'text-danger'}">${fmtSignedR(firstMetric(r,['v2_expectancy_r','expectancy_r']))}</td>
    <td class="mono">${fmtNum(firstMetric(r,['v2_profit_factor_r','profit_factor_r']))}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function renderWeakRegimeTable(rows){
  if(!rows.length)return emptyState('No weak regime groups');
  return`<div class="table-wrapper audit-table"><table class="data-table"><thead><tr>
    <th>Mode</th><th>Regime</th><th>Trades</th><th>Precision</th><th>E[R]</th><th>PF</th>
  </tr></thead><tbody>${rows.map(r=>`<tr>
    <td><span class="badge badge-${r.mode==='swing'?'accent':'info'}">${(r.mode||'-').toUpperCase()}</span></td>
    <td>${r.regime_status||r.shadow_market_regime||'-'}</td>
    <td class="mono">${firstMetric(r,['v2_recommended_count','trade_count'])??0}</td>
    <td class="mono">${fmtPctNum(firstMetric(r,['v2_precision_pct','precision_pct']))}</td>
    <td class="mono ${asNum(firstMetric(r,['v2_expectancy_r','expectancy_r']))>=0?'text-success':'text-danger'}">${fmtSignedR(firstMetric(r,['v2_expectancy_r','expectancy_r']))}</td>
    <td class="mono">${fmtNum(firstMetric(r,['v2_profit_factor_r','profit_factor_r']))}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function renderThresholdTable(rows){
  if(!rows.length)return emptyState('No threshold candidates');
  return`<div class="table-wrapper audit-table"><table class="data-table"><thead><tr>
    <th>Mode</th><th>Threshold</th><th>Trades</th><th>Precision</th><th>E[R]</th><th>PF</th>
  </tr></thead><tbody>${rows.slice(0,8).map(r=>`<tr>
    <td><span class="badge badge-${r.mode==='swing'?'accent':'info'}">${(r.mode||'-').toUpperCase()}</span></td>
    <td class="mono">${fmtNum(r.threshold,2)}</td>
    <td class="mono">${r.trade_count??0}</td>
    <td class="mono">${fmtPctNum(r.precision_pct)}</td>
    <td class="mono ${asNum(r.expectancy_r)>=0?'text-success':'text-danger'}">${fmtSignedR(r.expectancy_r)}</td>
    <td class="mono">${fmtNum(r.profit_factor_r)}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function renderCalibrationTable(rows){
  if(!rows.length)return emptyState('No calibration bins');
  return`<div class="table-wrapper audit-table"><table class="data-table"><thead><tr>
    <th>Bin</th><th>Samples</th><th>Predicted</th><th>Actual</th><th>Error</th>
  </tr></thead><tbody>${rows.map(r=>`<tr>
    <td class="mono">${r.bin||'-'}</td>
    <td class="mono">${r.sample_count??0}</td>
    <td class="mono">${fmtPctNum(r.avg_predicted_p_win_pct)}</td>
    <td class="mono">${fmtPctNum(r.actual_win_rate_pct)}</td>
    <td class="mono ${inverseMetricTone(r.abs_error_pct,10,20)==='danger'?'text-danger':inverseMetricTone(r.abs_error_pct,10,20)==='warning'?'text-warning':'text-success'}">${fmtPctNum(r.abs_error_pct)}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function renderFalsePositiveExamples(rows){
  if(!rows.length)return '';
  return`<div class="audit-panel mt-16">
    <div class="audit-panel-title">Worst False-Positive Examples</div>
    <div class="table-wrapper audit-table"><table class="data-table"><thead><tr>
      <th>Date</th><th>Ticker</th><th>Mode</th><th>Score</th><th>Regime</th><th>Outcome</th><th>Realized R</th><th>MAE R</th>
    </tr></thead><tbody>${rows.slice(0,6).map(r=>`<tr>
      <td class="mono">${r.date||'-'}</td>
      <td class="fw-700">${r.ticker||'-'}</td>
      <td><span class="badge badge-${r.mode==='swing'?'accent':'info'}">${(r.mode||'-').toUpperCase()}</span></td>
      <td class="mono">${fmtNum(r.score,2)}</td>
      <td>${r.regime_status||'-'}</td>
      <td>${r.outcome||'-'}</td>
      <td class="mono text-danger">${fmtSignedR(r.realized_r)}</td>
      <td class="mono text-danger">${fmtSignedR(r.mae_r)}</td>
    </tr>`).join('')}</tbody></table></div>
  </div>`;
}

function renderAccuracyAudit(audit){
  if(!audit||!Object.keys(audit).length){
    return`<div class="card mb-24"><div class="card-header"><span class="card-title">Model V2 Accuracy Audit</span>${badgeHtml('missing','danger')}</div>${emptyState('Model V2 accuracy audit not available')}</div>`;
  }
  const v2=audit.v2_recommended||{};
  const best=bestThresholdRecord(audit.best_thresholds);
  const calib=audit.calibration_v2_recommended||audit.calibration_all_candidates||{};
  const fp=audit.false_positive_summary||{};
  const input=audit.input||{};
  const bestMode=best.mode?String(best.mode).toUpperCase():'-';
  const bestThreshold=best.threshold!=null?`${bestMode} >= ${fmtNum(best.threshold,2)}`:'-';
  const tickerRows=weakTickerRows(audit);
  const regimeRows=weakRegimeRows(audit);
  const thresholdRows=(audit.threshold_candidates_preview||[]).slice();
  const calibrationRows=(calib.bins||[]).slice();
  return`
<div class="card mb-24">
  <div class="card-header"><span class="card-title">Model V2 Accuracy Audit</span>${badgeHtml(audit.status||'missing',audit.status==='ok'?'success':'danger')}</div>
  <div class="audit-meta">
    Generated ${audit.generated_at?audit.generated_at.slice(0,16):'-'} | audited trades ${input.audited_trade_count??0} | V2 recommended ${input.v2_recommended_count??0}
  </div>
  <div class="audit-metric-grid">
    ${auditMetric('Expectancy',fmtSignedR(v2.expectancy_r),`${v2.trade_count??0} V2 trades`,metricTone(v2.expectancy_r,0,-0.05))}
    ${auditMetric('Profit Factor',fmtNum(v2.profit_factor_r),`precision ${fmtPctNum(v2.precision_pct)}`,metricTone(v2.profit_factor_r,1.1,0.9))}
    ${auditMetric('Best Threshold',bestThreshold,`${fmtSignedR(best.expectancy_r)} | PF ${fmtNum(best.profit_factor_r)}`,metricTone(best.expectancy_r,0,-0.05))}
    ${auditMetric('Calibration Error',fmtPctNum(calib.ece_pct),`source ${calib.source||'-'}`,inverseMetricTone(calib.ece_pct,10,20))}
    ${auditMetric('False Positive',fmtPctNum(fp.negative_signal_rate_pct),`${fp.negative_signal_count??0} negative signals`,inverseMetricTone(fp.negative_signal_rate_pct,30,50))}
  </div>
  <div class="grid grid-2 mt-16">
    <div class="audit-panel"><div class="audit-panel-title">Weak Tickers</div>${renderWeakTickerTable(tickerRows)}</div>
    <div class="audit-panel"><div class="audit-panel-title">Weak Regimes</div>${renderWeakRegimeTable(regimeRows)}</div>
  </div>
  <div class="grid grid-2 mt-16">
    <div class="audit-panel"><div class="audit-panel-title">Threshold Candidates</div>${renderThresholdTable(thresholdRows)}</div>
    <div class="audit-panel"><div class="audit-panel-title">Calibration Bins</div>${renderCalibrationTable(calibrationRows)}</div>
  </div>
  ${renderFalsePositiveExamples(fp.worst_false_positive_examples||[])}
</div>`;
}

function renderFunnel(fun){
  const t1=fun.modes?.t1||{},sw=fun.modes?.swing||{},cb=fun.combined||{};
  const max=Math.max(t1.rank_candidates||0,sw.rank_candidates||0,cb.signal_count||1);
  const steps=[
    ['T1 Candidates',t1.rank_candidates,'var(--info)'],
    ['T1 After Score',t1.after_score_filter,'var(--accent)'],
    ['SW Candidates',sw.rank_candidates,'var(--accent-hover)'],
    ['SW After Score',sw.after_score_filter,'var(--success)'],
    ['Combined',cb.signal_count,'var(--warning)'],
    ['Exec Plan',cb.execution_plan_count,'var(--success)'],
  ];
  return steps.map(([l,v,c])=>{
    const pct=max?Math.max((v/max)*100,8):0;
    return`<div class="funnel-step"><span class="funnel-label">${l}</span><div class="funnel-bar"><div class="funnel-fill" style="width:${pct}%;background:${c}">${v||0}</div></div><span class="funnel-count">${v||0}</span></div>`;
  }).join('');
}

function gateTable(bt){
  const gc=bt.gate_components||{},gp=bt.gate_pass||{};
  return`<div class="table-wrapper"><table class="data-table"><thead><tr><th>Mode</th><th>Model Gate</th><th>Regime</th><th>Kill Switch</th><th>Final</th></tr></thead><tbody>
    ${['t1','swing'].map(m=>{const g=gc[m]||{};return`<tr><td class="fw-700">${m.toUpperCase()}</td>
      <td>${g.model_gate_ok?'<span class="text-success">✓</span>':'<span class="text-danger">✕</span>'}</td>
      <td>${g.regime_ok?'<span class="text-success">✓</span>':'<span class="text-danger">✕</span>'}</td>
      <td>${g.kill_switch_ok?'<span class="text-success">✓</span>':'<span class="text-danger">✕</span>'}</td>
      <td>${gp[m]?'<span class="badge badge-success">PASS</span>':'<span class="badge badge-danger">BLOCKED</span>'}</td></tr>`;}).join('')}
  </tbody></table></div>`;
}

// ── Charts ──
const chartColors={bg:'transparent',grid:'rgba(255,255,255,0.06)',text:'#94a3b8'};
const chartDefaults={responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:chartColors.text,font:{family:'Inter'}}},tooltip:{backgroundColor:'#1a1f2e',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#94a3b8',cornerRadius:8,padding:12}},scales:{x:{ticks:{color:chartColors.text},grid:{color:chartColors.grid}},y:{ticks:{color:chartColors.text},grid:{color:chartColors.grid}}}};

function renderWFChart(id,modeData){
  if(!modeData)return;
  const folds=modeData.folds||[];
  const ctx=document.getElementById(id);if(!ctx)return;
  S.charts[id]=new Chart(ctx,{type:'bar',data:{
    labels:folds.map(f=>'Fold '+f.fold),
    datasets:[
      {label:'OOS Win Rate',data:folds.map(f=>f.oos_metrics?.WinRate),backgroundColor:'rgba(99,102,241,0.7)',borderRadius:4},
      {label:'OOS Profit Factor',data:folds.map(f=>f.oos_metrics?.ProfitFactor),backgroundColor:'rgba(16,185,129,0.7)',borderRadius:4},
    ]},options:{...chartDefaults,plugins:{...chartDefaults.plugins,title:{display:true,text:'OOS Metrics per Fold',color:'#f1f5f9',font:{size:13}}}}});
}

function renderCompChart(id,metric,bt){
  const ctx=document.getElementById(id);if(!ctx)return;
  const t1=bt.metrics?.t1||{},sw=bt.metrics?.swing||{};
  S.charts[id]=new Chart(ctx,{type:'bar',data:{
    labels:['T+1','Swing'],
    datasets:[{label:metric,data:[t1[metric],sw[metric]],
      backgroundColor:['rgba(59,130,246,0.7)','rgba(139,92,246,0.7)'],borderRadius:6,barThickness:48}]
  },options:{...chartDefaults,indexAxis:'y',plugins:{...chartDefaults.plugins,legend:{display:false}}}});
}

function renderCAGRChart(id,wf){
  const ctx=document.getElementById(id);if(!ctx)return;
  const t1f=wf.modes?.t1?.folds||[],swf=wf.modes?.swing?.folds||[];
  const labels=t1f.map(f=>'Fold '+f.fold);
  S.charts[id]=new Chart(ctx,{type:'bar',data:{
    labels,datasets:[
      {label:'T+1 CAGR%',data:t1f.map(f=>f.oos_metrics?.CAGR),backgroundColor:'rgba(59,130,246,0.6)',borderRadius:4},
      {label:'Swing CAGR%',data:swf.map(f=>f.oos_metrics?.CAGR),backgroundColor:'rgba(139,92,246,0.6)',borderRadius:4},
    ]},options:chartDefaults});
}

// ── Init ──
async function init(){
  await loadAll();
  const hash=location.hash.replace('#','');
  navigate(hash||'overview');
  document.querySelectorAll('.nav-item[data-page]').forEach(n=>{
    n.addEventListener('click',e=>{e.preventDefault();navigate(n.dataset.page);location.hash=n.dataset.page;
      document.querySelector('.sidebar')?.classList.remove('open');});
  });
  window.addEventListener('hashchange',()=>{const h=location.hash.replace('#','');if(h)navigate(h);});
  $('#btnRefresh')?.addEventListener('click',async()=>{await loadAll();navigate(S.page);toast('Refreshed','success');});
  $('#menuToggle')?.addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
}
init();
})();
