# VC Brain Spine — API for Lanes 2, 3, 4

Base URL: `http://localhost:8000` (replace with the tunnel URL once shared)
Interactive docs: `{BASE}/docs` · CORS is open to `*`, no auth.

The contract in the kickoff doc is **frozen**. Field names below are exact.

---

## Writing

Every write endpoint accepts **an object, a list of objects, or `{"<plural_key>": [...]}`** — all three shapes work. Every write endpoint also accepts an optional `trace` key (object or list) that gets stored in `trace_log`:

```json
{ "opportunity_id": "…", "axes": {…},
  "trace": { "step": "axis_score", "detail": "why", "evidence_refs": ["url"] } }
```

Each endpoint also writes its own trace row automatically, so you only need `trace` when you want to add detail.

| Endpoint | Who | Notes |
|---|---|---|
| `POST /apply` | Lane 2 (inbound form) | Only `company_name` required. |
| `POST /opportunities` | Lane 4 | Bulk. Generates `id`, defaults `status: new`. |
| `POST /claims` | Lane 2/3 | Bulk. Returns rows with `claim_id` — keep them for `claim_refs`. |
| `PATCH /claims/{claim_id}/trust` | Lane 3 | Body `{"trust": {…}}` or the trust object bare. |
| `POST /axis-scores` | Lane 3 | Upsert on `opportunity_id`. Flips status → `screened`. |
| `POST /cold-start` | Lane 3 | Upsert on `opportunity_id`. |
| `POST /memos` | Lane 3 | Upsert on `opportunity_id`. Flips status → `memo_ready`. |
| `POST /trace` | anyone | Standalone trace rows. |
| `POST /founder-score` | Lane 3 | See below. |
| `DELETE /claims/{claim_id}` | Lane 2/3 | Removes one claim. 404 if unknown. |
| `PATCH /opportunities/{id}` | Lane 4 | Partial update. Nested objects **deep merge** — `{"company":{"name":"x"}}` keeps sector and one_liner. |
| `DELETE /opportunities/{id}` | Lane 4 | Removes the row; claims, axis scores, cold start, memo and traces cascade. `?dry_run=true` reports the blast radius first — **always dry-run before deleting a scored row.** |
| `POST /opportunities/{id}/claims/dedupe` | Lane 2/3 | Collapses claims identical in `(text, type, source)`, keeping the earliest. `?dry_run=true` reports without deleting. Use after re-running an extraction batch. |

An unknown field now returns **400 with the offending column name**, not a 500. If you get `unknown column — schema migration needed`, the field needs a migration — ask, don't work around it.

`POST /memos` accepts `what_would_change_my_mind` (jsonb — string or list) alongside `sections`, `gap_flags`, `claim_refs`, `recommendation`.

### `POST /apply`
```json
{ "company_name": "Acme",            // ← the only required field
  "one_liner": "", "founder_name": "", "github_handle": "",
  "twitter": "", "linkedin": "", "location": "", "sector": "", "stage": "pre-seed",
  "deck_url": "https://…",           // fetched and stored, falls back to the link
  "deck_base64": "JVBERi0…",         // data: URIs tolerated
  "deck_filename": "deck.pdf" }
```
Returns the full opportunity row. Deck bytes go to the public `decks` bucket; `deck_url` on the row is the stored public URL.

### `POST /founder-score`
```json
{ "identity": "github:adaokonkwo",   // or pass github_handle / founder_name instead
  "value": 78, "confidence": 0.6, "reason": "shipped OSS", "opportunity_id": "…" }
```
- Identity is `github:<handle>`, falling back to `name:<slug>`. **Always send `github_handle` when you have it** so a founder resolves to one key.
- Appends `{value, ts, reason, opportunity_id}` to `history`. Never resets.
- `trend` is recomputed from the last two values (`up` / `down` / `flat`).
- Mirrors the snapshot onto every opportunity sharing that identity — a founder's second application shows their prior history.

---

## Reading

### `GET /opportunities`
Query params, all optional: `sector`, `stage`, `min_founder_score`, `source`, `status`, `limit`.

`sector` and `stage` are substring matches (`?sector=eval` matches `eval & observability`). Ranked by `axes.founder.score` descending, falling back to `founder_score.value` where Lane 3 hasn't scored yet. Each row carries an extra `axes` key so list views can render the three axes without a second call.

### `GET /opportunities/{id}/bundle` ← **Lane 4 renders the detail page from this**
One call, everything:
```json
{ "opportunity": {…}, "claims": [...], "axis_scores": {"opportunity_id":"…","axes":{…}},
  "cold_start": {…}, "memo": {…}, "founder_score": {…}, "trace_log": [...] }
```
`axis_scores`, `cold_start`, `memo` are `null` when not yet written — render defensively.

### `GET /founder-score/{identity}`
Accepts `github:handle`, a bare handle, or a name. 404 if unknown.

### `GET /thesis` · `PUT /thesis`
`PUT` body: `{"params": {…}}`. Seeded with the fund thesis (pre-seed AI infra, $100K, 5–8%, high risk).

---

## Seeded rows to code against

| id | company | sector |
|---|---|---|
| `11111111-1111-1111-1111-111111111111` | Tensorwake | inference |
| `22222222-2222-2222-2222-222222222222` | Groundtruth | eval & observability |

---

## Rules

- `deck_present` is **derived, never trusted**. It is true only when `deck_url` is non-null, enforced by a DB constraint. Don't set it yourself — send `deck_url`/`deck_base64` and let the spine decide. Render the deck affordance off `deck_url`, not `deck_present`.
- The three axes are **never** averaged. There is no combined score field anywhere, and there will not be one.
- Trust Score is **per claim**, never per company.
- Cold start reports a band + interval, not a point score.
- Contract fields will not be renamed. If you need a new field, ask — additive only.
