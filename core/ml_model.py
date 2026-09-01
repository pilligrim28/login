"""
ML-модель предсказания успешности регистрации.

Бинарная логистическая регрессия (online-SGD, L2) без внешних зависимостей.
Обучается на истории попыток и умеет ранжировать комбинации параметров
(сервис, страна, оператор, прокси, час суток) — «находить возможности».
Веса сохраняются в JSON, чтобы модель дообучалась между запусками.
"""

import hashlib
import json
import math
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def _stable_bucket(value: str, buckets: int = 16) -> Optional[str]:
    if not value:
        return None
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    return f"p{int(digest, 16) % buckets}"


def _hour_bucket(hour: Optional[int]) -> Optional[str]:
    if hour is None:
        return None
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "day"
    return "evening"


def _parse_hour(created_at: Optional[str]) -> Optional[int]:
    if not created_at:
        return None
    try:
        s = str(created_at).strip().replace("T", " ")[:19]
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").hour
    except (ValueError, TypeError):
        return None


def record_to_features(attempt: Dict) -> Dict[str, str]:
    """Запись попытки (строка БД) -> словарь признаков."""
    proxy = attempt.get("proxy") or ""
    return {
        "service": attempt.get("service") or None,
        "country": attempt.get("country") or None,
        "operator": attempt.get("operator") or None,
        "proxy_bucket": _stable_bucket(proxy),
        "hour_bucket": _hour_bucket(_parse_hour(attempt.get("created_at"))),
    }


class LogisticRegression:
    """Бинарная логистическая регрессия с L2 и online-SGD."""

    FIELDS = ("service", "country", "operator", "proxy_bucket", "hour_bucket")

    def __init__(self, path="ml_model.json", learning_rate=0.15, l2=0.01):
        self.path = path
        self.learning_rate = learning_rate
        self.l2 = l2
        self.bias = 0.0
        self.weights: Dict[int, float] = {}
        self.vocab: Dict[str, int] = {}
        self.n_samples = 0
        self.load()

    def _index(self, field: str, value: str) -> int:
        key = f"{field}={value}"
        if key not in self.vocab:
            self.vocab[key] = len(self.vocab)
        return self.vocab[key]

    def _vectorize(self, record: Dict[str, str]) -> Dict[int, float]:
        feats: Dict[int, float] = {}
        for field in self.FIELDS:
            val = record.get(field)
            if val in (None, ""):
                continue
            feats[self._index(field, str(val))] = 1.0
        return feats

    @staticmethod
    def _sigmoid(z: float) -> float:
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        e = math.exp(z)
        return e / (1.0 + e)

    def _score(self, feats: Dict[int, float]) -> float:
        total = self.bias
        for idx, val in feats.items():
            total += self.weights.get(idx, 0.0) * val
        return total

    def predict_proba(self, record: Dict[str, str]) -> float:
        return self._sigmoid(self._score(self._vectorize(record)))

    def predict(self, record: Dict[str, str]) -> int:
        return 1 if self.predict_proba(record) >= 0.5 else 0

    def fit_one(self, record: Dict[str, str], y: int):
        feats = self._vectorize(record)
        proba = self._sigmoid(self._score(feats))
        err = proba - float(y)
        self.bias -= self.learning_rate * err
        for idx, val in feats.items():
            w = self.weights.get(idx, 0.0)
            self.weights[idx] = w - self.learning_rate * (err * val + self.l2 * w)
        self.n_samples += 1

    def fit(self, records: List[Tuple[Dict[str, str], int]], epochs: int = 10):
        if not records:
            return
        for _ in range(epochs):
            for record, y in records:
                self.fit_one(record, y)

    def suggest(self, options: List[Dict[str, str]], top_k: int = 10):
        scored = [(self.predict_proba(o), o) for o in options]
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:top_k]

    def save(self):
        data = {
            "bias": self.bias,
            "weights": {str(k): v for k, v in self.weights.items()},
            "vocab": self.vocab,
            "n_samples": self.n_samples,
        }
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.bias = float(data.get("bias", 0.0))
            self.weights = {int(k): float(v) for k, v in data.get("weights", {}).items()}
            self.vocab = {str(k): int(v) for k, v in data.get("vocab", {}).items()}
            self.n_samples = int(data.get("n_samples", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.bias = 0.0
            self.weights = {}
            self.vocab = {}
            self.n_samples = 0


def get_model(config) -> LogisticRegression:
    path = config.get("ml.model_path", "ml_model.json")
    lr = float(config.get("ml.learning_rate", 0.15))
    l2 = float(config.get("ml.l2", 0.01))
    return LogisticRegression(path=path, learning_rate=lr, l2=l2)


def build_options(attempts: List[Dict]) -> List[Dict[str, str]]:
    """Кандидаты (service x country) на основе истории."""
    services = sorted({a.get("service") for a in attempts if a.get("service")}) or [None]
    countries = sorted({a.get("country") for a in attempts if a.get("country")}) or [None]
    options = []
    for s in services:
        for c in countries:
            options.append({"service": s, "country": c})
    return options


def find_opportunities(model: LogisticRegression, attempts: List[Dict], top_k: int = 10):
    return model.suggest(build_options(attempts), top_k=top_k)
