from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib import parse, request

import pandas as pd

from src.config import EventRiskSourceSettings, Settings


def _resolve_env_value(value: str) -> str:
    txt = str(value)
    if txt.startswith("${") and txt.endswith("}") and len(txt) > 3:
        env_name = txt[2:-1].strip()
        return os.getenv(env_name, "")
    return txt


def _resolved_dict(values: dict[str, str] | None) -> dict[str, str]:
    raw = values or {}
    return {k: _resolve_env_value(v) for k, v in raw.items()}


def _extract_by_path(payload: object, path: str) -> object:
    if not path:
        return payload
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return []
    return cur


def _normalize_ticker(raw: object) -> str:
    txt = str(raw).upper().strip()
    if "." in txt:
        txt = txt.split(".", 1)[0]
    return txt


def _is_valid_ticker(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}", str(text).strip()))


def _format_date(raw: object) -> str:
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _extract_ticker_from_title(text: str) -> str:
    for pattern in [r"\[\s*([A-Z]{2,6})\s*\]", r"\(\s*([A-Z]{2,6})\s*\)"]:
        m = re.search(pattern, text)
        if m:
            return _normalize_ticker(m.group(1))
    return ""


def _keywords_match(text: str, source: EventRiskSourceSettings) -> bool:
    body = str(text).lower()
    any_keywords = [str(x).strip().lower() for x in (source.html_keyword_any or []) if str(x).strip()]
    all_keywords = [str(x).strip().lower() for x in (source.html_keyword_all or []) if str(x).strip()]
    none_keywords = [str(x).strip().lower() for x in (source.html_keyword_none or []) if str(x).strip()]

    if any_keywords and not any(k in body for k in any_keywords):
        return False
    if all_keywords and not all(k in body for k in all_keywords):
        return False
    if none_keywords and any(k in body for k in none_keywords):
        return False
    return True


