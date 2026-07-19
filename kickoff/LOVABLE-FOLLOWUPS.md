# Lovable follow-up prompts (paste one at a time)

## 1 — Apply page with pitch deck upload

Add an "Apply" page at route `/apply`, linked from the top nav as "Apply".

Form fields: Company name (required, the only required field), One-liner, Founder name, GitHub handle, Location, Sector (same options as thesis: inference, agent frameworks, vector/data tooling, eval & observability), Stage (default "pre-seed"), and a pitch deck upload (PDF, drag-and-drop or file picker, max ~10 MB).

On submit, `POST ${API_BASE}/apply` with JSON:

```json
{ "company_name": "...", "one_liner": "...", "founder_name": "...",
  "github_handle": "...", "location": "...", "sector": "...", "stage": "pre-seed",
  "deck_base64": "<base64 of the PDF, no data: prefix needed>",
  "deck_filename": "deck.pdf" }
```

Omit `deck_base64`/`deck_filename` entirely if no file was chosen. The response is the full opportunity row including `id`. On success show a confirmation with the company name and a "View in pipeline" link to `/opportunity/{id}`. Show a spinner while uploading and a readable error message on failure. Keep the form minimal and calm — deck + name is the whole bar.

## 2 — Fix memo citation chips

On the memo page, citation markers are rendering as raw UUIDs and literal `[claim:uuid]` text. Fix the memo renderer:

- Anywhere memo text (any section, including inside SWOT bullets and numbered hypotheses) contains `[claim:<uuid>]`, replace it with a small superscript numbered chip (¹, ², … numbered in order of first appearance).
- Also handle the variant where the marker appears as a bare UUID followed by "[?]" — same treatment.
- Clicking or hovering a chip opens the same evidence popover used in the Claims & Trust panel: claim text, trust status chip (icon + label + color), source snippet, external URL, confidence bar, note. Look the claim up by id in the bundle's `claims` array; if the id isn't found, render the chip in muted gray with a "claim not found" tooltip instead of showing the raw UUID.
- Never display a raw UUID anywhere in the memo body.

## 3 — Draft outreach modal

On the memo page footer and the opportunity detail header, when `opportunity.source` is `outbound_github` or `outbound_hn`, show a "Draft outreach" button. It opens a modal with a pre-filled friendly email: subject "Impressed by {repo/company} — quick chat?", body referencing one corroborated claim (e.g. stars/HN traction), the fund's one-line thesis, and a scheduling ask. Editable textarea + "Copy to clipboard" button. Mock text is fine — no API call needed.

## 4 — NL query bar on Pipeline

Add a query input at the top of the Pipeline table, placeholder: "technical founder, Berlin, AI infra, no prior VC backing". On Enter, `POST ${INTEL_BASE}/nl_query` with `{"q": "<text>"}` and show the returned opportunities in the table (falling back to client-side keyword filtering over company, one-liner, founder, sector, location if the request fails). Add a small "clear" affordance to return to the full ranked list. `INTEL_BASE` is a constant next to `API_BASE`.

## 5 — Small detail-page fixes

- If `opportunity.deck_url` is non-null, show a "View deck" link (external) in the detail header. Render this off `deck_url` only, never `deck_present`.
- If `memo.what_would_change_my_mind` exists (string or list), render it on the memo page as its own section "What would change my mind" above the recommendation banner.
