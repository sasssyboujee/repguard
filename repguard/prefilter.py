"""Local ML/NLP Pre-filter for screening reviews before sending to LLM.

Implements rule-based heuristics, VADER offline sentiment analysis,
a data logger for pseudo-labeling, and a local RandomForestClassifier
that can be trained once enough data is bootstrapped.
"""

from __future__ import annotations

import csv
import ssl
from pathlib import Path
import nltk

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

from repguard.utils import PROJECT_ROOT, console

# Setup data and models directories
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"

DATA_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

LABELED_DATA_PATH = DATA_DIR / "labeled_reviews.csv"
MODEL_PATH = MODELS_DIR / "prefilter_rf.joblib"

# Global cache for heavy library loads
_vader_analyzer = None
_loaded_model = None


def get_vader_analyzer():
    """Lazily initialize and return the VADER Sentiment Intensity Analyzer, downloading lexicon if needed."""
    global _vader_analyzer
    if _vader_analyzer is not None:
        return _vader_analyzer

    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
    except (LookupError, AttributeError):
        console.print("  [info]Downloading local NLTK VADER lexicon...[/info]")
        nltk.download("vader_lexicon", quiet=True)
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer


def extract_features(text: str, rating: int) -> dict[str, float]:
    """Extract linguistic and sentiment features from a review for classification."""
    text_clean = text.strip()
    words = text_clean.split()
    word_count = len(words)
    char_count = len(text_clean)

    if word_count == 0:
        lexical_diversity = 0.0
    else:
        lexical_diversity = len(set(w.lower() for w in words)) / word_count

    exclamation_count = text_clean.count("!")
    exclamation_density = exclamation_count / max(char_count, 1)

    alpha_chars = [c for c in text_clean if c.isalpha()]
    caps_chars = [c for c in alpha_chars if c.isupper()]
    caps_ratio = len(caps_chars) / max(len(alpha_chars), 1)

    # NLTK VADER Sentiment Analysis
    sia = get_vader_analyzer()
    sentiment = sia.polarity_scores(text_clean)
    neg = sentiment["neg"]
    neu = sentiment["neu"]
    pos = sentiment["pos"]
    compound = sentiment["compound"]

    # Sentiment-Rating Mismatch (highly suspicious)
    # Low rating but positive sentiment, or high rating but negative sentiment
    mismatch = 0.0
    if rating <= 2 and compound >= 0.3:
        mismatch = 1.0
    elif rating >= 4 and compound <= -0.3:
        mismatch = 1.0

    # Common generic low-effort/spam templates count
    generic_templates = [
        "worst experience", "terrible place", "very bad", "don't waste", "never go here",
        "stay away", "highly recommended", "best experience", "amazing service", "worst service",
        "worst customer service", "do not buy", "scam", "waste of money", "terrible", "horrible"
    ]
    text_lower = text_clean.lower()
    generic_count = sum(1 for template in generic_templates if template in text_lower)

    return {
        "rating": float(rating),
        "word_count": float(word_count),
        "char_count": float(char_count),
        "lexical_diversity": lexical_diversity,
        "exclamation_density": exclamation_density,
        "caps_ratio": caps_ratio,
        "vader_neg": neg,
        "vader_neu": neu,
        "vader_pos": pos,
        "vader_compound": compound,
        "sentiment_rating_mismatch": mismatch,
        "generic_template_count": float(generic_count),
    }


def compute_heuristic_suspicion(features: dict[str, float]) -> float:
    """Fallback rule-based heuristic suspicion score based on extracted features."""
    score = 0.0

    rating = features["rating"]
    word_count = features["word_count"]
    mismatch = features["sentiment_rating_mismatch"]
    caps_ratio = features["caps_ratio"]
    excl_density = features["exclamation_density"]
    generic_count = features["generic_template_count"]

    # Rule 1: Extreme rating with extremely brief text is highly suspicious
    if rating <= 2 and word_count <= 4:
        score += 0.45
    elif rating <= 2 and word_count <= 8:
        score += 0.25

    # Rule 2: Sentiment mismatch is highly suspicious
    if mismatch > 0:
        score += 0.40

    # Rule 3: Extreme ALL-CAPS shouting
    if caps_ratio > 0.4 and word_count >= 3:
        score += 0.20

    # Rule 4: Excessive exclamation marks
    if excl_density > 0.05:
        score += 0.15

    # Rule 5: Low rating + generic templates presence
    if rating <= 3 and generic_count >= 1:
        score += 0.15 * min(generic_count, 3)

    # Rule 6: If review rating is high and no mismatch, it's very likely clean
    if rating >= 4 and mismatch == 0:
        score -= 0.3

    return min(1.0, max(0.0, score))


