FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py upload-voice.sh entrypoint-tts.sh ./
RUN chmod +x upload-voice.sh entrypoint-tts.sh

CMD ["python", "agent.py", "start"]
