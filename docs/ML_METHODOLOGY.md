# Machine Learning Methodology

> Implementation: `backend/ml/` · Reproduce: `python -m ml.experiments.run_all`
> Companion: [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md),
> [`CRYPTOGRAPHY_DESIGN.md`](CRYPTOGRAPHY_DESIGN.md)

---

## 0. Read this first: what these results are

**Every number in this document is computed on synthetic data.** AssistMe has no
deployed users, so there is no observational corpus of elderly people receiving
remote assistance, and there will not be one until the system is in the field.

### What these experiments can establish

* That the modelling approach is **implemented correctly** — calibration,
  cost-sensitive thresholding, and off-policy estimation behave as the theory
  says on data whose ground truth is knowable by construction.
* That the learned policy **beats the rule baseline on contexts where the rule
  baseline is known to be wrong**, since the generator constructs those contexts
  deliberately and labels them.
* That the **safety envelope is never violated**, which is checked by
  enumeration rather than by sampling.
* That off-policy estimators **recover the true policy value**, which is only
  checkable when the truth is known — the reason for doing this on a simulator
  first.

### What they cannot establish

Any claim about real-world accuracy. The generative process in
`ml/datasets/generators.py` encodes beliefs about how risk arises; a model
evaluated on data drawn from those beliefs will confirm them. Reported
accuracies are properties of **this simulator**, not of the world.

Validating against real usage is the first item in future work, not a footnote.

### Reproducing

```bash
python -m ml.experiments.run_all            # full run, ~60 s
python -m ml.experiments.run_all --quick    # ~100 s, for CI
```

Everything derives from `GLOBAL_SEED = 20260901`. Seeds are derived *per
component* via BLAKE2b over a label, not shared: two components drawing from one
stream consume correlated draws, which silently couples the dataset generator to
the bandit's exploration and invalidates any regret measurement.

Results land in `ml/results/results.json`; the tables below are generated from
it, not transcribed.

---

## 1. The research question

ACSAF's premise is that assistance capability should adapt to context. The
inherited implementation adapted with a chain of `if` statements over two
signals:

```python
if context.is_flag_secure_active:
    return "high", reasons
if category in ("banking", "health", "password_manager", "payment"):
    return "high", reasons
```

Three limitations follow, and each maps to one of the four models built here:

| Limitation | Consequence | Addressed by |
|---|---|---|
| No probability, only a label | Cannot distinguish a marginal call from an obvious one, and cannot be tuned against the cost of being wrong | §3 Calibrated risk classifier |
| Rules fire on *category*, not on what is actually on screen | Over-restricts a bank app on its login splash; misses a card photographed into a chat | §3, §4 |
| No notion of what assistance actually *worked* | Takes the maximum permitted privilege always, which is not the same as helping | §4 Contextual bandit |
| No sense of sequence or of success | Suggests what was done before, never what comes next | §5 Recommender |
| Nothing detects a helper acting like a fraudster | Consent obtained by deception is still consent to the schema | §6 Anomaly detection |

---

## 2. The safety envelope: what ML is *not* allowed to do

This is the design decision the rest depends on.

A learned policy here decides what a third party may do on an elderly person's
phone. Machine learning is the right tool for **choosing well within** that
space, and the wrong tool for **defining its boundary**:

* A retrained model can regress in ways no test catches until it is live, and
  the failure mode is a stranger tapping inside someone's bank app.
* Features come from the client, so a compromised client can craft the context
  vector it wants. Rules keyed on OS-set signals (`FLAG_SECURE`, the
  accessibility capability) are correspondingly harder to talk out of.
* Consent is a legal and ethical property, not a statistical one. "The model
  estimated they probably would have agreed" is not consent.

So the model **never grants**. It proposes; the envelope decides what the
proposal may become:

```
ceiling(x) = highest-privilege mode the deterministic rules permit
action     = min(model_proposal, ceiling(x))     [by privilege rank]
```

The clamp is **one-directional** — the envelope can lower a proposal and never
raise one — so the worst a broken model can do is be unhelpful.

### Three independent enforcement points

| Layer | Where | Stops |
|---|---|---|
| Envelope | `ml/risk/safety.py` | The model proposing above the ceiling |
| Database | `ck_policy_decisions_high_risk_limits_mode` | Any writer, including raw SQL and a bad migration |
| Client | Consent gate on the helpee's device | Anything that got past both |

A single point of enforcement for a safety property is a single point of
failure.

### Audit result

`run_safety_audit` enumerates every mode — plus malformed inputs like `"tap "`,
`"administrator"`, and `"'; DROP TABLE sessions;--"` — against every generated
context. Not sampled: the property is absolute, so a single violation is a
failure.

