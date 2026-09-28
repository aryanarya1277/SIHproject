from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any


MODEL_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "models"
MODEL_FILES = {
    "disaster_detection": MODEL_ROOT / "disaster_detection.joblib",
    "event_type": MODEL_ROOT / "event_type.joblib",
}


@lru_cache(maxsize=2)
def _load_model(task: str) -> dict[str, Any]:
    model_path = MODEL_FILES[task]
    if not model_path.is_file():
        raise FileNotFoundError(
            f"AI model {task!r} is not trained. Run "
            "`python datasets/clean_data.py` and `python datasets/train_models.py`."
        )
    try:
        import joblib
    except ImportError as error:
        raise RuntimeError(
            "scikit-learn and joblib are required to load the trained model."
        ) from error
    # Only load model artifacts generated locally by datasets/train_models.py.
    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict) or "pipeline" not in artifact or "metadata" not in artifact:
        raise ValueError(f"AI model artifact {model_path} has an unsupported format.")
    return artifact


def classify_text(text: str) -> dict[str, Any]:
    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("Report text must not be empty.")
    try:
        detector = _load_model("disaster_detection")
        event_classifier = _load_model("event_type")
    except FileNotFoundError as error:
        raise RuntimeError(str(error)) from error

    disaster_model = detector["pipeline"]
    event_model = event_classifier["pipeline"]
    disaster_label = str(disaster_model.predict([normalized])[0])
    event_type = str(event_model.predict([normalized])[0])

    def score(artifact: dict[str, Any], label: str) -> float:
        pipeline = artifact["pipeline"]
        probabilities = pipeline.predict_proba([normalized])[0]
        classes = [str(value) for value in pipeline.named_steps["classifier"].classes_]
        return float(probabilities[classes.index(label)])

    return {
        "disaster_label": disaster_label,
        "disaster_score": round(score(detector, disaster_label), 4),
        "social_event_type": event_type,
        "event_type_score": round(score(event_classifier, event_type), 4),
        "model_version": "tfidf-logistic-regression-v1",
        "verification_status": "Unverified",
        "note": (
            "Social-text classification is not proof that a real-world event occurred. "
            "Scores are uncalibrated. Independent evidence and human assessment outside this app are required."
        ),
    }
