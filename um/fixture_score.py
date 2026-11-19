"""Score predicted conflict/duplicate pairs against the hand-labelled fixtures.

A predicted pair counts as a true positive only when the same unordered pair {a, b} is labelled
and the predicted label matches the gold label.
"""
from __future__ import annotations

import json
from pathlib import Path


def _key(row: dict) -> frozenset:
    return frozenset((row["a"], row["b"]))


def score_pairs(findings_path: Path, labels_path: Path) -> dict:
    gold = {}
    for line in Path(labels_path).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            gold[_key(row)] = row["label"]
    predicted = {_key(p): p["label"] for p in json.loads(Path(findings_path).read_text())["pairs"]}
    tp = sum(1 for k, label in predicted.items() if gold.get(k) == label)
    fp = len(predicted) - tp
    fn = sum(1 for k, label in gold.items() if predicted.get(k) != label)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}
