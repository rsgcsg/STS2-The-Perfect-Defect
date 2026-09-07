# Artifact foundation bootstrap

This is a source-generation receipt, not final CI or readiness evidence.

```json
{
  "schema": "stpd/bootstrap-source-evidence-v1",
  "input_head": "d0c204ebed1f7940109c1c0be2df988271934750",
  "existing_dependency_pins_preserved": true,
  "added_dependencies": [
    [
      "boto3",
      "1.43.89",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "botocore",
      "1.43.89",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "duckdb",
      "1.5.5",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "jmespath",
      "1.1.0",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "python-dateutil",
      "2.9.0.post0",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "s3transfer",
      "0.19.2",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "six",
      "1.17.0",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ],
    [
      "urllib3",
      "2.7.0",
      "{\"registry\": \"https://pypi.org/simple\"}"
    ]
  ],
  "uv_lock_sha256": "ee0a7b73c1666c3950f2b00e1bbc6bfb35db63970aadbdccfa1a5fb7ccfbf059",
  "focused_checks_on_uncommitted_worktree": {
    "focused_ruff": 0,
    "focused_pytest": 0
  },
  "non_claims": [
    "latest-head full CI",
    "Windows",
    "real S3",
    "pre-Full-Run readiness"
  ]
}
```