| Metric | Result |
|---|---|
| Checks performed | **56,000** |
| Ceiling violations | **0** |
| Interactive modes granted at rule-assessed high risk | **0** |
| Unknown mode strings fail closed to `restricted` | ✅ |

---

## 3. Risk classification

### 3.1 Cost-sensitive decisions

Thresholding at `p > 0.5` implicitly asserts that failing to protect someone
costs the same as inconveniencing them. It does not. The Bayes-optimal threshold
under asymmetric cost is

```
p* = c_false_risky / (c_false_risky + c_false_safe)
```

With the project's declared **10:1** ratio, `p* = 0.091`: the system restricts
whenever there is more than about a 9% chance the context is sensitive.

The 10:1 ratio is a **judgement, not a measurement** — it says one missed
protection is as bad as ten unnecessary restrictions. It is stated as a named
constant (`ml/config.py`) precisely so it can be argued with. A hard-coded 0.5
encodes a 1:1 ratio nobody ever chose.

### 3.2 Calibration

The decision layer thresholds a probability, so the probability has to mean
something. Gradient-boosted trees are systematically over-confident at the
extremes, so both candidates are wrapped in isotonic regression fitted on
**out-of-fold** predictions (`CalibratedClassifierCV(cv=5)`).

Calibrating on training predictions is a classic silent error: the base model is
over-confident *and correct* in-sample, so the calibrator learns to leave it
alone and the reliability curve looks perfect on training data and is badly
wrong on new data.

Model selection is by **cross-validated Brier score**, not accuracy, because the
downstream decision is a thresholded probability and Brier is the proper scoring
rule for exactly that.

### 3.3 Abstention, derived rather than tuned

Where the two actions' expected costs are near-equal, the model's opinion is not
worth acting on and the deterministic rules should decide. The band is derived
from the cost model:

```
|p·(c_safe + c_risky) − c_risky| < abstain_cost_gap
```

An earlier version used a fixed ±0.04 in probability units, which spans a fifth
of the usable range below a 0.09 threshold and sent **58% of traffic** to the
fallback. The cost-derived band sends **2.7%**, and moves coherently if the cost
ratio changes instead of leaving a stale hand-tuned margin behind.

### 3.4 Results

Held-out set, 6,000 contexts, positive rate 0.26.

| Metric | Model | Baseline | Note |
|---|---:|---:|---|
| ROC-AUC | **0.811** | 0.500 | |
| PR-AUC | **0.704** | 0.251 | No-skill = positive rate |
| Brier score | **0.120** | 0.188 | Baseline predicts the base rate |
| **ECE** | **0.015** | — | Equal-frequency bins (§3.5) |
| Max calibration error | 0.044 | — | |
| Recall | **0.982** | — | At the cost-optimal threshold |
| Precision | 0.260 | — | Expected: the threshold is deliberately cautious |
| Accuracy | 0.29 | 0.75 majority, 0.86 Bayes | **See §3.6** |
| **Expected cost/decision** | **0.747** | **0.975** (rules) | **-23.4%** |
| Abstention rate | 0.026 | — | Handed to the rule engine |

**Selected model: logistic regression.** It beat gradient boosting on
cross-validated Brier score (0.1240 vs 0.1248) — a difference too small to call
meaningful, which is itself the finding. Where the simpler model matches, the
simpler model wins: on a safety path, coefficients a human can read are worth
real accuracy, and there is nothing here to trade away.

### 3.5 Why equal-frequency calibration bins

With a threshold near 0.09 the predicted-probability distribution is heavily
concentrated below 0.2. Equal-*width* bins would place nearly every sample in
the first bin, leaving the rest almost empty and the reported ECE dominated by
noise from a handful of points. Equal-frequency (quantile) bins put comparable
mass in each.

### 3.6 On the accuracy figure

Accuracy of 0.29 is **below** the 0.75 majority-class baseline, and that is the
intended behaviour, not a defect. At a 0.091 threshold the classifier flags
anything with a ≥9% chance of sensitivity, which produces many false positives
by construction. Under the declared cost ratio that is the *cheaper* error.

Accuracy is the wrong objective here and is reported only for familiarity,
always beside the majority baseline and the Bayes ceiling. **Expected cost is
the metric the system optimises**, and on it the model beats the rules by 23.4%.

### 3.7 The result that matters: where rules fail

The generator injects two populations the rule engine is known to get wrong:

* **`hidden_sensitive`** — sensitive content in a non-critical app (a bank card
  photographed into a chat). Rules under-protect, so **recall** is the metric.
