import json
from pathlib import Path
import pytest
from src.ingest.idx_membership_acquisition import probe_idx_membership_source_availability

def plan(path, second=False):
    rows=[{"announcement_id":"ONE","expected_source_url":"https://www.idx.co.id/one.zip","verification_status":"unverified_research_candidate"}]
    if second: rows.append({"announcement_id":"TWO","expected_source_url":"https://www.idx.co.id/two.zip","verification_status":"unverified_research_candidate"})
    path.write_text(json.dumps({"candidates":rows}),encoding="utf-8")

def test_available_is_review_only(tmp_path):
    p=tmp_path/"p.json"; plan(p)
    out=probe_idx_membership_source_availability(str(p),str(tmp_path/"missing.json"),str(tmp_path/"o.json"),probe_head=lambda u,t:(200,u,{"content-type":"application/zip"},1))
    assert out["status"]=="sources_available_for_manual_download"
    assert out["response_body_bytes_read"]==0 and not out["automatic_download_performed"] and not out["final_decision_eligible"]

def test_partial_and_redirect_are_blocked(tmp_path):
    p=tmp_path/"p.json"; plan(p,True)
    out=probe_idx_membership_source_availability(str(p),str(tmp_path/"missing.json"),str(tmp_path/"o.json"),probe_head=lambda u,t:(200,u,{"content-type":"application/zip"},1) if "one" in u else (404,u,{},1))
    assert out["status"]=="blocked_partial_source_availability"
    p2=tmp_path/"p2.json"; plan(p2)
    out=probe_idx_membership_source_availability(str(p2),str(tmp_path/"missing.json"),str(tmp_path/"o2.json"),probe_head=lambda u,t:(200,"https://example.com/a.zip",{"content-type":"application/zip"},1))
    assert out["records"][0]["status"]=="blocked_untrusted_redirect"

def test_invalid_timeout(tmp_path):
    p=tmp_path/"p.json"; plan(p)
    with pytest.raises(ValueError): probe_idx_membership_source_availability(str(p),timeout_seconds=0)

def test_workflow_is_read_only():
    text=Path(".github/workflows/idx-membership-source-monitor.yml").read_text(encoding="utf-8")
    assert "contents: read" in text and "upload-artifact@v4" in text
    assert "git push" not in text and "send-telegram" not in text
