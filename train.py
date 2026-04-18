"""
Standalone training script.
Run: python train.py
"""
import logging
import json
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from dotenv import load_dotenv
load_dotenv()

from src.storage.database import init_db
from src.model.trainer import train

if __name__ == "__main__":
    init_db()
    print("Starting model training...")
    metrics = train()
    print("\n=== Training complete ===")
    print(f"Best model  : {metrics['best_model']}")
    print(f"Samples     : {metrics['n_samples']}")
    print(f"Classes     : {metrics['n_classes']} → {metrics['classes']}")
    print("\nCross-validation results:")
    for name, cv in metrics["cv_results"].items():
        print(f"  {name:<22} acc={cv['accuracy_mean']:.3f}±{cv['accuracy_std']:.3f}  "
              f"f1_w={cv['f1_weighted_mean']:.3f}±{cv['f1_weighted_std']:.3f}")
    print(f"\nModel saved to data/model.joblib")
    print(f"Metrics saved to data/model_metrics.json")