* **`benign_critical`** — a critical-category app showing nothing sensitive (a
  banking app on its login splash). Rules over-restrict, so the **false positive
  rate** is the metric.

| Subgroup | n | Model recall | Rule recall |
|---|---:|---:|---:|
| `hidden_sensitive` | 371 | **0.981** | 0.733 |
| `benign_critical` | 111 | 1.000 | 1.000 |

**The headline finding:** on contexts carrying sensitive content that no app
category reveals, the learned model catches **98.1%** against the rule engine's
**73.3%**. That is the case ACSAF's adaptive premise exists to address, and the
one an aggregate metric would average away.

On `benign_critical` the model does not improve on the rules — both restrict
everything. That is an honest negative result: at a threshold this cautious the
model has no room to relax a restriction, and recovering utility there would
require a cost ratio the safety argument does not support.

---

## 4. Contextual bandit for mode selection

### 4.1 Why a bandit

Mode selection has **no ground-truth label**. Nobody can say what the correct
assistance mode for a past session was; there is only what happened when a mode
was chosen. That is bandit feedback: one action, one reward, no information
about the alternatives.

Framing it as supervised learning would require inventing labels, and the
invented label would be whatever the rule engine chose — teaching a model to
imitate the system it is meant to improve on.

### 4.2 A modelling correction worth recording

The first version of the reward model made higher privilege strictly better
whenever admissible. Under that reward the optimal policy is "take the
envelope's ceiling", which is exactly what the rule engine already does — so the
rule baseline achieved near-zero regret and there was nothing for a learner to
contribute. **That was an artefact of the reward model, not a finding about
rules.**

It was also wrong about the domain. Remote-controlling someone's phone when a
spoken instruction would have worked is not a better outcome: the person learns
nothing, and the assistive-technology literature is consistent that
over-assistance drives abandonment. Reward now peaks at a **context-dependent**
mode:

```
optimal(x) ≈ f(task_complexity, helpee_autonomy, gesture_capability)
```

Both latents are *partially* observable — complexity through app category,
autonomy through relationship history — so the right action is learnable from
features but not deducible from any fixed rule. That is precisely the regime
where a contextual policy earns its place.

### 4.3 Regret

6,000 rounds, 5 seeds, fresh policy per seed.

| Policy | Final regret | Tail rate | Optimal action % | Safety violations |
|---|---:|---:|---:|---:|
| **Thompson sampling** | **259** | 0.030 | 51.2% | **0** |
| LinUCB | 289 | 0.035 | 49.3% | 0 |
| ε-greedy | 365 | 0.059 | 43.6% | 0 |
| Random | 614 | 0.104 | 30.0% | 0 |
| **Rule ceiling (baseline)** | **729** | 0.121 | 35.0% | 0 |
| Least privilege | 1117 | 0.185 | 3.3% | 0 |

**Thompson sampling reduces cumulative regret by 64% against the rule
baseline, with zero safety violations across every policy and every round.**

Two secondary observations are worth as much as the headline:

* **The rule ceiling is worse than random.** Always taking the maximum permitted
  privilege over-helps, and over-helping costs real reward. This is the
  quantitative form of the argument in §4.2.
* **Zero safety violations is by construction, not by luck.** Inadmissible
  actions receive zero probability mass, so exploration bonuses cannot push the
  policy toward them — they are not in the argmax at all.

### 4.4 Off-policy evaluation

A candidate policy cannot be A/B tested here. The subjects are elderly people,
the actions grant a stranger control of their phone, and the harm from a bad
policy is not a lost conversion. Any policy change must be assessed **before** it
touches a session.

Three estimators, because they fail differently and agreement between them is
itself evidence:

| Policy | IPS | SNIPS | **DR** | True value | ESS |
|---|---:|---:|---:|---:|---:|
| Least Privilege | 0.698 | 0.704 | 0.705 | 0.708 | 8172 |
| Rule Ceiling | 0.819 | 0.756 | 0.762 | 0.773 | 718 |
| Linucb | 0.946 | 0.904 | 0.890 | 0.861 | 746 |
| Thompson | 0.948 | 0.899 | **0.888** | 0.863 | 1023 |

**DR is roughly 3× more accurate than IPS** (Thompson: 0.026 vs 0.086 absolute
error), exactly as theory predicts — it is consistent if *either* the reward
model or the propensities are right.

**On the ESS column.** Effective sample size is the first number to look at
before believing any off-policy result. Ten thousand logged decisions with an
ESS of 718 give an estimate with the precision of 718 samples. Quoting an
estimate without it hides that entirely, and the low ESS for `rule_ceiling` and
`linucb` is why IPS is visibly wrong for those rows.

