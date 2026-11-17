# Laya benchmark (synthetic labeled set)

Generated: 2026-11-17T10:30:44+00:00  
Hardware: AMD64 Family 23 Model 24 Stepping 1, AuthenticAMD · threads=4 · CPU only  
Small synthetic labeled set; results are indicative only, not production accuracy.

| Model | Task | Acc | Acc EN | Acc ID | Macro F1 | ECE | Conf ok / wrong | p50 ms | p95 ms | Peak RSS MB |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| rule_fallback | dq_category | 0.9 | 0.8 | 1.0 | 0.905 | — | 1.0 / 1.0 | — | — | — |
| rule_fallback | agent_route | 1.0 | 1.0 | 1.0 | 1.0 | — | 1.0 / None | — | — | — |
| multilingual | dq_category | 0.6 | 0.65 | 0.55 | 0.594 | 0.193 | 0.901 / 0.632 | 1161.9 | 1377.7 | 2225 |
| multilingual | agent_route | 0.688 | 0.812 | 0.562 | 0.663 | 0.197 | 0.788 / 0.678 | 979.6 | 1108.3 | 2225 |
| english | dq_category | 0.575 | 0.7 | 0.45 | 0.536 | 0.095 | 0.788 / 0.333 | 2708.2 | 2894.1 | 3018 |
| english | agent_route | 0.625 | 0.812 | 0.438 | 0.639 | 0.089 | 0.689 / 0.54 | 2680.4 | 2891.4 | 3018 |
| typed-decisions | dq_category | 0.6 | 0.75 | 0.45 | 0.562 | 0.318 | 0.334 / 0.206 | 3490.5 | 4208.1 | 3018 |
| typed-decisions | agent_route | 0.719 | 0.875 | 0.562 | 0.713 | 0.337 | 0.402 / 0.328 | 2900.5 | 3228.0 | 3018 |
