# ml_trainer.py — AMALYN ML Model Trainer
# Run this after collecting data to train the anomaly detector

import numpy as np
import os
import glob
import json
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

DATA_DIR = os.path.join(os.path.dirname(__file__), 'ml_data')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'ml_models')
os.makedirs(MODEL_DIR, exist_ok=True)

LABEL_MAP = {"CLEAN": 0, "WARNING": 1, "CRITICAL": 2}
LABEL_NAMES = {0: "CLEAN", 1: "WARNING", 2: "CRITICAL"}


class AudioDataset(Dataset):
    def __init__(self, features, labels):
        self.X = torch.FloatTensor(features)
        self.y = torch.LongTensor(labels)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


class AmalynDetector(nn.Module):
    """
    AMALYN Neural Network — Audio Anomaly Detector
    Input: 257 frequency magnitude bins
    Output: 3 classes (CLEAN, WARNING, CRITICAL)
    """
    def __init__(self):
        super(AmalynDetector, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(257, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, 3)
        )

    def forward(self, x):
        return self.network(x)


def load_all_data():
    csv_files = glob.glob(os.path.join(DATA_DIR, '*.csv'))
    if not csv_files:
        print("No training data found. Run ml_collector.py first.")
        return None, None

    features = []
    labels = []

    for f in csv_files:
        print(f"Loading: {os.path.basename(f)}")
        with open(f, 'r') as file:
            lines = file.readlines()
            for line in lines[1:]:
                parts = line.strip().split(',')
                if len(parts) < 258:
                    continue
                label = parts[0]
                if label not in LABEL_MAP:
                    continue
                mags = [float(x) for x in parts[1:258]]
                # Normalize to 0-1 range
                mags = [(m + 80) / 80 for m in mags]
                features.append(mags)
                labels.append(LABEL_MAP[label])

    print(f"\nTotal samples loaded: {len(features)}")
    counts = {name: labels.count(idx) for name, idx in LABEL_MAP.items()}
    print(f"Distribution: {counts}")
    return np.array(features), np.array(labels)


def train():
    print("\n" + "="*50)
    print("   AMALYN ML Trainer")
    print("="*50)

    features, labels = load_all_data()
    if features is None:
        return

    # Split 80/20 train/test
    split = int(len(features) * 0.8)
    idx = np.random.permutation(len(features))
    train_idx, test_idx = idx[:split], idx[split:]

    train_data = AudioDataset(features[train_idx], labels[train_idx])
    test_data = AudioDataset(features[test_idx], labels[test_idx])

    train_loader = DataLoader(train_data, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_data, batch_size=64)

    model = AmalynDetector()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()

    print(f"\nTraining on {len(train_data)} samples...")
    print(f"Testing on {len(test_data)} samples\n")

    best_accuracy = 0
    epochs = 50

    for epoch in range(epochs):
        model.train()
        total_loss = 0
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            output = model(X_batch)
            loss = criterion(output, y_batch)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        # Evaluate
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for X_batch, y_batch in test_loader:
                output = model(X_batch)
                predicted = torch.argmax(output, dim=1)
                correct += (predicted == y_batch).sum().item()
                total += len(y_batch)

        accuracy = correct / total * 100

        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1:3d}/{epochs} | Loss: {total_loss/len(train_loader):.4f} | Accuracy: {accuracy:.1f}%")

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            torch.save(model.state_dict(), os.path.join(MODEL_DIR, 'amalyn_detector.pth'))

    print(f"\nBest accuracy: {best_accuracy:.1f}%")
    print(f"Model saved to ml_models/amalyn_detector.pth")

    # Save model config
    config = {"input_size": 257, "classes": LABEL_NAMES, "accuracy": best_accuracy}
    with open(os.path.join(MODEL_DIR, 'model_config.json'), 'w') as f:
        json.dump(config, f, indent=2)

    print("Training complete.")


if __name__ == "__main__":
    train()