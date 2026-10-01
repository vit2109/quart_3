"""Подготовить офлайн-модель эмбеддингов перед сборкой PyInstaller."""

from __future__ import annotations

from pathlib import Path

from sentence_transformers import SentenceTransformer


MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
TARGET = Path(__file__).resolve().parents[1] / "models" / "embedding" / "all-MiniLM-L6-v2"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(MODEL_ID)
    model.save_pretrained(str(TARGET))
    print(f"Embedding model prepared: {TARGET}")


if __name__ == "__main__":
    main()
