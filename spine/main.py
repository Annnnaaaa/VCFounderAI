"""VC Brain — Lane 1 data spine. Owns the frozen JSON contract + Supabase persistence.

Run: uvicorn main:app --reload --port 8000
"""
import base64
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from supabase import Client, create_client

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
DECK_BUCKET = "decks"

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI(title="VC Brain Spine", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ────────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Loose(BaseModel):
    """Contract bodies are permissive — extra keys pass through, nothing is rejected."""

    model_config = ConfigDict(extra="allow")


def normalize_identity(github_handle: Optional[str], name: Optional[str]) -> str:
    """Founder identity key: github handle wins, else normalized name."""
    if github_handle:
        h = github_handle.strip().lower()
        h = re.sub(r"^https?://(www\.)?github\.com/", "", h).strip("/")
        if h:
            return f"github:{h}"
    if name:
        n = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        if n:
            return f"name:{n}"
    raise HTTPException(400, "cannot derive founder identity: need github_handle or founder name")


def write_trace(
    opportunity_id: Optional[str],
    step: str,
    detail: str = "",
    evidence_refs: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "opportunity_id": opportunity_id,
        "step": step,
        "detail": detail or "",
        "evidence_refs": evidence_refs or [],
        "ts": now_iso(),
    }
    try:
        sb.table("trace_log").insert(row).execute()
    except Exception as e:  # tracing must never break a write
        row["_trace_error"] = str(e)
    return row


def trace_from_body(body: Dict[str, Any], default_opp: Optional[str], default_step: str) -> None:
    """Every write endpoint accepts an optional `trace` object and stores it."""
    t = body.get("trace")
    if not t:
        return
    if isinstance(t, dict):
        t = [t]
    for entry in t:
        write_trace(
            entry.get("opportunity_id") or default_opp,
            entry.get("step") or default_step,
            entry.get("detail", ""),
            entry.get("evidence_refs"),
        )


def rows(resp) -> List[Dict[str, Any]]:
    return resp.data or []


def one(resp) -> Optional[Dict[str, Any]]:
    d = resp.data or []
    return d[0] if d else None


# ── POST /apply ────────────────────────────────────────────────────────────
class ApplyBody(Loose):
    company_name: str
    one_liner: Optional[str] = None
    founder_name: Optional[str] = None
    github_handle: Optional[str] = None
    twitter: Optional[str] = None
    linkedin: Optional[str] = None
    location: Optional[str] = None
    sector: Optional[str] = None
    stage: Optional[str] = "pre-seed"
    deck_url: Optional[str] = None
    deck_base64: Optional[str] = None
    deck_filename: Optional[str] = None


def store_deck(opp_id: str, body: ApplyBody) -> tuple[bool, Optional[str]]:
    """Persist deck bytes to Supabase storage. Returns (deck_present, public_url)."""
    data: Optional[bytes] = None
    filename = body.deck_filename or "deck.pdf"

    if body.deck_base64:
        raw = body.deck_base64.split(",", 1)[-1]  # tolerate data: URIs
        try:
            data = base64.b64decode(raw)
        except Exception:
            raise HTTPException(400, "deck_base64 is not valid base64")
    elif body.deck_url:
        try:
            r = httpx.get(body.deck_url, timeout=20, follow_redirects=True)
            r.raise_for_status()
            data = r.content
            filename = body.deck_url.rsplit("/", 1)[-1].split("?")[0] or filename
        except Exception:
            # keep the link even if we could not fetch the bytes
            return True, body.deck_url

    if not data:
        return False, None

    path = f"{opp_id}/{filename}"
    try:
        sb.storage.from_(DECK_BUCKET).upload(
            path, data, {"content-type": "application/pdf", "upsert": "true"}
        )
        return True, sb.storage.from_(DECK_BUCKET).get_public_url(path)
    except Exception:
        return True, body.deck_url


@app.post("/apply")
def apply(body: ApplyBody):
    """Minimum bar is deck + company name. No other required fields."""
    opp_id = str(uuid.uuid4())
    deck_present, deck_url = store_deck(opp_id, body)

    identity = None
    if body.github_handle or body.founder_name:
        identity = normalize_identity(body.github_handle, body.founder_name)

    prior = {"value": 0, "confidence": 0.0, "trend": "flat", "history": []}
    if identity:
        existing = one(
            sb.table("founder_scores").select("*").eq("identity", identity).execute()
        )
        if existing:  # a returning founder carries their history in
            prior = {
                "value": existing["value"],
                "confidence": existing["confidence"],
                "trend": existing["trend"],
                "history": existing["history"],
            }

    row = {
        "id": opp_id,
        "source": "inbound_apply",
        "founder": {
            "name": body.founder_name or "",
            "handles": {
                "github": body.github_handle or "",
                "twitter": body.twitter or "",
                "linkedin": body.linkedin or "",
            },
            "location": body.location or "",
            "identity": identity,
        },
        "company": {
            "name": body.company_name,
            "one_liner": body.one_liner or "",
            "sector": body.sector or "",
            "stage": body.stage or "pre-seed",
        },
        "deck_present": deck_present,
        "deck_url": deck_url,
        "created_at": now_iso(),
        "status": "new",
        "founder_score": prior,
    }
    created = one(sb.table("opportunities").insert(row).execute())
    write_trace(opp_id, "deck_extract", f"inbound application received for {body.company_name}")
    trace_from_body(body.model_dump(), opp_id, "deck_extract")
    return created


# ── bulk writes (Lane 4 / Lane 2 / Lane 3) ─────────────────────────────────
def as_list(body: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if isinstance(body.get(key), list):
            return body[key]
        return [body]
    raise HTTPException(400, f"expected an object or a list of {key}")


@app.post("/opportunities")
def create_opportunities(body: Any = Body(...)):
    items = as_list(body, "opportunities")
    payload = []
    for it in items:
        it = dict(it)
        it.pop("trace", None)
        it.setdefault("id", str(uuid.uuid4()))
        it.setdefault("created_at", now_iso())
        it.setdefault("status", "new")
        it.setdefault("source", "outbound_github")
        it.setdefault("deck_present", False)
        it.setdefault(
            "founder_score", {"value": 0, "confidence": 0.0, "trend": "flat", "history": []}
        )
        f = it.setdefault("founder", {})
        if isinstance(f, dict) and not f.get("identity"):
            gh = (f.get("handles") or {}).get("github")
            if gh or f.get("name"):
                f["identity"] = normalize_identity(gh, f.get("name"))
        payload.append(it)

    created = rows(sb.table("opportunities").upsert(payload).execute())
    for c in created:
        write_trace(c["id"], "enrich", f"sourced via {c.get('source')}")
    if isinstance(body, dict):
        trace_from_body(body, None, "enrich")
    return created


@app.post("/claims")
def create_claims(body: Any = Body(...)):
    items = as_list(body, "claims")
    payload = []
    for it in items:
        it = dict(it)
        it.pop("trace", None)
        it.setdefault("claim_id", str(uuid.uuid4()))
        it.setdefault(
            "trust", {"status": "unverified", "confidence": 0.0, "evidence": [], "note": ""}
        )
        payload.append(it)
    created = rows(sb.table("claims").upsert(payload).execute())
    for c in created:
        write_trace(c.get("opportunity_id"), "verify", f"claim recorded: {c.get('text', '')[:120]}")
    if isinstance(body, dict):
        trace_from_body(body, None, "verify")
    return created


@app.patch("/claims/{claim_id}/trust")
def patch_claim_trust(claim_id: str, body: Any = Body(...)):
    body = body if isinstance(body, dict) else {}
    trust = body.get("trust", {k: v for k, v in body.items() if k != "trace"})
    updated = one(
        sb.table("claims").update({"trust": trust}).eq("claim_id", claim_id).execute()
    )
    if not updated:
        raise HTTPException(404, f"claim {claim_id} not found")
    write_trace(
        updated.get("opportunity_id"),
        "verify",
        f"trust -> {trust.get('status')} ({trust.get('confidence')})",
        [e.get("url") for e in (trust.get("evidence") or []) if isinstance(e, dict)],
    )
    trace_from_body(body, updated.get("opportunity_id"), "verify")
    return updated


@app.post("/axis-scores")
def upsert_axis_scores(body: Any = Body(...)):
    items = as_list(body, "axis_scores")
    payload = [{k: v for k, v in dict(it).items() if k != "trace"} for it in items]
    for p in payload:
        p["updated_at"] = now_iso()
    saved = rows(sb.table("axis_scores").upsert(payload, on_conflict="opportunity_id").execute())
    for s in saved:
        axes = s.get("axes") or {}
        write_trace(
            s["opportunity_id"],
            "axis_score",
            f"founder={(axes.get('founder') or {}).get('score')} "
            f"market={(axes.get('market') or {}).get('rating')} "
            f"idea_vs_market={(axes.get('idea_vs_market') or {}).get('verdict')}",
        )
        sb.table("opportunities").update({"status": "screened"}).eq(
            "id", s["opportunity_id"]
        ).execute()
    if isinstance(body, dict):
        trace_from_body(body, None, "axis_score")
    return saved


@app.post("/cold-start")
def upsert_cold_start(body: Any = Body(...)):
    items = as_list(body, "cold_start")
    payload = [{k: v for k, v in dict(it).items() if k != "trace"} for it in items]
    for p in payload:
        p["updated_at"] = now_iso()
    saved = rows(sb.table("cold_start").upsert(payload, on_conflict="opportunity_id").execute())
    for s in saved:
        fq = s.get("founder_quality") or {}
        write_trace(
            s["opportunity_id"],
            "cold_start",
            f"band={fq.get('band')} interval={fq.get('interval')} signals={fq.get('signals_used')}",
        )
    if isinstance(body, dict):
        trace_from_body(body, None, "cold_start")
    return saved


@app.post("/memos")
def upsert_memos(body: Any = Body(...)):
    items = as_list(body, "memos")
    payload = [{k: v for k, v in dict(it).items() if k != "trace"} for it in items]
    for p in payload:
        p["updated_at"] = now_iso()
    saved = rows(sb.table("memos").upsert(payload, on_conflict="opportunity_id").execute())
    for s in saved:
        write_trace(
            s["opportunity_id"], "memo", f"memo written, recommendation={s.get('recommendation')}"
        )
        sb.table("opportunities").update({"status": "memo_ready"}).eq(
            "id", s["opportunity_id"]
        ).execute()
    if isinstance(body, dict):
        trace_from_body(body, None, "memo")
    return saved


@app.post("/trace")
def post_trace(body: Any = Body(...)):
    items = as_list(body, "trace")
    return [
        write_trace(
            it.get("opportunity_id"),
            it.get("step", "enrich"),
            it.get("detail", ""),
            it.get("evidence_refs"),
        )
        for it in items
    ]


# ── founder score store (persists across opportunities, never resets) ──────
class FounderScoreBody(Loose):
    identity: Optional[str] = None
    github_handle: Optional[str] = None
    founder_name: Optional[str] = None
    name: Optional[str] = None
    value: float
    confidence: Optional[float] = None
    reason: Optional[str] = ""
    opportunity_id: Optional[str] = None


@app.post("/founder-score")
def post_founder_score(body: FounderScoreBody):
    display_name = body.founder_name or body.name
    identity = body.identity or normalize_identity(body.github_handle, display_name)

    existing = one(sb.table("founder_scores").select("*").eq("identity", identity).execute())
    history: List[Dict[str, Any]] = list(existing["history"]) if existing else []

    history.append(
        {
            "value": body.value,
            "ts": now_iso(),
            "reason": body.reason or "",
            "opportunity_id": body.opportunity_id,
        }
    )

    # trend from the last two values
    trend = "flat"
    if len(history) >= 2:
        prev, cur = history[-2]["value"], history[-1]["value"]
        trend = "up" if cur > prev else "down" if cur < prev else "flat"

    row = {
        "identity": identity,
        "name": display_name or (existing or {}).get("name") or "",
        "value": body.value,
        "confidence": body.confidence
        if body.confidence is not None
        else (existing or {}).get("confidence", 0.0),
        "trend": trend,
        "history": history,
        "updated_at": now_iso(),
    }
    saved = one(sb.table("founder_scores").upsert(row, on_conflict="identity").execute())

    # mirror onto every opportunity belonging to this founder
    snapshot = {
        "value": saved["value"],
        "confidence": saved["confidence"],
        "trend": saved["trend"],
        "history": saved["history"],
    }
    sb.table("opportunities").update({"founder_score": snapshot}).eq(
        "founder->>identity", identity
    ).execute()

    write_trace(
        body.opportunity_id,
        "axis_score",
        f"founder score {body.value} for {identity} (trend {trend}, n={len(history)})",
    )
    trace_from_body(body.model_dump(), body.opportunity_id, "axis_score")
    return saved


@app.get("/founder-score/{identity:path}")
def get_founder_score(identity: str):
    found = one(sb.table("founder_scores").select("*").eq("identity", identity).execute())
    if not found:  # tolerate a bare handle or name
        for guess in (f"github:{identity.lower()}", normalize_identity(None, identity)):
            found = one(sb.table("founder_scores").select("*").eq("identity", guess).execute())
            if found:
                break
    if not found:
        raise HTTPException(404, f"no founder score for {identity}")
    return found


# ── read APIs for the UI ───────────────────────────────────────────────────
@app.get("/opportunities")
def list_opportunities(
    sector: Optional[str] = None,
    stage: Optional[str] = None,
    min_founder_score: Optional[float] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    q = sb.table("opportunities").select("*")
    if sector:
        q = q.ilike("company->>sector", f"%{sector}%")
    if stage:
        q = q.ilike("company->>stage", f"%{stage}%")
    if source:
        q = q.eq("source", source)
    if status:
        q = q.eq("status", status)
    opps = rows(q.limit(limit).execute())
    if not opps:
        return []

    ids = [o["id"] for o in opps]
    axis_by_opp = {
        a["opportunity_id"]: a.get("axes") or {}
        for a in rows(sb.table("axis_scores").select("*").in_("opportunity_id", ids).execute())
    }

    def founder_axis(o: Dict[str, Any]) -> float:
        axes = axis_by_opp.get(o["id"], {})
        s = (axes.get("founder") or {}).get("score")
        if s is None:
            s = (o.get("founder_score") or {}).get("value", 0)
        return float(s or 0)

    for o in opps:
        o["axes"] = axis_by_opp.get(o["id"], {})  # so the list view can render axes

    if min_founder_score is not None:
        opps = [o for o in opps if founder_axis(o) >= min_founder_score]

    opps.sort(key=founder_axis, reverse=True)  # ranked by founder axis score desc
    return opps


@app.get("/opportunities/{opp_id}/bundle")
def get_bundle(opp_id: str):
    """One call → everything Lovable needs for the detail page."""
    opp = one(sb.table("opportunities").select("*").eq("id", opp_id).execute())
    if not opp:
        raise HTTPException(404, f"opportunity {opp_id} not found")

    identity = (opp.get("founder") or {}).get("identity")
    founder_score = None
    if identity:
        founder_score = one(
            sb.table("founder_scores").select("*").eq("identity", identity).execute()
        )

    return {
        "opportunity": opp,
        "claims": rows(sb.table("claims").select("*").eq("opportunity_id", opp_id).execute()),
        "axis_scores": one(
            sb.table("axis_scores").select("*").eq("opportunity_id", opp_id).execute()
        ),
        "cold_start": one(
            sb.table("cold_start").select("*").eq("opportunity_id", opp_id).execute()
        ),
        "memo": one(sb.table("memos").select("*").eq("opportunity_id", opp_id).execute()),
        "founder_score": founder_score or opp.get("founder_score"),
        "trace_log": rows(
            sb.table("trace_log")
            .select("*")
            .eq("opportunity_id", opp_id)
            .order("ts", desc=False)
            .execute()
        ),
    }


@app.get("/thesis")
def get_thesis():
    t = one(sb.table("thesis").select("*").limit(1).execute())
    if not t:
        raise HTTPException(404, "no thesis row — run schema.sql")
    return t


@app.put("/thesis")
def put_thesis(body: Any = Body(...)):
    body = body if isinstance(body, dict) else {}
    params = body.get("params", {k: v for k, v in body.items() if k != "trace"})
    existing = one(sb.table("thesis").select("id").limit(1).execute())
    row = {"params": params, "updated_at": now_iso()}
    if existing:
        saved = one(sb.table("thesis").update(row).eq("id", existing["id"]).execute())
    else:
        saved = one(sb.table("thesis").insert(row).execute())
    trace_from_body(body, None, "enrich")
    return saved


@app.get("/health")
def health():
    return {"ok": True, "ts": now_iso()}
