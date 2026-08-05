# CLAUDE.md - the rules every agent on this repository runs under

This file did not exist until 2026-08-05, although every agent had been told to
read it. `audit/FINDINGS.md` records that absence as **OBS-1**. The rules below
are not generic advice: every one of them is the residue of something that went
wrong here, and each carries the case that produced it so it can be checked
rather than believed.

**Precedence.** This file governs the whole tree. A subdirectory CLAUDE.md
(`research-agents/CLAUDE.md`) adds effort-specific rules on top; where they
conflict, the narrower file wins inside its own directory and this one wins
everywhere else. Nothing in either file overrides an explicit instruction from
the user.

**Where the evidence for the rules below lives.** These documents are on
different branches and worktrees; the paths are given so no claim here has to be
taken on trust.

| document | where |
|---|---|
| `COORDINATION.md` | repository root, every worktree (the shared cross-agent log) |
| `audit/FINDINGS.md`, `audit/CLAIMS_AUDIT.md` | branch `audit`, worktree `C:\Users\karti\wt-audit` |
| `cli/docs/HARDENING_LOG.md` | branches `cli-perfect` / `audit-fixes` (`wt-cliperfect`, `wt-fix`) |
| `research-agents/docs/CAPABILITY_MAP.md`, `ROUNDS_LEDGER.md`, `TEST_LOG.md`, `MECHANISM_AUDIT.md` | branch `capability-complete` / `audit-fixes` (`wt-cap`, `wt-fix`) |
| `research/FINDINGS_*.md` | one per experiment, on that experiment's branch |
| `reviews/science/CLAIMS_AUDIT.md`, `reviews/code/AUDIT_LOG.md` | branches `reviewer-science`, `reviewer-code` |
| `collab/COLLAB_LOG.md`, `collab/API_CONTRACT.md` | branch `collab-backend` |

---

## 1. Completion enforcement

**An agent may not end a session until every completion criterion for its task is
provably met and documented with cited evidence.**

Any urge to summarize, hand back, or ask what to do next is a signal to check the
criteria and keep working. It is not permission to stop.

Before any final summary, state **each criterion as MET or UNMET**, each with
specific evidence:

- a test count from a run that actually finished (`793 passed, 2 skipped` - not
  "the suite passes"),
- a file path,
- a measured number with its units and its conditions,
- a commit hash.

**An unverified claim counts as UNMET.** So does a claim whose evidence is a
document rather than a run. If any criterion is UNMET, generate work targeting
it and continue; do not report completion.

Two sessions on this project had to write *"a run at N is queued and until it
finishes this row will keep saying so"* rather than round a pending number up.
Do that again rather than guess.

---

## 2. Verify by executing, never by reading

A test that has never been observed to fail is not evidence. A suite that
reports green is a claim, not a result.

**The cases this rule exists for.**

- **Three async tests were counted and never ran** (`cli/docs/HARDENING_LOG.md`,
  entry H100). `pyproject.toml` had set `asyncio_mode = "auto"` since the TUI was
  written, but `[project.optional-dependencies] dev` never declared
  `pytest-asyncio`. Without the plugin the option is not one pytest knows, and
  the whole failure surfaced as a single line -
  `PytestConfigWarning: Unknown config option: asyncio_mode` - inside the
  warnings summary, **below the pass count**, in a suite the log says to run with
  `-q`. The three `async def` tests in `test_display_contract.py` did not
  execute. The documented "fresh install" verification produced exactly this
  environment.
