# Reflection (≤1 page)

**Which fault types were hardest to catch, and why?**

The hardest cases were subtle feature skew and structural lineage faults. A
small training-serving shift can overlap normal variation, so lowering one
static threshold would improve recall at the cost of false alarms. Lineage was
also less direct: the event payload does not contain the full expected graph.
I therefore learned a stable topology per job from prior runs and compared each
new graph with its modal signature. This catches missing upstreams and orphaned
outputs without coupling the detector to run IDs.

**What would you change about your cost/coverage tradeoff, if you had another pass?**

On practice, one relevant check per event cost 180 credits against a 220-credit
budget. The longer public stream cost 240; I accepted that modest overage because
blindly skipping expensive AI checks can lose more recall than the overage term
saves. With another pass I would use cheap historical signals to triage which
borderline AI events deserve a metered check. I would keep conservative static
thresholds and only lower them when a second signal or persistent trend agrees,
preserving a controlled false-positive rate while improving subtle-fault
recall. In the final pass, tightening staleness, embedding drift, and document
age gave the best marginal tradeoff; broad tightening across every metric
generated false alarms without comparable recall gains.
