"""Train and evaluate the AMALYN feedback-status classifier."""

import csv
import glob
import json
import os

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from ml_model import (
    AmalynDetector,
    FEATURE_COUNT,
    FEATURE_SCALE,
    LABEL_MAP,
    LABEL_NAMES,
    normalize_magnitudes,
)


DATA_DIR = os.path.join(os.path.dirname(__file__), "ml_data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "ml_models")
MODEL_PATH = os.path.join(MODEL_DIR, "amalyn_detector.pth")
CONFIG_PATH = os.path.join(MODEL_DIR, "model_config.json")


class AudioDataset(Dataset):
    def __init__(self, features, labels):
        self.features = torch.as_tensor(features, dtype=torch.float32)
        self.labels = torch.as_tensor(labels, dtype=torch.long)

    def __len__(self):
        return len(self.features)

    def __getitem__(self, index):
        return self.features[index], self.labels[index]


def load_all_data():
    features, labels = [], []
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    if not csv_files:
        print("No training data found. Run ml_collector.py first.")
        return None, None

    legacy_rows = 0
    for path in csv_files:
        print(f"Loading: {os.path.basename(path)}")
        with open(path, newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                if row.get("feature_scale") != FEATURE_SCALE:
                    legacy_rows += 1
                    continue
                label = row.get("label")
                if label not in LABEL_MAP:
                    continue
                try:
                    magnitudes = [float(row[f"bin_{index}"]) for index in range(FEATURE_COUNT)]
                except (KeyError, TypeError, ValueError):
                    continue
                features.append(normalize_magnitudes(magnitudes))
                labels.append(LABEL_MAP[label])

    if not features:
        if legacy_rows:
            print("Only legacy-scale data was found. Collect new dBFS-v2 frames before training.")
        else:
            print("No valid labelled frames were found.")
        return None, None

    distribution = {name: labels.count(index) for name, index in LABEL_MAP.items()}
    print(f"\nTotal samples loaded: {len(features)}")
    print(f"Distribution: {distribution}")
    return np.asarray(features), np.asarray(labels)


def train(epochs=50, seed=42):
    print("\n" + "=" * 50)
    print("   AMALYN ML Trainer")
    print("=" * 50)
    features, labels = load_all_data()
    if features is None or len(features) < 5:
        print("At least five valid labelled frames are required to train a model.")
        return None

    test_size = max(1, round(len(features) * 0.2))
    indices = np.random.default_rng(seed).permutation(len(features))
    test_indices, train_indices = indices[:test_size], indices[test_size:]
    train_data = AudioDataset(features[train_indices], labels[train_indices])
    test_data = AudioDataset(features[test_indices], labels[test_indices])
    train_loader = DataLoader(train_data, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_data, batch_size=64)

    torch.manual_seed(seed)
    model = AmalynDetector()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = torch.nn.CrossEntropyLoss()
    best_accuracy = -1.0
    print(f"\nTraining on {len(train_data)} samples; validating on {len(test_data)} samples\n")

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for feature_batch, label_batch in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(feature_batch), label_batch)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        model.eval()
        correct = total = 0
        with torch.inference_mode():
            for feature_batch, label_batch in test_loader:
                predicted = torch.argmax(model(feature_batch), dim=1)
                correct += (predicted == label_batch).sum().item()
                total += len(label_batch)
        accuracy = correct / total * 100
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            os.makedirs(MODEL_DIR, exist_ok=True)
            torch.save(model.state_dict(), MODEL_PATH)
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"Epoch {epoch + 1:3d}/{epochs} | Loss: {total_loss / len(train_loader):.4f} | Accuracy: {accuracy:.1f}%")

    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(
            {
                "input_size": FEATURE_COUNT,
                "feature_scale": FEATURE_SCALE,
                "classes": LABEL_NAMES,
                "accuracy": best_accuracy,
                "seed": seed,
            },
            file,
            indent=2,
        )
    print(f"\nBest accuracy: {best_accuracy:.1f}%")
    print(f"Model saved to {MODEL_PATH}")
    return best_accuracy


if __name__ == "__main__":
    train()