This is what the `propensity` column of `ml_decision_log` is for: it is knowable
only at decision time and can never be recovered afterwards.

---

## 5. Next-action recommendation

### 5.1 What it replaces

The inherited engine counted `(user, app, action)` signatures, suggested
anything seen twice, and reported "confidence" as `count / 4`. Three defects,
each fixed:

* **No notion of success.** An action retried five times *because it kept
  failing* outranked one that worked immediately. Exposure and reward are now
  separate, ranked by a Beta-Bernoulli posterior (Jeffreys prior).
* **No recency.** A monotone counter means a habit abandoned a year ago outranks
  one formed last week, forever. Evidence now decays with a six-week half-life,
  maintained in O(1) per observation.
* **`count / 4` is not a probability.** It saturates at four observations and is
  calibrated against nothing. The posterior mean is well-defined at zero
  observations and shrinks toward the prior when evidence is thin — which is
  exactly the conservatism a cold-start elderly user needs.

### 5.2 Evaluation design

**Split by session, chronologically, plus a held-out user cohort.** A random
split over transitions would put a session's step 3 in training and step 4 in
test, letting the model see the future of a sequence it is asked to predict.

A purely chronological split is also insufficient: every test user then already
has a personal history, and the "cold start" column measures nothing. 15% of
users are withheld from training entirely, so the cold-start figures describe
real strangers — the population an assistance product acquires continuously, and
for whom the first session matters most.

### 5.3 Results

| Model | Recall@1 | Recall@3 | MRR | Cold-start R@3 |
|---|---:|---:|---:|---:|
| **Markov + backoff** | **0.560** | **0.975** | **0.748** | **0.977** |
| Neural MLP | 0.543 | 0.967 | 0.736 | 0.959 |
| Popularity | 0.297 | 0.698 | 0.537 | 0.697 |
| Random | — | 0.500 | — | — |

**The Markov chain is shipped, and the neural model is not.**

The neural model does not beat it on any metric — Recall@3, MRR, and cold-start
recall all favour the chain, by small margins. That is a mildly surprising
result worth stating plainly rather than burying: an MLP with a windowed history
encoding has strictly more representational capacity than a first-order chain,
so on data with genuine longer-range structure it should win. It does not here,
which suggests the generated sequences carry little beyond first-order
dependence — a property of the simulator that real sessions may well not share.
The comparison should be re-run on field data before concluding anything
general.

Meanwhile the chain wins on every other axis: it updates online in O(1), needs
no training pipeline, adds no dependency to the request path, and can explain
itself to a helper ("after drawing, 42% of your sessions go to remote control").
Reporting a negative result for the more sophisticated model is more useful than
shipping it because it is more sophisticated.

**Cold start holds at 0.977** because the Jelinek–Mercer backoff hands over
continuously from personal to population to popularity as evidence accumulates,
rather than switching at a threshold. A user with no history is served entirely
by the population model, and never sees the discontinuity a hard cutoff would
produce on their fifth session.

---

## 6. Security anomaly detection

### 6.1 The threat

Every other control assumes the helper is who the helpee thinks they are.
Pairing requires consent; escalation requires an explicit risk screen. None of
that helps when the helpee has been persuaded — by a call from "the bank" — to
approve a stranger and then approve control. **Consent obtained by deception is
still consent as far as the schema is concerned.**

### 6.2 Why unsupervised

There are no labelled fraud cases and cannot be at this stage. Even in
production, confirmed labels arrive rarely, long after the fact, and are biased
toward cases someone noticed — a supervised model trained on them learns to
detect the fraud that has already been caught.

An ensemble of **Isolation Forest** (sparse-region isolation) and **robust
Mahalanobis distance** (correlation violation), combined by rank averaging since
the two scores live on incomparable scales. Mahalanobis catches the case
Isolation Forest is weakest on: a point whose every individual feature is
unremarkable but whose *combination* is not — a brand-new account running a
four-hour session at 3 a.m.

### 6.3 A correction: the first version was too easy

The first generator produced attacks that were trivially separable, and the
detector reported **ROC-AUC = 1.000**. That number said the simulator was easy,
not that the detector was good.

Real attackers adapt: someone caught once spaces their pairing requests out,
waits before asking for control, operates during the day. 55% of injected
attacks are now blended toward the normal profile with a per-case weight, so the
interesting cases partially resemble legitimate use — which is where a detector
has to earn its keep.

### 6.4 Results

Base rate 5.1%, deliberately low: a detector evaluated on balanced classes
reports a precision it will never achieve against real traffic.

