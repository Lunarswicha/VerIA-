#!/usr/bin/env python3
"""
VeriaChain — Script d'évaluation reproductible
==============================================
Protocole décrit au paragraphe 10.3 du mémoire : évaluation du pipeline de
détection sur 533 images du dataset public Hemg/AI-Generated-vs-Real-Images-Datasets,
pour trois configurations (huggingface seul, frequency seul, ensemble 65/35).

Usage :
    pip install -r requirements.txt datasets
    python evaluate.py                # 533 images, seed fixe
    python evaluate.py --limit 100    # essai rapide

Sorties :
    eval_results.json  : prédictions individuelles reproductibles
    eval_report.txt    : métriques par configuration (accuracy, précision, rappel, F1)
"""
from __future__ import annotations

import argparse
import io
import json
import random
from pathlib import Path

import numpy as np

from config import Config
from detection.detector import VeriaDetector

SEED = 42
N_IMAGES = 533
THRESHOLD = 0.5  # score >= 0.5 -> classé "IA"


def load_dataset(limit: int):
    from datasets import load_dataset
    ds = load_dataset("Hemg/AI-Generated-vs-Real-Images-Datasets", split="train")
    idx = list(range(len(ds)))
    random.Random(SEED).shuffle(idx)
    return ds, idx[:limit]


def to_bytes(pil_img) -> bytes:
    buf = io.BytesIO()
    pil_img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def metrics(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    acc = (tp + tn) / max(len(y_true), 1)
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    return {"n": len(y_true), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "accuracy": round(acc, 4), "precision": round(prec, 4),
            "recall": round(rec, 4), "f1": round(f1, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=N_IMAGES)
    args = ap.parse_args()

    ds, indices = load_dataset(args.limit)
    label_names = ds.features["label"].names  # ex. ['AiArtData', 'RealArt'] selon le dataset
    print(f"Labels du dataset : {label_names}")
    # convention : 1 = généré par IA, 0 = authentique
    ai_label_ids = [i for i, n in enumerate(label_names) if "ai" in n.lower()]

    results = []
    per_config = {"huggingface": ([], []), "frequency": ([], []), "ensemble": ([], [])}

    for mode in per_config:
        cfg = Config()
        cfg.DETECTION_MODE = mode
        det = VeriaDetector(cfg)
        y_true, y_pred = per_config[mode]
        for k, i in enumerate(indices, 1):
            row = ds[i]
            truth = 1 if row["label"] in ai_label_ids else 0
            res = det.analyze_image(to_bytes(row["image"]), f"img_{i}.png")
            pred = 1 if res.ai_probability >= THRESHOLD else 0
            y_true.append(truth)
            y_pred.append(pred)
            results.append({"mode": mode, "index": i, "truth": truth,
                            "score": res.ai_probability, "pred": pred})
            if k % 50 == 0:
                print(f"  [{mode}] {k}/{len(indices)}")

    report = {m: metrics(*per_config[m]) for m in per_config}
    Path("eval_results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    lines = [f"Évaluation VeriaDetect — {len(indices)} images, seed {SEED}, seuil {THRESHOLD}", ""]
    for m, r in report.items():
        lines.append(f"{m:12s} acc={r['accuracy']:.3f} prec={r['precision']:.3f} "
                     f"rappel={r['recall']:.3f} F1={r['f1']:.3f} "
                     f"(tp={r['tp']} tn={r['tn']} fp={r['fp']} fn={r['fn']})")
    Path("eval_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
