"""VC Brain — Lane 1 data spine. Owns the frozen JSON contract + Supabase persistence.

Run: uvicorn main:app --reload --port 8000
"""
import base64
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict
from supabase import Client, create_client

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
DECK_BUCKET = "decks"

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

class _ThreadLocalSupabase:
    """One Supabase client per thread.

    FastAPI runs sync `def` endpoints in a threadpool, so a single shared client
    means concurrent requests race on one HTTP/2 socket — which surfaces as
    httpx.ReadError and a 500. Attribute access is proxied to a per-thread client.
    """

    _local = threading.local()

    @property
    def _client(self) -> Client:
        client = getattr(self._local, "client", None)
        if client is None:
            client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            self._local.client = client
        return client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


sb = _ThreadLocalSupabase()

# transient socket/stream faults worth one more attempt
_TRANSIENT = ("ReadError", "WriteError", "ConnectError", "RemoteProtocolError", "PoolTimeout")


def retry(fn, attempts: int = 3, base_delay: float = 0.15):
    """Defense in depth: per-thread clients fix the race, this absorbs real blips."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ not in _TRANSIENT and not any(
                t in str(e) for t in ("ReadError", "10035", "Connection reset")
            ):
                raise
            last = e
            time.sleep(base_delay * (2**i))
    raise last  # type: ignore[misc]

app = FastAPI(title="VC Brain Spine", version="1.1")


@app.exception_handler(APIError)
def postgrest_error(request: Request, exc: APIError) -> JSONResponse:
    """Surface schema mismatches as an actionable 400 instead of an opaque 500."""
    code = getattr(exc, "code", "") or ""
    message = getattr(exc, "message", None) or str(exc)
    if code in ("PGRST204", "42703"):
        return JSONResponse(
            status_code=400,
            content={"detail": f"unknown column — schema migration needed: {message}"},
        )
    return JSONResponse(status_code=400, content={"detail": message, "code": code})


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
        retry(sb.table("trace_log").insert(row).execute)
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


def ex(q):
    """Execute a Supabase query builder, retrying transient socket faults."""
    return retry(q.execute) if hasattr(q, "execute") else q


def rows(q) -> List[Dict[str, Any]]:
    return ex(q).data or []


def one(q) -> Optional[Dict[str, Any]]:
    d = ex(q).data or []
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


def safe_object_key(filename: str) -> str:
    """Supabase storage rejects non-ASCII and empty keys with InvalidKey.

    Fold accents to ASCII, replace anything else with '-', and always end up
    with a non-empty name.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    )
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip("-._")
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = f"deck{ascii_name or '.pdf'}"
    return ascii_name[:120]


def store_deck(opp_id: str, body: ApplyBody) -> tuple[bool, Optional[str]]:
    """Persist deck bytes to Supabase storage.

    Returns (deck_present, url). deck_present is true only when a deck is
    actually reachable — either stored bytes or a link we can hand the UI.
    An unbacked deck_present renders a deck affordance that resolves to nothing.
    """
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
            # the bytes are out of reach but the link still resolves for the UI
            write_trace(opp_id, "deck_extract", f"deck fetch failed, keeping link {body.deck_url}")
            return True, body.deck_url

    if not data:
        return False, None

    path = f"{opp_id}/{safe_object_key(filename)}"
    try:
        sb.storage.from_(DECK_BUCKET).upload(
            path, data, {"content-type": "application/pdf", "upsert": "true"}
        )
        return True, sb.storage.from_(DECK_BUCKET).get_public_url(path)
    except Exception as e:  # noqa: BLE001
        # never claim a deck the UI cannot open — record why and report honestly
        write_trace(opp_id, "deck_extract", f"deck upload failed: {type(e).__name__}: {e}")
        return (True, body.deck_url) if body.deck_url else (False, None)


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
            sb.table("founder_scores").select("*").eq("identity", identity)
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
    created = one(sb.table("opportunities").insert(row))
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
        # deck_present is derived, never trusted — it must imply an openable deck
        it["deck_present"] = bool(it.get("deck_url"))
        it.setdefault(
            "founder_score", {"value": 0, "confidence": 0.0, "trend": "flat", "history": []}
        )
        f = it.setdefault("founder", {})
        if isinstance(f, dict) and not f.get("identity"):
            gh = (f.get("handles") or {}).get("github")
            if gh or f.get("name"):
                f["identity"] = normalize_identity(gh, f.get("name"))
        payload.append(it)

    created = rows(sb.table("opportunities").upsert(payload))
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
    created = rows(sb.table("claims").upsert(payload))
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
        sb.table("claims").update({"trust": trust}).eq("claim_id", claim_id)
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
    saved = rows(sb.table("axis_scores").upsert(payload, on_conflict="opportunity_id"))
    for s in saved:
        axes = s.get("axes") or {}
        write_trace(
            s["opportunity_id"],
            "axis_score",
            f"founder={(axes.get('founder') or {}).get('score')} "
            f"market={(axes.get('market') or {}).get('rating')} "
            f"idea_vs_market={(axes.get('idea_vs_market') or {}).get('verdict')}",
        )
        retry(
            sb.table("opportunities")
            .update({"status": "screened"})
            .eq("id", s["opportunity_id"])
            .execute
        )
    if isinstance(body, dict):
        trace_from_body(body, None, "axis_score")
    return saved


