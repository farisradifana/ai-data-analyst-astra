# 24 — Laya Model Selection

| Checkpoint | HF repo / subfolder | Backbone (model card) | Params | Pinned revision |
|---|---|---|---|---|
| multilingual (**selected**) | `convaiinnovations/laya` / `multilingual` | mmBERT-base | ~322M | `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67` |
| english | `convaiinnovations/laya` (root) | ModernBERT-large | ~421M | `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` |
| typed-decisions | `convaiinnovations/laya` / `typed-decisions` | ModernBERT-large | ~421M | `1a793eb568e6718f15941d08f85432581df534e3` |

Package `laya==0.4.35`, revisions as listed by `laya.PINNED_REVISIONS`.

Selection evidence and limits: [27-laya-evaluation.md](27-laya-evaluation.md).
Configure with `LAYA_CHECKPOINT` (default `multilingual`).

Multilingual was not assumed best. It was benchmarked against the other two. It tied or won on
Indonesian, was 2.5–3× faster on this CPU and loads in 35 s. typed-decisions had the best
English routing accuracy (0.88) but its confidences are too low to gate on.
