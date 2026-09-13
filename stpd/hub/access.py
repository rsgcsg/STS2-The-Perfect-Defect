"""Hub v1 shared developer result visibility, independent of server and workbench.

Raw/source/Dataset artifacts stay admin-only. Download policy does not admit training.
"""

RESULT_KINDS = frozenset(
    {
        "model",
        "checkpoint",
        "run_result",
        "offline_evaluation",
        "live_evaluation",
        "performance",
        "analysis",
    }
)
