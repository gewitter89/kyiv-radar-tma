# v1.45 — no guessed room counts (private feed quality gate)

## What this prevents
A source title can explicitly say "2-кімнатна", while structured metadata says
"1 room". Users may see a misleading listing even though the source is a
different property. We must never silently "correct" the count by guessing.

The private intake checks only **permissioned** title/description text if the
source supplies those fields. It detects explicit Ukrainian/Russian room-count
claims (numeric, 1–5 word forms), not "studio", bedroom count, floor, bathrooms,
or unknown values. Contradictory source claims or disagreement with structured
count cause the batch to fail transactionally. Missing rooms remain unknown.

- `scripts/room_claims.py` is deliberately narrow. It cannot establish if
  the original website's current source page is correct or still active.
- XML/YRL parsers carry title/description only in transient Python objects;
  normalization drops them before inventory DB persistence. It does not
  ingest raw phones, media, full text or guess from unvisited URLs.
- Catalog integrity report gives anonymous mismatch counts and numeric IDs
  for manual reviewer followup. Do not publish private evidence or fake
  verification badges.
- The publicly served catalogue is still zero unlicensed historical items.
  This improvement does not fetch, license, or publish any real listing.

## Tests and rollout
The adapted tests are synthetic and exercise Ukrainian/Russian variants,
no false positives, mismatches, malformed/oversized source text, XML, YRL,
private-data non-persistence, and atomic rollback of conflicting feed batch.
The v1.45 branch also adds these tests to CI's partner and broad Quality jobs.
This clean focused change does not merge old stacked PR #57 wholesale, since
its branch contains stale frontend/static catalog changes.

Do not enable partner intake or public presentation absent explicit provider
permission for the actual fields and a current source-availability gate.
