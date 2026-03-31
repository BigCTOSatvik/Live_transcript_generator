FROM python:3.11-slim

# system deps
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# clone the recorder
RUN git clone https://github.com/Michele0303/tiktok-live-recorder /recorder

# install uv and recorder deps
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:/root/.local/bin:$PATH"

WORKDIR /recorder
RUN uv venv && uv sync

# install our pipeline deps on top
RUN pip install openai

# copy our pipeline
WORKDIR /app
COPY main.py .

# directories
RUN mkdir -p /recordings /transcripts

CMD ["python", "main.py"]
