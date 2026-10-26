# Evidence index

Only current evidence is kept in this clean branch.

| Claim | Evidence |
|---|---|
| 2-hour real-vLLM gateway soak | [`soak-c4-7200s-telemetry.json`](soak-c4-7200s-telemetry.json) |
| 10-minute real-vLLM gateway soak | [`soak-c4-600s-metrics-final.json`](soak-c4-600s-metrics-final.json) |
| Direct vLLM c=1 | [`int4-r3-c1.json`](int4-r3-c1.json) |
| Direct vLLM c=4 | [`int4-r3-c4.json`](int4-r3-c4.json) |
| Final-image Kubernetes smoke | [`k8s-smoke.json`](k8s-smoke.json) |
| HPA + TLS demo | [`k8s-hpa-tls.json`](k8s-hpa-tls.json) |

Quality evidence lives in [`../eval/`](../eval/).
