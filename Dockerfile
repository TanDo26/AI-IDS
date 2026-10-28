# Training pipeline image (Compose profile "pipeline"; GPU through the NVIDIA runtime).
# Python 3.13 like the API image and the local venv: bundles are pickles, built here and loaded there.
FROM python:3.13

WORKDIR /app

# System dependencies for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt includes requirements/api.txt (the scikit-learn / xgboost pins bundles rely on)
COPY requirements.txt .
COPY requirements/ requirements/
# Explicitly install packages with the PyTorch CUDA index to ensure GPU wheels are pulled
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu130
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python"]
