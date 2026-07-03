"""Cost-aware defenses for all five Data Siege event types."""
from api import Verdict

# Multipliers below 1 tighten published three-sigma upper bounds. Keeping them
# centralized makes the recall/false-alarm tradeoff explicit and auditable.
SENSITIVITY = {
    "data_interval": 1.0,
    "null_rate": 1.0,
    "staleness": 0.67,
    "contract_freshness": 1.0,
    "lineage_runtime": 1.0,
    "feature_shift": 1.0,
    "embedding_shift": 0.66,
    "document_age": 0.71,
}


def register(ctx):
    ctx.on("data_batch", check_data_batch)
    ctx.on("contract_checkpoint", check_contract_checkpoint)
    ctx.on("lineage_run", check_lineage_run)
    ctx.on("feature_materialization", check_feature_materialization)
    ctx.on("embedding_batch", check_embedding_batch)


def check_data_batch(payload, ctx):
    profile = ctx.tools.batch_profile(payload["batch_id"])
    if "error" in profile:
        return Verdict(alert=False, confidence=0.0, reason=profile["error"], pillar="checks")

    baseline = ctx.baseline
    signals = []
    if _outside_margin(profile["row_count"], baseline["row_count_min"],
                       baseline["row_count_max"], SENSITIVITY["data_interval"]):
        signals.append("row_count")
    if profile["null_rate"].get("customer_id", 0.0) > SENSITIVITY["null_rate"] * baseline["null_rate_max"]:
        signals.append("customer_id_null_rate")
    if _outside_margin(profile["mean_amount"], baseline["mean_amount_min"],
                       baseline["mean_amount_max"], SENSITIVITY["data_interval"]):
        signals.append("mean_amount")
    if profile["staleness_min"] > SENSITIVITY["staleness"] * baseline["staleness_min_max"]:
        signals.append("staleness")
    return _verdict(signals, "checks")


def check_contract_checkpoint(payload, ctx):
    diff = ctx.tools.contract_diff(payload["contract_id"], payload["checkpoint_batch_id"])
    if "error" in diff:
        return Verdict(alert=False, confidence=0.0, reason=diff["error"], pillar="contracts")
    signals = list(diff.get("violations", []))
    if diff["freshness_delay_min"] > SENSITIVITY["contract_freshness"] * ctx.baseline["freshness_delay_max_min"]:
        signals.append("freshness_sla")
    return _verdict(signals, "contracts")


def check_lineage_run(payload, ctx):
    graph = ctx.tools.lineage_graph_slice(payload["run_id"])
    if "error" in graph:
        return Verdict(alert=False, confidence=0.0, reason=graph["error"], pillar="lineage")
    signals = []
    if graph["duration_ms"] > SENSITIVITY["lineage_runtime"] * ctx.baseline["lineage_duration_ms_max"]:
        signals.append("runtime")

    # The event describes datasets but does not publish the complete expected
    # graph. Learn the stable signature per job from the stream and reject
    # deviations from its modal (thus outlier-resistant) topology.
    signature = (tuple(sorted(graph["actual_upstream"])), graph["actual_downstream_count"])
    topology = ctx.state.setdefault("lineage_topology", {})
    counts = topology.setdefault(payload.get("job", "__default__"), {})
    if counts:
        # Prefer the most complete graph seen. This resists a faulty first run
        # (a mode initially has only one sample) and remains deterministic.
        expected = max(counts, key=lambda item: (len(item[0]), item[1], counts[item]))
        if signature[0] != expected[0]:
            signals.append("upstream_edges")
        if signature[1] != expected[1]:
            signals.append("downstream_count")
    counts[signature] = counts.get(signature, 0) + 1
    return _verdict(signals, "lineage")


def check_feature_materialization(payload, ctx):
    drift = ctx.tools.feature_drift(payload["feature_view"], payload["batch_id"])
    if "error" in drift:
        return Verdict(alert=False, confidence=0.0, reason=drift["error"], pillar="ai_infra")
    signals = []
    if drift["mean_shift_sigma"] > SENSITIVITY["feature_shift"] * ctx.baseline["feature_mean_shift_sigma_max"]:
        signals.append("training_serving_skew")
    return _verdict(signals, "ai_infra")


def check_embedding_batch(payload, ctx):
    drift = ctx.tools.embedding_drift(payload["corpus"], payload["chunk_batch_id"])
    if "error" in drift:
        return Verdict(alert=False, confidence=0.0, reason=drift["error"], pillar="ai_infra")
    signals = []
    if drift["centroid_shift"] > SENSITIVITY["embedding_shift"] * ctx.baseline["embedding_centroid_shift_max"]:
        signals.append("embedding_drift")
    if drift["avg_doc_age_days"] > SENSITIVITY["document_age"] * ctx.baseline["corpus_avg_doc_age_days_max"]:
        signals.append("corpus_staleness")
    return _verdict(signals, "ai_infra")


def _verdict(signals, pillar):
    """Build consistent, useful verdict metadata without extra RPC calls."""
    return Verdict(
        alert=bool(signals),
        confidence=1.0 if signals else 0.9,
        reason=", ".join(signals) if signals else "within calibrated bounds",
        pillar=pillar,
    )


def _outside_margin(value, published_low, published_high, fraction):
    """Tighten a published three-sigma interval toward its midpoint."""
    center = (published_low + published_high) / 2.0
    half_width = (published_high - published_low) * fraction / 2.0
    return value < center - half_width or value > center + half_width
