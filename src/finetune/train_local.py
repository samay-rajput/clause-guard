"""Local GPU fine-tune of the MuRIL conflict screener — the Colab notebook's
exact protocol, sized for a 4 GB laptop GPU.

Protocol (unchanged from notebooks/finetune_muril_colab.ipynb): seed 42,
effective train batch 16 (8 x grad-accum 2 here), lr 2e-5, 5 epochs, warmup
0.1, weight decay 0.01, fp16, best-of-epochs by dev macro-F1, early stopping
patience 2, test metrics to metrics_finetuned.json, fp16 export.

Run (in the CUDA venv):
  .venv_embed/Scripts/python src/finetune/train_local.py --out model/muril_gr_conflict_fp16_clean
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
SEED = 42
LABEL2ID = {"contradiction": 0, "consistent": 1, "neutral": 2}
ID2LABEL = {v: k for k, v in LABEL2ID.items()}
MODEL = "google/muril-base-cased"


def load(split):
    p = ROOT / "data" / f"pairs_{split}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="model/muril_gr_conflict_fp16_clean")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=2)
    a = ap.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    from datasets import Dataset
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              DataCollatorWithPadding, EarlyStoppingCallback,
                              Trainer, TrainingArguments)

    rows = {s: load(s) for s in ("train", "dev", "test")}
    print({s: len(r) for s, r in rows.items()}, flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL)

    def to_ds(rs):
        ds = Dataset.from_dict({
            "premise": [r["premise"] for r in rs],
            "hypothesis": [r["hypothesis"] for r in rs],
            "label": [LABEL2ID[r["label"]] for r in rs]})
        return ds.map(lambda b: tok(b["premise"], b["hypothesis"],
                                    truncation=True, max_length=256),
                      batched=True, remove_columns=["premise", "hypothesis"])

    dtrain, ddev, dtest = (to_ds(rows[s]) for s in ("train", "dev", "test"))
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL, num_labels=3, id2label=ID2LABEL, label2id=LABEL2ID)

    def compute_metrics(p):
        preds = p.predictions.argmax(-1)
        return {"macro_f1": f1_score(p.label_ids, preds, average="macro"),
                "accuracy": accuracy_score(p.label_ids, preds)}

    args = TrainingArguments(
        output_dir=str(ROOT / "data" / "train_out"), seed=SEED,
        per_device_train_batch_size=a.batch,
        gradient_accumulation_steps=a.accum,
        per_device_eval_batch_size=32,
        learning_rate=2e-5, num_train_epochs=5, warmup_ratio=0.1,
        weight_decay=0.01, fp16=torch.cuda.is_available(),
        eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True, metric_for_best_model="macro_f1",
        save_total_limit=1, logging_steps=25, report_to="none")
    trainer = Trainer(model=model, args=args, train_dataset=dtrain,
                      eval_dataset=ddev, data_collator=DataCollatorWithPadding(tok),
                      compute_metrics=compute_metrics,
                      callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    trainer.train()

    pred = trainer.predict(dtest)
    yh = pred.predictions.argmax(-1)
    y = pred.label_ids
    import sklearn
    import transformers
    metrics = {
        "macro_f1": f1_score(y, yh, average="macro"),
        "accuracy": accuracy_score(y, yh),
        "report": classification_report(y, yh, target_names=list(LABEL2ID),
                                        output_dict=True, zero_division=0),
        "seed": SEED, "model": MODEL,
        "trained_on": "clean mahGRs corpus pairs (gemini-flash-lite teacher, "
                      "mixed-language hypotheses, + mined real pairs)",
        "effective_batch": a.batch * a.accum,
        "versions": {"transformers": transformers.__version__,
                     "sklearn": sklearn.__version__},
    }
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    model.half().save_pretrained(str(out))
    tok.save_pretrained(str(out))
    (out / "metrics_finetuned.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: round(metrics[k], 4) for k in ("macro_f1", "accuracy")}),
          flush=True)
    print(f"saved -> {out}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