def log_labeled_review(text: str, rating: int, is_suspicious: bool, confidence_score: float) -> None:
    """Log a review, its extracted features, and Gemini's decision to build the training dataset."""
    features = extract_features(text, rating)
    row = {
        "text": text,
        "is_suspicious": 1 if is_suspicious else 0,
        "confidence_score": confidence_score,
        **features
    }

    file_exists = LABELED_DATA_PATH.exists()
    headers = ["text", "is_suspicious", "confidence_score"] + list(features.keys())

    try:
        with open(LABELED_DATA_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        console.print(f"  [warning]⚠ Failed to log review to dataset: {e}[/warning]")


def get_trained_model():
    """Load the trained Random Forest model if it exists."""
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model

    if MODEL_PATH.exists():
        try:
            import joblib
            _loaded_model = joblib.load(MODEL_PATH)
            return _loaded_model
        except Exception as e:
            console.print(f"  [warning]⚠ Failed to load trained ML model: {e}. Falling back to heuristics.[/warning]")
    return None


def predict_suspicion(text: str, rating: int) -> float:
    """Predict the suspicion score of a review.

    Uses a local RandomForestClassifier if trained, otherwise falls back to rule-based heuristics.
    """
    features = extract_features(text, rating)
    model = get_trained_model()

    if model is not None:
        try:
            import pandas as pd
            feature_names = [
                "rating", "word_count", "char_count", "lexical_diversity",
                "exclamation_density", "caps_ratio", "vader_neg", "vader_neu",
                "vader_pos", "vader_compound", "sentiment_rating_mismatch",
                "generic_template_count"
            ]
            df = pd.DataFrame([features])[feature_names]
            probs = model.predict_proba(df)[0]
            classes = list(model.classes_)
            if 1 in classes:
                class_1_idx = classes.index(1)
                return float(probs[class_1_idx])
            else:
                return 0.0
        except Exception as e:
            console.print(f"  [warning]⚠ Random Forest prediction failed: {e}. Using heuristics instead.[/warning]")

    return compute_heuristic_suspicion(features)


def train_prefilter() -> str:
    """Train a RandomForestClassifier on the collected labeled review CSV file."""
    if not LABELED_DATA_PATH.exists():
        raise FileNotFoundError(
            f"No training data found at {LABELED_DATA_PATH}.\n"
            "Analyze reviews with Gemini first to automatically collect training data."
        )

    try:
        import pandas as pd
        import joblib
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as e:
        raise ImportError(
            f"Missing dependencies for training: {e}.\n"
            "Run 'uv sync' or make sure scikit-learn, pandas, and joblib are installed."
        )

    df = pd.read_csv(LABELED_DATA_PATH)
    min_samples = 10
    if len(df) < min_samples:
        raise ValueError(
            f"Insufficient training data. Found {len(df)} samples, need at least {min_samples}.\n"
            "Analyze more reviews to collect enough samples."
        )

    if len(df["is_suspicious"].unique()) < 2:
        raise ValueError(
            "Training dataset must contain both suspicious (1) and clean (0) samples.\n"
            f"Current samples only contain class: {df['is_suspicious'].unique()}"
        )

    feature_names = [
        "rating", "word_count", "char_count", "lexical_diversity",
        "exclamation_density", "caps_ratio", "vader_neg", "vader_neu",
        "vader_pos", "vader_compound", "sentiment_rating_mismatch",
        "generic_template_count"
    ]

    X = df[feature_names]
    y = df["is_suspicious"]

    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    model.fit(X, y)

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    global _loaded_model
    _loaded_model = model

    return str(MODEL_PATH)
