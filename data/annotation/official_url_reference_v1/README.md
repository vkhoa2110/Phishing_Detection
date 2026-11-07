# Official-origin URL reference review, v1

This is an **assistant-curated origin reference**, not a benign/phishing gold set.
The collection does not infer website safety, ownership, absence of compromised
content, or safety of another URL on the same domain. No domain allowlist is
installed in the application.

The fixed selection contains 36 routes: eight Vietnamese and 28 international,
across 16 registrable-domain groups under the project's pinned PSL rules. It
covers banks, government, universities, utilities and account-support services.
The route tags cover login, password reset, payment, query parameters, articles
and long paths. Selection order, quotas, permitted hosts and a collector-code
hash were locked before collection and before any model scoring. There are no
score-based replacements for sources that fail retrieval.

The one-pass collection on 2026-11-07 documented **29/36 selections**, covering
all 16 domain groups: seven Vietnamese routes and 22 international routes. Seven
failures are retained. All six requested route categories are represented. There
are four login-tagged, five password-reset-tagged, five payment-tagged, three
query-tagged, five long-path-tagged and ten article-tagged records; tags overlap.
Twenty-four routes overlap historical URL/domain exclusions; five remain
origin-reference review candidates. These counts describe collection, not model
quality.

Files:

- `selection.json` and `selection.json.sha256`: fixed selections and collection
  rules, including a hash of the existing prospective registration.
- `records.jsonl`: successfully documented routes; `label=null`,
  `label_scope=official_origin_reference`, `label_status=assistant_curated`,
  and no reviewer IDs.
- `attempts.jsonl`: every locked selection, including failures.
- `collection.json` and `collection_locks.json`: counts, coverage, limits and
  hashes of the immutable collected records.
- `review.csv`: blank origin assessment, URL-risk label, rationale and reviewer
  fields. A human's completed sheet should be saved as a new version; it does
  not change these locked records into gold automatically.

Evidence records retain the source URL, publisher, actual retrieval UTC time,
final source URL, status, redirect chain, robots metadata and a local snapshot
path/SHA-256. Source excerpts are limited to a short title and anchor. Full HTML
and robots responses stay in ignored
`artifacts/evaluations/official_url_reference_v1/snapshots/`; they are not
redistributed with the small metadata files.

`published_link` means the saved source HTML contains an exact normalized link
to the selected route. `self_served_document` means the selected route itself
served an HTML document; this is weaker origin evidence and does not independently
authenticate the publisher. The assistant chose the official-domain identities;
the collector does not authenticate them. A linked route need not have been
fetched itself: evidence supports publication, not current target availability.
Of the 29 collected records, seven use a separate official source document that
links the route. The other 22 use the selected document as its own source; 15 of
these contain self-links and seven have `self_served_document` evidence. A
`published_link` on the same selected page is still self-publication, not an
independent endorsement.

Exact URL or registrable-domain overlaps with the existing prospective exclusion
index are assigned to `regression`. Other records remain
`new_origin_reference_review_only`. **Neither pool is eligible for the registered
prospective benchmark:** there are no independently verified risk labels, and
unknown campaign identity does not establish isolation. Once scored, these are
also adaptive development references and cannot become an untouched test.

Verify saved hashes and evidence locally without making network/model/API calls:

```bash
.venv/bin/python -B -m evaluation.official_url_references verify \
  --out data/annotation/official_url_reference_v1
```

Collection is a one-pass, allowlisted HTTPS GET operation with robots checks,
per-host spacing, source-size limits, no forms or authentication, and no malicious
URL fetching. Retrieval/TLS/robots/publication failures remain failures; the
collector never disables certificate validation or retries failures in place.
TLS success and an official-origin reference are not benign risk labels.

## Local review worksheet

The generated Vietnamese worksheet is at
`artifacts/evaluations/official_url_reference_v1/review/index.html` (local,
ignored). It shows all 29 records without model scores, decisions or source risk
labels. Origin assessment and URL-risk assessment are separate, and all fields
start blank. UNKNOWN is an explicit reviewed decision, distinct from unfinished.

Enter your own reviewer ID and reasons, then download a new CSV. Export keeps the
same eight columns as `review.csv`; incomplete rows remain blank and receive no
reviewer attribution. A decision needs a rationale. CSV cells are formula-escaped.
The page does not open URLs, make external requests, save browser data or modify
the source records. Reloading loses unexported changes. It creates no additional
reviewers, and one person's worksheet is not gold.

Generate another fresh worksheet after verifying the locked reference:

```bash
.venv/bin/python -B scripts/data/render_official_review.py \
  --out artifacts/evaluations/official_url_reference_v1/review/index-new.html
```

Existing output files are never overwritten. Browser checks cover four viewport
sizes, blank defaults, no automatic risk selection, UNKNOWN, CSV schema/formula
escaping, no stored state, no external requests, and hostile metadata rendered as
text. Smoke-test CSV values are fixtures and are deleted, not saved as labels.
