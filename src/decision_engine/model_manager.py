"""Loads the local Laya Router once and keeps it resident.

- CPU only, one checkpoint resident at a time (machine has ~14 GB RAM, little free).
- vega lane OFF: only the three base checkpoints, no extra reader model.
- Checkpoint revisions are pinned by the laya package (laya.PINNED_REVISIONS).
- Weights come from the local Hugging Face cache after the first download. Set
  HF_HUB_OFFLINE=1 to forbid any network access at inference time.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger("decision_engine.model_manager")

CHECKPOINTS = ("multilingual", "english", "typed-decisions")
DEFAULT_CHECKPOINT = os.getenv("LAYA_CHECKPOINT", "multilingual")


class ModelManager:
    def __init__(self, checkpoint: str = DEFAULT_CHECKPOINT, threads: int | None = None) -> None:
        if checkpoint not in CHECKPOINTS:
            raise ValueError(f"unknown checkpoint {checkpoint!r}; expected one of {CHECKPOINTS}")
        self.checkpoint = checkpoint
        self._threads = threads or int(os.getenv("LAYA_THREADS", "4"))
        self._router: Any = None
        self._lock = threading.Lock()

    def router(self) -> Any:
        with self._lock:
            if self._router is None:
                os.environ.setdefault("USE_TF", "0")
                import torch
                from laya import Router

                torch.set_num_threads(self._threads)
                log.info("loading laya router checkpoint=%s threads=%d", self.checkpoint, self._threads)
                self._router = Router(max_loaded=1, vega=False, device="cpu", default=self.checkpoint)
            return self._router

    def predict(self, body: str, questions: dict[str, Any]) -> dict[str, Any]:
        return self.router().predict({"body": body}, questions, model=self.checkpoint)

    def info(self) -> dict[str, Any]:
        import laya

        repo, sub = laya.DEFAULT_MODELS[self.checkpoint]
        pinned_key = repo if sub is None else f"{repo}-{sub}"
        return {
            "package": "laya",
            "package_version": getattr(laya, "__version__", None),
            "checkpoint": self.checkpoint,
            "repo": repo,
            "subfolder": sub,
            "pinned_revision": laya.PINNED_REVISIONS.get(pinned_key),
            "device": "cpu",
            "vega_lane": False,
            "hosted_api": False,
        }