@app.post("/cold-start")
def upsert_cold_start(body: Any = Body(...)):
    items = as_list(body, "cold_start")
    payload = [{k: v for k, v in dict(it).items() if k != "trace"} for it in items]
    for p in payload:
        p["updated_at"] = now_iso()
    saved = rows(sb.table("cold_start").upsert(payload, on_conflict="opportunity_id"))
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
    saved = rows(sb.table("memos").upsert(payload, on_conflict="opportunity_id"))
    for s in saved:
        write_trace(
            s["opportunity_id"], "memo", f"memo written, recommendation={s.get('recommendation')}"
        )
        retry(
            sb.table("opportunities")
            .update({"status": "memo_ready"})
            .eq("id", s["opportunity_id"])
            .execute
        )
    if isinstance(body, dict):
        trace_from_body(body, None, "memo")
    return saved


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge nested JSONB objects so a partial patch never clobbers siblings."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@app.patch("/opportunities/{opp_id}")
def patch_opportunity(opp_id: str, body: Any = Body(...)):
    """Partial update. Nested objects (company, founder) merge rather than replace,
    so `{"company": {"name": "x"}}` keeps the existing sector and one_liner.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "expected an object")
    existing = one(sb.table("opportunities").select("*").eq("id", opp_id))
    if not existing:
        raise HTTPException(404, f"opportunity {opp_id} not found")

    patch = {k: v for k, v in body.items() if k not in ("trace", "id", "created_at")}
    merged = {
        k: (deep_merge(existing.get(k) or {}, v) if isinstance(v, dict) else v)
        for k, v in patch.items()
    }
    if not merged:
        return existing

    # deck_present stays derived — a caller cannot assert a deck into existence
    if "deck_url" in merged or "deck_present" in merged:
        merged["deck_present"] = bool(merged.get("deck_url", existing.get("deck_url")))

    updated = one(sb.table("opportunities").update(merged).eq("id", opp_id))
    write_trace(opp_id, "enrich", f"opportunity patched: {', '.join(sorted(patch))}")
    trace_from_body(body, opp_id, "enrich")
    return updated


@app.delete("/opportunities/{opp_id}")
def delete_opportunity(opp_id: str, dry_run: bool = False):
    """Remove an opportunity and everything hanging off it.

    Claims, axis scores, cold start, memo and trace rows cascade. Pass
    ?dry_run=true first — the response reports what would go, so you can see
    whether another lane's work would be destroyed along with the junk row.
    """
    existing = one(sb.table("opportunities").select("*").eq("id", opp_id))
    if not existing:
        raise HTTPException(404, f"opportunity {opp_id} not found")

    cascade = {
        "claims": len(rows(sb.table("claims").select("claim_id").eq("opportunity_id", opp_id))),
        "axis_scores": len(
            rows(sb.table("axis_scores").select("opportunity_id").eq("opportunity_id", opp_id))
        ),
        "cold_start": len(
            rows(sb.table("cold_start").select("opportunity_id").eq("opportunity_id", opp_id))
        ),
        "memos": len(
            rows(sb.table("memos").select("opportunity_id").eq("opportunity_id", opp_id))
        ),
        "trace_log": len(rows(sb.table("trace_log").select("id").eq("opportunity_id", opp_id))),
    }

    if not dry_run:
        retry(sb.table("opportunities").delete().eq("id", opp_id).execute)

    return {
        "deleted": opp_id,
        "dry_run": dry_run,
        "company": (existing.get("company") or {}).get("name"),
        "source": existing.get("source"),
        "status": existing.get("status"),
        "cascaded": cascade,
    }


@app.delete("/claims/{claim_id}")
def delete_claim(claim_id: str):
    """Remove a single claim. Lanes need this to undo a bad extraction batch."""
    existing = one(sb.table("claims").select("*").eq("claim_id", claim_id))
    if not existing:
        raise HTTPException(404, f"claim {claim_id} not found")
    retry(sb.table("claims").delete().eq("claim_id", claim_id).execute)
    write_trace(
        existing.get("opportunity_id"),
        "verify",
        f"claim deleted: {existing.get('text', '')[:100]}",
    )
    return {"deleted": claim_id, "opportunity_id": existing.get("opportunity_id")}


@app.post("/opportunities/{opp_id}/claims/dedupe")
def dedupe_claims(opp_id: str, dry_run: bool = False):
    """Collapse claims identical in (text, type, source), keeping the earliest.

    A re-run of an extraction batch duplicates every claim; the UI then renders
    each one twice. Pass ?dry_run=true to see what would go without deleting.
    """
    claims = rows(
        sb.table("claims").select("*").eq("opportunity_id", opp_id).order("created_at")
    )
    seen: Dict[tuple, str] = {}
    doomed: List[Dict[str, Any]] = []
    for c in claims:
        key = (c.get("text"), c.get("type"), c.get("source"))
        if key in seen:
            doomed.append(c)
        else:
            seen[key] = c["claim_id"]

    if not dry_run:
        for c in doomed:
            retry(sb.table("claims").delete().eq("claim_id", c["claim_id"]).execute)
        if doomed:
            write_trace(opp_id, "verify", f"deduped {len(doomed)} duplicate claims")

    return {
        "opportunity_id": opp_id,
        "before": len(claims),
        "kept": len(seen),
        "removed": len(doomed),
        "dry_run": dry_run,
        "removed_claim_ids": [c["claim_id"] for c in doomed],
    }


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

    existing = one(sb.table("founder_scores").select("*").eq("identity", identity))
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
    saved = one(sb.table("founder_scores").upsert(row, on_conflict="identity"))

    # mirror onto every opportunity belonging to this founder
    snapshot = {
        "value": saved["value"],
        "confidence": saved["confidence"],
        "trend": saved["trend"],
        "history": saved["history"],
    }
    retry(
        sb.table("opportunities")
        .update({"founder_score": snapshot})
        .eq("founder->>identity", identity)
        .execute
    )

    write_trace(
        body.opportunity_id,
        "axis_score",
        f"founder score {body.value} for {identity} (trend {trend}, n={len(history)})",
    )
    trace_from_body(body.model_dump(), body.opportunity_id, "axis_score")
    return saved


@app.get("/founder-score/{identity:path}")
def get_founder_score(identity: str):
    found = one(sb.table("founder_scores").select("*").eq("identity", identity))
    if not found:  # tolerate a bare handle or name
        for guess in (f"github:{identity.lower()}", normalize_identity(None, identity)):
            found = one(sb.table("founder_scores").select("*").eq("identity", guess))
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
    opps = rows(q.limit(limit))
    if not opps:
        return []

    ids = [o["id"] for o in opps]
    axis_by_opp = {
        a["opportunity_id"]: a.get("axes") or {}
        for a in rows(sb.table("axis_scores").select("*").in_("opportunity_id", ids))
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
    opp = one(sb.table("opportunities").select("*").eq("id", opp_id))
    if not opp:
        raise HTTPException(404, f"opportunity {opp_id} not found")

    identity = (opp.get("founder") or {}).get("identity")
    founder_score = None
    if identity:
        founder_score = one(
            sb.table("founder_scores").select("*").eq("identity", identity)
        )

    return {
        "opportunity": opp,
        "claims": rows(sb.table("claims").select("*").eq("opportunity_id", opp_id)),
        "axis_scores": one(
            sb.table("axis_scores").select("*").eq("opportunity_id", opp_id)
        ),
        "cold_start": one(
            sb.table("cold_start").select("*").eq("opportunity_id", opp_id)
        ),
        "memo": one(sb.table("memos").select("*").eq("opportunity_id", opp_id)),
        "founder_score": founder_score or opp.get("founder_score"),
        "trace_log": rows(
            sb.table("trace_log")
            .select("*")
            .eq("opportunity_id", opp_id)
            .order("ts", desc=False)
            
        ),
    }


@app.get("/thesis")
def get_thesis():
    t = one(sb.table("thesis").select("*").limit(1))
    if not t:
        raise HTTPException(404, "no thesis row — run schema.sql")
    return t


@app.put("/thesis")
def put_thesis(body: Any = Body(...)):
    body = body if isinstance(body, dict) else {}
    params = body.get("params", {k: v for k, v in body.items() if k != "trace"})
    existing = one(sb.table("thesis").select("id").limit(1))
    row = {"params": params, "updated_at": now_iso()}
    if existing:
        saved = one(sb.table("thesis").update(row).eq("id", existing["id"]))
    else:
        saved = one(sb.table("thesis").insert(row))
    trace_from_body(body, None, "enrich")
    return saved


@app.get("/health")
def health():
    return {"ok": True, "ts": now_iso()}