| Metric | Result | Baseline |
|---|---:|---:|
| ROC-AUC | 0.987 | 0.500 |
| PR-AUC | **0.936** | 0.051 |
| Precision | 0.894 | — |
| Recall | 0.872 | — |
| Alert rate | 4.9% | — |

Per-scenario recall, which an aggregate would hide:

| Scenario | Recall |
|---|---:|
| Pairing spam | 0.991 |
| Escalation probing | 0.802 |
| **Coercion** | **0.824** |

Coercion is the scenario with the worst outcome for the person, so a detector
that missed it would be unfit whatever its average said. Precision@k is reported
across review-queue capacities (25/50/100/200) because that is the number that
determines whether staffing a queue is worthwhile.

### 6.5 What this is not

**An anomaly score is not evidence of fraud.** Nothing here blocks a session or
accuses anyone. The operating point favours precision because wrongly telling
someone their daughter looks like a fraudster is a real harm, and every alert
carries its top contributing features so a human can judge it.

---

## 7. Production integration

### 7.1 Degradation

Every failure path ends at the deterministic rule engine, and the response
records `decision_source = "rules"`:

| Condition | Behaviour |
|---|---|
| `ML_ENABLED=false` | Rules |
| Artefact missing or unloadable | Rules; logged once, not retried per request |
| Inference raises | Rules; model marked unavailable |
| Model abstains | Rules; abstention recorded so the rate is measurable in production |
| Feature extraction fails | Rules |
| No context reported | Rules, capped at `voice` |

The system's floor is exactly its previous behaviour. That is what makes
shipping a model on this path defensible: the worst case is the old system, not
an unpredictable one.

### 7.2 A bug this design surfaced

`InferenceService._propose_mode` originally selected via
`ACTIONS[argmax(policy.probabilities(...))]`. For Thompson sampling that is not
Thompson sampling — it is greedy exploitation of the posterior predictive, which
removes exploration entirely **and** makes every logged decision useless for
off-policy evaluation, because a deterministic policy assigns propensity 1 to
one action and 0 to the rest.

It now calls `policy.select(...)`, which draws once from the posterior. The
propensity is recorded only when the envelope did *not* clamp: if it did, the
action taken is not the one the policy sampled, and attaching the policy's
propensity to it would corrupt every importance weight computed from that row.

### 7.3 Model cards

Every artefact carries a card written *by the training run*, so it cannot drift
from what it describes. `limitations` and `ethical_considerations` are required
fields, not optional: a model that decides what a stranger may do on an elderly
person's phone should not be deployable without someone having written down what
it cannot do.

---

## 8. Threats to validity

**Construct validity.** The generator encodes the author's beliefs about how
risk arises, and the model confirms them. The 10:1 cost ratio is asserted, not
elicited from users. The reward model's shape — that over-assistance is costly —
is grounded in the assistive-technology literature but not measured here.

**Internal validity.** Mitigated by fixed per-component seeds, out-of-fold
calibration, chronological session splits with held-out users, fresh policies
per regret seed, and estimators checked against known ground truth. The
remaining risk is that the feature extractor and the generator share
assumptions — both are authored here.

**External validity.** The weakest axis, and unfixable without deployment. Real
app-category distributions, real FLAG_SECURE usage, real helper behaviour, and
the real reward signal are all unknown. Nothing here should be read as a
prediction about field performance.

**Statistical validity.** Regret is averaged over 5 seeds with standard errors.
Off-policy estimates carry standard errors and effective sample sizes. The
single-run comparisons in §3 and §5 do **not** carry confidence intervals across
repeated data draws — repeated-draw intervals are future work, and differences
of a few points there should not be read as significant. In particular the
Markov chain's margin over the neural model in §5 (0.007 Recall@3) is well
inside that band: the defensible reading is "no better", not "worse".

---

## 9. Future work, in priority order

1. **Field validation.** Everything above is conditional on a simulator.
2. **Instrument the real reward signal** — task resolved, control revoked,
   session abandoned — before the bandit's reward means anything.
3. **Elicit the cost ratio** from helpees and helpers instead of asserting 10:1.
4. **Fairness audit across device and platform strata.** The current evaluation
   has no subgroup analysis by platform or device age, and an accessibility
   product cannot claim to be finished without one.
5. **Drift monitoring.** Calibration will decay as the app population changes;
   `ml_decision_log` has the data to detect it, but nothing consumes it yet.
6. **Repeated-draw confidence intervals** for the risk and recommender
   comparisons.
7. **Move key material to an HSM** so a live process compromise stops being
   sufficient to decrypt (see `CRYPTOGRAPHY_DESIGN.md` §1).