def _load_rows_from_html(
    text: str,
    source: EventRiskSourceSettings,
    default_status: str,
    settings: Settings,
) -> pd.DataFrame:
    anchors = re.findall(r"<a[^>]*>(.*?)</a>", text, flags=re.IGNORECASE | re.DOTALL)
    rows: list[dict[str, str]] = []
    today = datetime.utcnow().strftime("%Y-%m-%d")
    status_override = str(source.status_override).upper().strip() or default_status
    source_name = str(source.source_name).strip() or default_status.lower()

    for raw in anchors:
        plain = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        title = _normalize_space(plain)
        if len(title) < 6:
            continue
        if not _keywords_match(title, source):
            continue
        ticker = _extract_ticker_from_title(title)
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "status": status_override,
                "reason": title,
                "start_date": today,
                "end_date": "",
                "source": source_name,
                "updated_at": today,
            }
        )

    if not rows:
        for item in _extract_nuxt_announcements(text):
            title = _normalize_space(item.get("title", ""))
            if len(title) < 6:
                continue
            if not _keywords_match(title, source):
                continue
            ticker = _normalize_ticker(item.get("ticker", "")) or _extract_ticker_from_title(title)
            if not ticker:
                continue
            publish_date = _format_date(item.get("publish_date", ""))
            rows.append(
                {
                    "ticker": ticker,
                    "status": status_override,
                    "reason": title,
                    "start_date": publish_date or today,
                    "end_date": "",
                    "source": source_name,
                    "updated_at": today,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["ticker", "status", "reason", "start_date", "end_date", "source", "updated_at"])

    out = pd.DataFrame(rows)
    out = out.loc[out["ticker"].map(_is_valid_ticker)].copy()
    out = _apply_default_active_window(out, settings)
    out = out.drop_duplicates(subset=["ticker", "status"], keep="last").reset_index(drop=True)
    return out


def _extract_nuxt_announcements(text: str) -> list[dict[str, str]]:
    node_script = r"""
const fs = require('fs');
const html = fs.readFileSync(0, 'utf8');
const start = html.indexOf('__NUXT__=');
if (start < 0) {
  process.stdout.write('[]');
  process.exit(0);
}
const after = html.slice(start + '__NUXT__='.length);
const scriptEnd = after.indexOf('</script>');
let expr = (scriptEnd >= 0 ? after.slice(0, scriptEnd) : after).trim();
if (expr.endsWith(';')) {
  expr = expr.slice(0, -1);
}
let root = null;
try {
  root = eval(expr);
} catch (e) {
  process.stdout.write('[]');
  process.exit(0);
}
const out = [];
const seen = new Set();
const stack = [root];
while (stack.length > 0) {
  const cur = stack.pop();
  if (!cur) continue;
  if (Array.isArray(cur)) {
  const hasTicker = (x) => ('Code' in x) || ('Kode' in x) || ('CompanyID' in x) || ('Ticker' in x) || ('Symbol' in x);
  const hasTitle = (x) => ('Title' in x) || ('Judul' in x) || ('AnnouncementTitle' in x) || ('Reason' in x);
  const hasDate = (x) => ('PublishDate' in x) || ('Date' in x) || ('UMADate' in x) || ('Tanggal' in x);
  const isAnnouncementArray =
      cur.length > 0 &&
      cur.every(
        (x) =>
          x &&
          typeof x === 'object' &&
          hasTicker(x) &&
          hasTitle(x) &&
          hasDate(x),
      );
    if (isAnnouncementArray) {
      for (const row of cur) {
        const ticker = String(row.Code || row.Kode || row.CompanyID || row.Ticker || row.Symbol || '').trim();
        const title = String(row.Title || row.Judul || row.AnnouncementTitle || row.Reason || '').trim();
        const publishDate = String(row.PublishDate || row.Date || row.UMADate || row.Tanggal || '').trim();
        const key = `${ticker}|${publishDate}|${title}`;
        if (!seen.has(key)) {
          seen.add(key);
          out.push({ ticker, title, publish_date: publishDate });
        }
      }
    }
    for (const v of cur) stack.push(v);
  } else if (typeof cur === 'object') {
    for (const v of Object.values(cur)) stack.push(v);
  }
}
process.stdout.write(JSON.stringify(out));
"""
    try:
        proc = subprocess.run(
            ["node", "-e", node_script],
            input=text,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []

    out: list[dict[str, str]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "ticker": str(row.get("ticker", "")).strip(),
                "title": str(row.get("title", "")).strip(),
                "publish_date": str(row.get("publish_date", "")).strip(),
            }
        )
    return out


def _apply_default_active_window(frame: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    if frame.empty:
        return frame

    out = frame.copy()
    if "start_date" not in out.columns:
        out["start_date"] = ""
    if "end_date" not in out.columns:
        out["end_date"] = ""

    start_ts = pd.to_datetime(out["start_date"], errors="coerce")
    end_ts = pd.to_datetime(out["end_date"], errors="coerce")
    active_days = max(1, int(settings.pipeline.event_risk.default_active_days))
    fill_mask = end_ts.isna() & start_ts.notna()
    if fill_mask.any():
        out.loc[fill_mask, "end_date"] = (
            start_ts[fill_mask] + pd.Timedelta(days=active_days)
        ).dt.strftime("%Y-%m-%d")

    out["start_date"] = out["start_date"].map(_format_date)
    out["end_date"] = out["end_date"].map(_format_date)
    return out


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _load_rows_from_source(
    source: EventRiskSourceSettings,
    default_status: str,
    settings: Settings,
    response_cache: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, str]:
    cfg = settings.pipeline.event_risk.auto_update
    if not source.url:
        return pd.DataFrame(), "no_url"

    base_params = _resolved_dict(cfg.query_params)
    source_params = _resolved_dict(source.query_params)
    params = {**base_params, **source_params}
    headers = _resolved_dict(cfg.headers)

    url = source.url.strip()
    if params:
        connector = "&" if "?" in url else "?"
        url = f"{url}{connector}{parse.urlencode(params)}"

    cache_key = url
    cached = (response_cache or {}).get(cache_key)
    if isinstance(cached, str) and cached:
        text = cached
    else:
        req = request.Request(url=url, headers=headers)
        with request.urlopen(req, timeout=cfg.request_timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
        if response_cache is not None:
            response_cache[cache_key] = text

    fmt = (source.format or "csv").strip().lower()
    if fmt == "json":
        payload = json.loads(text)
        rows = _extract_by_path(payload, source.response_data_path)
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ValueError(f"Event-risk source {default_status} JSON data is not list-like")
        frame = pd.DataFrame(rows)
    elif fmt == "html":
        frame = _load_rows_from_html(text=text, source=source, default_status=default_status, settings=settings)
        return frame, "ok"
    else:
        frame = pd.read_csv(StringIO(text))

    if source.ticker_column not in frame.columns:
        raise ValueError(f"Event-risk source {default_status} missing ticker column: {source.ticker_column}")

    out = pd.DataFrame(index=frame.index)
    out["ticker"] = frame[source.ticker_column].map(_normalize_ticker)

    status_override = str(source.status_override).upper().strip()
    status_column = str(source.status_column).strip()
    if status_override:
        out["status"] = status_override
    elif status_column and status_column in frame.columns:
        out["status"] = frame[status_column].astype(str).str.upper().str.strip()
    else:
        out["status"] = default_status
    out["status"] = out["status"].replace("", default_status).fillna(default_status)

    reason_column = str(source.reason_column).strip()
    if reason_column and reason_column in frame.columns:
        out["reason"] = frame[reason_column].astype(str).str.strip()
    else:
        out["reason"] = ""
    fallback_reason = f"Auto-update event risk: {default_status}"
    out["reason"] = out["reason"].where(out["reason"].str.len() > 0, fallback_reason)

    start_column = str(source.start_date_column).strip()
    end_column = str(source.end_date_column).strip()
    out["start_date"] = frame[start_column].map(_format_date) if start_column and start_column in frame.columns else ""
    out["end_date"] = frame[end_column].map(_format_date) if end_column and end_column in frame.columns else ""
    out["source"] = str(source.source_name).strip() or default_status.lower()
    out["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d")
    out = _apply_default_active_window(out, settings)

    out = out.loc[out["ticker"].map(_is_valid_ticker)].copy()
    out = out.drop_duplicates(subset=["ticker", "status"], keep="last")
    out = out.reset_index(drop=True)
    return out, "ok"


def maybe_auto_update_event_risk(settings: Settings, force: bool = False) -> dict[str, object]:
    pipeline_cfg = settings.pipeline.event_risk
    cfg = pipeline_cfg.auto_update
    blacklist_path = Path(pipeline_cfg.blacklist_csv_path)
    state_path = Path(cfg.state_path)
    now = datetime.utcnow()
    state = _read_state(state_path)

    result: dict[str, object] = {
        "enabled": bool(cfg.enabled),
        "forced": bool(force),
        "status": "skipped_disabled",
        "message": "Event-risk auto-update disabled",
        "blacklist_path": str(blacklist_path),
        "state_path": str(state_path),
        "updated": False,
        "attempted_at": now.isoformat(),
        "last_success_at": state.get("last_success_at", ""),
        "counts": {"rows": 0, "tickers": 0, "status_counts": {}},
        "errors": [],
        "source_status": {},
    }

    if (not cfg.enabled) and (not force):
        return result

    last_success = pd.to_datetime(state.get("last_success_at"), errors="coerce")
    if (not force) and pd.notna(last_success):
        elapsed = now - pd.Timestamp(last_success).to_pydatetime()
        if elapsed < timedelta(hours=max(1, int(cfg.interval_hours))):
            result["status"] = "skipped_interval"
            result["message"] = f"Last successful update still within {cfg.interval_hours} hours interval"
            return result

    errors: list[str] = []
    source_status: dict[str, str] = {}
    frames: list[pd.DataFrame] = []
    response_cache: dict[str, str] = {}

    for status_name, source in [("SUSPEND", cfg.suspend), ("UMA", cfg.uma), ("MATERIAL", cfg.material)]:
        try:
            frame, status = _load_rows_from_source(
                source=source,
                default_status=status_name,
                settings=settings,
                response_cache=response_cache,
            )
            source_status[status_name] = status
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            source_status[status_name] = "error"
            errors.append(f"{status_name}: {exc}")

    result["errors"] = errors
    result["source_status"] = source_status

    no_url_only = source_status and all(v == "no_url" for v in source_status.values())
    if no_url_only:
        result["status"] = "skipped_no_source"
        result["message"] = "Event-risk source URLs are empty; keeping existing blacklist file"
        _write_state(
            state_path,
            {
                "last_attempt_at": now.isoformat(),
                "last_success_at": state.get("last_success_at", ""),
                "status": result["status"],
                "message": result["message"],
                "errors": errors,
                "source_status": source_status,
                "blacklist_path": str(blacklist_path),
            },
        )
        return result

    if cfg.fail_on_error and errors:
        raise RuntimeError("; ".join(errors))

    if not frames:
        result["status"] = "failed_no_rows"
        result["message"] = "No rows fetched from event-risk sources; keeping existing blacklist file"
        if cfg.fail_on_error:
            raise RuntimeError(str(result["message"]))
        _write_state(
            state_path,
            {
                "last_attempt_at": now.isoformat(),
                "last_success_at": state.get("last_success_at", ""),
                "status": result["status"],
                "message": result["message"],
                "errors": errors,
                "source_status": source_status,
                "blacklist_path": str(blacklist_path),
            },
        )
        return result

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["ticker"] = merged["ticker"].astype(str).str.upper().str.strip()
    merged["status"] = merged["status"].astype(str).str.upper().str.strip()
    merged["reason"] = merged["reason"].astype(str).str.strip()
    merged["start_date"] = merged["start_date"].map(_format_date)
    merged["end_date"] = merged["end_date"].map(_format_date)
    merged["source"] = merged["source"].astype(str).str.strip()
    merged["updated_at"] = now.strftime("%Y-%m-%d")
    merged = merged.loc[merged["ticker"].map(_is_valid_ticker)].copy()
    merged = merged.loc[merged["status"].str.len() > 0].copy()
    merged = merged.drop_duplicates(subset=["ticker", "status"], keep="last")
    merged = merged.sort_values(["ticker", "status"]).reset_index(drop=True)

    if merged.empty:
        result["status"] = "failed_no_rows"
        result["message"] = "Fetched event-risk rows are empty after normalization"
        if cfg.fail_on_error:
            raise RuntimeError(str(result["message"]))
        return result

    blacklist_path.parent.mkdir(parents=True, exist_ok=True)
    merged[["ticker", "status", "reason", "start_date", "end_date", "updated_at", "source"]].to_csv(
        blacklist_path,
        index=False,
    )

    status_counts = merged["status"].value_counts().to_dict()
    result["updated"] = True
    result["status"] = "updated"
    result["message"] = "Event-risk blacklist updated successfully"
    result["counts"] = {
        "rows": int(len(merged)),
        "tickers": int(merged["ticker"].nunique()),
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
    }
    result["last_success_at"] = now.isoformat()

    _write_state(
        state_path,
        {
            "last_attempt_at": now.isoformat(),
            "last_success_at": now.isoformat(),
            "status": result["status"],
            "message": result["message"],
            "counts": result["counts"],
            "errors": errors,
            "source_status": source_status,
            "blacklist_path": str(blacklist_path),
        },
    )
    return result
