FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg git curl \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/Michele0303/tiktok-live-recorder /recorder

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:/root/.local/bin:$PATH"

WORKDIR /recorder
RUN uv venv && uv sync

RUN pip install --break-system-packages openai flask google-api-python-client google-auth

WORKDIR /app
COPY main.py .

RUN mkdir -p /recordings /transcripts /intel

CMD ["python", "main.py"]