- **Three of this project's own tests were found passing while checking nothing**
  (`audit/FINDINGS.md`, "Three defects were found in this audit's OWN
  test-writing"), each caught by running a negative control rather than trusting
  a green result: the F006 leak probe compared against `json.dumps(...)`, which
  escapes every backslash on Windows, so it reported clean for a leak that was in
  its own output; the F001 route-table test would have **hung** rather than
  failed on a regression, because `/stream` blocks without the guard; and the
  prompt-injection test passed with the filter stubbed out, because the
  instruction it used made the rule planner return an action, so `_finalize`
  discarded the model's reply for an unrelated reason.
- **A scanner whose positive control skips when the scanner degrades** (F004).
  `_scanner_patterns()` returns `[]` when the vendored pattern set is missing,
  and the one test whose job is to notice responds with `pytest.skip`. The other
  tests keep running at 4 patterns instead of the full set and report the same
  colour.

**The rule that follows.** An incomplete test environment makes a run look
*greener* than it is, and that is exactly the case where silence is the wrong
answer. An unavailable engine makes a run look redder than it is, so a banner may
stay quiet there. The suite banner for a missing test dependency prints **even on
a green run**, headed *"TEST ENVIRONMENT INCOMPLETE - tests below are NOT RUN,
not passing."* Keep it that way.

In practice:

- Run the suite and **read every failure and every warning**, not the total.
- Before trusting a new test, **make it fail on purpose** and watch it go red.
  `test_the_detector_itself_fires_when_the_plugin_is_absent` exists because every
  other banner test monkeypatched the detector and so proved nothing about it.
- `str.replace` does not complain when its pattern is absent. Assert the count,
  then verify the file changed.
- A round or check reporting `0/0 behaved` is broken, not clean (F93).

---

## 3. Verify mechanisms, never inherit them

A component can be imported, called, covered by tests, and still do nothing.
**Prove every relied-upon component executes and does what its description says,
on real data**, before building on it or reporting a result that depends on it.

**The cases this rule exists for.**

- **`detect_pieces` was assumed functional for weeks and returns one piece on
  every real torn section.** It cuts kNN edges longer than 2.2 spot pitches on the
  assumption that a tear opens a gap; this benchmark's tear slides a region
  *along* the cut, so the fragments stay in contact and no edge is stretched.
  `research-agents/docs/MECHANISM_AUDIT.md` grades it **DIFFERS**: 1 piece on
  `DLPFC_151508_s3_seed0`, 1 on `DLPFC_151508_s4_tear_seed1`, and 2 only on a
  synthetic slice cut with a 9-pitch gap. Consequence, from
  `research/FINDINGS_model_until.md`: *"Every 'piecewise' number in the earlier
  write-ups on this benchmark is therefore a single GLOBAL fit, and the
  piece-aware branch of the search space had never actually been tested."* The
  numbers were right; the published mechanism descriptions were wrong.
- **`gate_refine` was graded INERT by an audit whose population was wrong; it
  actually fires.** The first mechanism check exercised it on a synthetic
  near-perfect base - an input the pipeline itself declines - and returned
  **FIRES** on evidence that said it made things worse
  (*"median error 0.415 -> 0.859 spot pitch"*), because the check only ever asked
  "did it move anything" (F112). Repaired to measure **recorded real runs**
  first, it then said `INERT - applied to 0 of 2 real pairs` (F113): the
  deployment guard decided from the base method's *name* (`only_ot=True`), the
  router picks Sutura for most real pairs, so the correction was computed, scored
  and thrown away on every real pair - including `c603`, where the measurement
  said it cut median registration error by 1.393 spot pitch. Fixed by deciding
  from the **measurement first, the name second**; `C603` now applies it and
  improves 5.514 -> 4.121 spot-pitch median error.

**The rule that follows.**

- A mechanism audit must have a verdict vocabulary that can say the unflattering
  thing. **FIRES / INERT / DIFFERS / HARMS / N/A**, with a number attached to
  each verdict. A check that can only say "it ran" cannot answer "did it work".
- **Get the population right.** The subject of the check must be the real runs
  the product actually produces, not a synthetic probe. A synthetic probe is
  admissible only as explicitly-labelled out-of-envelope evidence.
- When a fix makes something newly load-bearing, **that thing needs its own
  test**, not just the fix. F102 made a hang depend on `liveness`, which had no
  test; F103 and F104 both came through that door.
- If two products ship the same algorithm with opposite deployment decisions,
  one of them is wrong. That was the CLI and the research agent on `gate_refine`,
  and it went unnoticed until the audit population was corrected.

---

## 4. Silent wrongness outranks crashes

**Three quarters of all findings on this project were silent failures.** The
priority order for closing gaps is: **silent wrong answers, then crashes and
hangs, then format and platform coverage, then scale, then request handling.**

The recurring shapes, from `research-agents/docs/ROUNDS_LEDGER.md` and
`docs/CAPABILITY_MAP.md`:

| shape | real instances |
|---|---|
| work done without saying so | F55 - a folder named `warped` made the planner run a 20-minute alignment nobody asked for; F76 - an explicit section order applied but never recorded |
| data quietly dropped by caps and filters | F53 `max_sections`, F57/F75 `max_spots` - counts and scores described a subset while looking like the whole |
| a number reported without its conditions | F46 a 1000x coordinate-scale mismatch unflagged; F59 QC verdicts without their thresholds; F47 an installed-package list read as a claim of use |
| NaN folded into an average | F62 a NaN score written down as a score; F73 a NaN metric writing invalid JSON into the record; F77 an unmeasurable spot pitch reported as NaN; F96 a measured -0.000047 rounded to 0.0 **at record time**, one layer below where F48 had protected printing |
| input interpreted differently than intended | F56/F64 - "at least 1,000 counts" parsed as a folder called `least`, so the QC threshold silently became the default; F72 - a table wired into a section input read as an empty section set, and the tool answered confidently about nothing |
| a fingerprint that missed changed content | **F80** - a folder's fingerprint missed a file whose content changed but whose length did not, so two runs on different data compared as though they matched |

**The rule that follows.** For every "success", ask: *would a wrong result
actually have been caught here?* If the only thing standing between a wrong
answer and a green report is that nothing raised, the check is not a check.

Specifics that cost real defects to establish:

- **A zero from a step that ran is a measurement; a zero from a step that did not
  run is not.** A metric may only come from a step that finished (R172).
- Never present a measured value as zero. Rounding at the point of *recording*
  destroys signal that printing-time guards cannot recover (F96 vs F48).
- A cap, subsample or filter must be disclosed **wherever the number it affected
  is quoted**, not once at the top.
- An audit that cannot audit something must count it as **unchecked, not clean**,
  and name it (F111's shape: *"Runs that could not be audited - counted as
  unchecked, not as clean"*). A hole an audit does not name is indistinguishable
  from no hole.
- A leakage or coverage check built on a hardcoded file list reports the same
  PASS whether it is looking at everything or at half of it (F008: `SCORING_PATH`
  is four filenames; three later modules that produce scored CSVs are not
  scanned). Derive the population, do not enumerate it.

---

## 5. Recompute every number from raw results before publishing it

**Never quote a figure from a summary, a prose handoff, or another document.
Recompute it from the committed artifact - the CSV, the run record, the log -
and cite that artifact.**

Reported figures on this project have drifted upward from the committed data more
than once, and the drift has always been flattering.

**The shipped claim.** `cli/sutura_cli/core/refine.py:8` shipped *"cut PASTE2's
median registration error by 10-35%"*. Recomputed from
`research/results/hybrid_validate.csv`, paired within donor on `(severity, seed)`
with no cell present in one arm and not the other, the arithmetic is **exactly
right**: Br5292b 4.643 -> 3.008 (35.22%), Br5595b 5.659 -> 4.835 (14.55%),
Br8100b 5.468 -> 4.897 (10.43%). What the range hides is the finding (F009):

- **The floor is not 10%.** Broken out by severity, the severity-8 cuts are
  **6.21%** (Br5595b) and **3.66%** (Br8100b) - below the stated floor by nearly
  a factor of three, and exactly where the tool matters most. `audit/FINDINGS.md`
  then corrects its own reporting of this figure: pooling both severity-8 donors
  gives **4.94%**, and the true per-cell minimum across the panel is **2.62%**.
  Quote it with that correction attached; the finding is if anything understated.
- **The donor supplying the 35% ceiling is missing its two hardest cells.**
  Br5292b has 12 cells to the others' 14 because PASTE2 itself hit the **900 s
  watchdog** at severity 8 (`status=error`, `TimeoutError: exceeded 900s`). So
  the top of the range is measured on severities 0-6 while the bottom is measured
  on 0-8. Matching the grids moves the other donors *up* (14.55 -> 16.08%,
  10.43 -> 11.71%).
- **An earlier correction of this same figure to "6-35%" found one of the two low
  cells and stopped.** A correction is not automatically a floor.

**The circulating headline that appears in no committed artifact.** The figures
carried between sessions in prose - `L_blend2` at **2.758-2.859** vs PASTE2
**4.534**, 100% of **225** cells - occur in none of `FINDINGS_any_tissue.md`,
`FINDINGS_any_tissue_r4.md` or `COORDINATION.md` at the branch commit. The
committed record, recomputed from `any_tissue.csv` (4,887 rows, all `status=ok`),
says **2.721**, **4.568**, **205 cells**. The value `4.534` occurs once in the
whole document, as a single cell of a `base_fusebr` per-dataset row measuring a
different thing. The drift is monotonically flattering: lower error, higher
baseline error, more cells. **A resuming session that trusts a prose summary
rather than the CSV will propagate three wrong numbers.**

**And read the number's support, not just its size.** Of the 205 cells behind
"100%", 132 are DLPFC (the in-distribution corpus) and 73 are genuinely unseen
tissue. 73 cells across 5 unseen datasets is a real result; it is not 205 cells
of unseen tissue, and a headline that does not say which is not reportable.

In practice:

- Pair explicitly and check both arms for missing cells before computing a delta.
  State the pairing key.
- State the **worst case** alongside any range. A performance claim without its
  worst case is a marketing number.
- Say what the number is a range *over* - three donor means is not a range over
  outcomes.
- Carry the conditions with the claim to wherever it ships: which datasets, which
  variant, synthetic or real tears, how many seeds, against which baseline.
- Every count quoted in any document must equal what the code produces. Where a
  generator exists (`sync_doc_counts.py`, `recompute_gate_claims.py`,
  `recompute_headline.py`), it is the source and the prose is downstream.

---

## 6. Leakage discipline

**A spectacular result on this project has already been retracted for training on
the evaluation target.** A self-supervised residual "beat PASTE2 off-distribution
on breast, 1.20 vs 3.65". It had been trained on the A-B array-bridge
correspondence, which *is* the evaluation target. Trained leakage-free - only on
synthetic self-warps of the reference section - it **loses to PASTE2 on every
dataset**: breast 6.02 vs 3.65, mouse 6.28 vs 5.47, DLPFC ~13-14. The "1.20" was
the leak's dataset-independent signature, reproducing as ~0.8-1.9 *everywhere*,
because it trains on the answer. Combining it with the genuine result made the
genuine result worse.

**Any claimed improvement must pass the five-check audit, run rather than read.**
The reference implementation is in `research/FINDINGS_model_until.md` and
`research/results/leakage_audit.txt`; `A0` is the uncorrupted reference:

| check | what it does | what it must show |
|---|---|---|
| `A1_train_shuffled` | training targets permuted between spots | the advantage EVAPORATES (>= baseline). If it survives, the win never came from the targets |
| `A2_train_noise` | training targets replaced by noise | same |
| `A3_feature_noise` | trained model kept, input descriptors randomised at inference | performance DEGRADES. If it does not, the model is ignoring its inputs |
| `A4_gt_poison` | every held-out pair's ground truth set to NaN **before** the training set is assembled, then the training set rebuilt from scratch | performance UNCHANGED **and weights bit-identical**. That is a proof, not an assurance, that no test target reached training |
| `A5_eval_shuffled` | every config scored against a shuffled evaluation ground truth | every error explodes to the random-correspondence floor. This is the check that the metric reads the ground truth at all |

Alongside them, run the **static fold-composition audit** (train and held-out
slice lists, overlap must be NONE, per fold; eval warp seeds disjoint from
training streams) and, where a cheap base exists, the **oracle control** - a
cross-donor result must not exceed a deliberately leaky oracle trained on the
test.

**An unaudited win counts as no win.** Do not report it, do not build on it, do
not carry it into a summary. If an audit passes, name the file it wrote.

Two further specifics learned here:

- Prove GT-freedom and feature-freedom by **corruption**, not by inspection: the
  gate produces bit-identical output when ground truth and features are trashed,
  which is why it survived where the residual did not.
- Using the array bridge to *decide at deploy time* whether to keep a refinement
  is a measurement, not a leak - `array_row`/`array_col` are in the data when the
  user runs it. Using it in *training* is a leak. Keep the distinction explicit
  wherever it appears.

---

## 7. Honesty requirements

- **Never fabricate a metric or a capability.** Not in a report, not in a demo,
  not in a summary, not as a placeholder.
- **Every result names the method that produced it.** No number appears without
  its provider. Where a real accuracy cannot be computed - no array-index bridge
  - the reported figure is a **collapse proxy**, never an accuracy, and is
  labelled as one everywhere it appears.
- **Anything the system cannot do is refused explicitly, at the point where
  someone would ask for it, never approximated.** Segmentation, deconvolution,
  trajectory inference, image registration, anything clinical, forcing an
  aligner, Stereo-seq ingest - each is refused with its reason and, where one
  exists, a remedy. A refusal that loses its remedy is a defect (F114).
- **Report negatives plainly.** The retracted leak, the tear detector that never
  fired, the never-regress guarantee that is empirical rather than absolute, the
  five platforms implemented against synthesized bundles with no real instrument
  output in this repository - all of these are in the record in those words. Keep
  it that way.
- **"No attack finds anything" is not the same as "correct."** The rounds ledger
  states this deliberately: five consecutive clean rounds is the completion
  criterion and it has been met several times over, but nearly every batch aimed
  at a genuinely *new* surface kept finding something. The honest reading is
  "these attacks no longer find anything, and the ones that did are fixed with
  tests that fail if they come back."
- **The verifier is usually the designer here, and that is a real limitation.**
  The available independence fix is **mutation**: break the system on purpose and
  require the check to notice. Reverting a sanitiser must make its hypotheses
  fail; stubbing a load-bearing function must make its hypotheses fail; both must
  recover.
- A hypothesis that fails because *your own assertion* was wrong is recorded as a
  harness bug, by name, not quietly corrected. There have been twenty-one of
  them.
- A published row that turns out to have overstated what it verified is
  **corrected in place and marked as corrected**.

---

## 8. Resource discipline

This machine has crashed under load. The evidence, not the folklore:

- A collab backend **died with a real `MemoryError`** (468 MiB on a
  (3661, 33538) matrix) because `ensure_adata` kept four copies of a combined
  DLPFC matrix where two suffice and never released them, so memory was the sum
  over every session that had ever run.
- Two further failures were `MemoryError` **inside PASTE2 and harmonypy** under
  the same pressure - not regressions, the box.
- A seven-round batch **segfaulted**; a watch test failed with
  `memory allocation failed for chunk`; a Ray pool took the machine to **0.48 GB
  free** and stalled. Free memory here is routinely under 1 GB while other
  worktrees run heavy jobs.

**The rules.**

- **Cap concurrent sub-agents at four.**
- **Never run more than one heavy compute job at a time.** Serialise long
  verifications; do not run the full suite and a replay together.
- **Reduce concurrency if the machine slows.** Treat a slowdown as the signal it
  is, before the segfault.
- A full-resolution PASTE2 solve on one DLPFC pair (4226 x 4384 spots) measured
  **393 s**, and at ~4800 spots with a maximum tear it exceeded a **900 s**
  watchdog. Budget for that; subsampling to ~2500 spots is 3.4x faster and
  lossless on this benchmark, ~1500 is 13x with minor loss.
- **Background jobs launched from the agent shell get reaped.** Launch detached
  (`Start-Process powershell -File ...`), give every run **its own log file**,
  and write a heartbeat. A run whose stdout goes to a killed watcher's pipe
  cannot produce evidence however long it runs.
- Long runs must be **resumable and incremental** - write the CSV row after every
  cell, cache expensive bases to disk, wrap each cell in try/except so one
  failure does not lose the grid.
- Keep `.ps1` files **pure ASCII**. PowerShell 5.1 breaks on non-ASCII in
  strings. The same caution applies to anything printed to a console: a fix that
  replaced a backtick with U+02CB would have raised `UnicodeEncodeError` on a
  cp1252 console.

---

## 9. Session rules

- **Never ask questions.** Make a reasonable decision and log the reasoning where
  the work lives.
- **Never stop for approval.**
- **If one line of attack is exhausted, enumerate an untried surface and
  continue.** The rounds that found nothing were the ones re-examining surfaces
  already hardened; the ones that found something were aimed at new ground. When
  a batch comes back clean, that is evidence you chose an old surface.
- **If blocked, log it precisely, work around it, and move on rather than
  stalling.** Say what is blocked, what you tried, and what would unblock it -
  the way the Xenium-ingest and browser-screenshot blockers are recorded in
  `COORDINATION.md`, with the exact missing prerequisite named.
- **Commit incrementally and keep logs current continuously**, not at the end. An
  auto-sync process commits WIP to the current branch of the shared tree; do not
  leave work uncommitted and assume it is yours.
- **Stay inside your scope guard.** Name the paths your effort owns before you
  start and touch nothing else. Never switch branches in the shared tree
  `C:\Users\karti\arca`; work in your own worktree. `main`, the website and
  `demo/` are not yours unless you were told they are.
- Prefer a mechanism that cannot silently go stale over one that is currently
  correct. A new round file that is not registered in `_load_extra_rounds`
  silently does not run; a new endpoint without a router-level dependency is
  unauthenticated by default. Make the safe case the default one.

---

## 10. On interruption

If the session is interrupted, resumed, compacted, or restarted:

1. **Re-read this file** and the logs for your effort - your
   `COORDINATION.md` section, your `FINDINGS_*.md`, your `STATUS.md` /
   `TEST_LOG.md` / `HARDENING_LOG.md`.
2. **Re-run the criterion check** from section 1. Do not infer status from the
   log; re-derive it.
3. **Continue from the first UNMET item, without waiting for instruction.**

Read the first-run ledger, not the regenerated report. `HYPOTHESIS_ROUNDS.md` is
regenerated on every run and so always looks clean; `ROUNDS_LEDGER.md` is written
by hand and never regenerated, and records what each round found the **first**
time it ran. A round that found three defects is indistinguishable from one that
found none once the defects are fixed.

---

## 11. Inter-agent communication

*The protocol text referenced in the commissioning instruction did not arrive
with it. This section is therefore reconstructed from the practice already
working in this repository - `COORDINATION.md`, `collab/COLLAB_LOG.md` and
`collab/API_CONTRACT.md` - and is authoritative until replaced. Reasoning logged
here rather than resolved by asking, per section 9.*

Several agents work this repository concurrently, each in its own worktree on its
own branch. They cannot see each other's working directories. Everything below
exists so that a fact discovered by one agent reaches the others.

### The channels

| channel | what goes in it |
|---|---|
| `COORDINATION.md` at the repository root | the shared cross-agent log. Every effort appends a dated section. This is where another agent looks first. |
| `<effort>/COORDINATION.md` | an effort's own detailed log, when it is large enough to swamp the root one (`research-agents/`, `collab/`, `benchmarks/`). The root log still gets the section header and the verdict. |
| `collab/COLLAB_LOG.md` | the two-party pattern, for agents that must agree on an interface. Append-only. |
| `<effort>/API_CONTRACT.md` | the interface itself, versioned. |
| `research/FINDINGS_<topic>.md` | the durable result of an experiment. One per experiment. |

### The rules

1. **Append-only. Newest entries at the bottom.** Never rewrite another agent's
   entry. A correction is a new entry that names what it corrects, or an in-place
   fix explicitly marked as corrected.
2. **Every entry carries an agent tag, a UTC date, and a one-line subject.**
   Use the branch name as the tag: `[tear-detect] 2026-07-18 - real-tissue damage
   detector`. Two-party logs use short tags (`[A]`, `[B]`) declared at the top of
   the file.
3. **Declare your scope guard in your first entry** - the exact paths your effort
   will touch - and stay inside it. Existing entries do this in one line:
   *"Scope guard: touched only `research/src/global_recon*.py` and
   `research/results/global_recon*`. Did NOT touch main/website/demo/cli/app or
   other branches."*
4. **Requests to another agent go under a visible `## Open requests` heading and
   move to `## Resolved` with an outcome when done.** A request buried in prose
   is not a request. The resolved table records what happened - *"Real bug,
   fixed in 1.2.0"*, *"Worse than reported, fixed"*, *"Documented as reserved,
   not emitted"* - so the exchange survives both sessions ending.
5. **Any interface change gets an entry and a version bump**, with the
   behavioural consequences spelled out for the other side, including the ones
   that will break their tests. The model to follow: *"a restart now advances
   `seq` by one event per previously-online participant plus the run/step
   cancellations. If any of your suites assert that the sequence number is
   unchanged across a restart, they will need updating."*
6. **Publish numbers with their artifact path**, so the other agent can
   recompute rather than quote. A number that travels as prose drifts - see
   section 5.
7. **Publish retractions and negative results with the same prominence as
   wins**, and say plainly that the earlier claim does not survive. The leak
   retraction is in the log in those words.
8. **Hand over blockers with their exact prerequisite**, not as "blocked".
9. **Never touch another agent's branch, worktree, or paths.** If you need
   something changed there, file it under their Open requests.
10. **Before starting, read the root `COORDINATION.md` and the sections for any
    effort your work touches.** Before stopping, make sure your section states
    what is done, what is open, and what the next session must read first.

### Making this file visible in a worktree

All worktrees share one object store, so no fetch is needed:

```
git checkout speed-opt -- CLAUDE.md      # from any worktree, no branch switch
```

A worktree that has not run this will not have the file on disk even after it is
committed and pushed.
