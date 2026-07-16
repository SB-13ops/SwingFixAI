FROM python:3.12-slim

# System libraries OpenCV and MediaPipe need
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libgl1 libgles2 libegl1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Bake the MediaPipe pose model into the image so analyses never depend
# on a runtime download succeeding
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task', '/app/backend/app/pose_landmarker_lite.task')"

WORKDIR /app/backend
RUN mkdir -p uploads

# ANTHROPIC_API_KEY is optional - set it in your host's dashboard for AI coaching,
# or leave it unset to use the built-in measured coaching engine.
ENV PORT=8000
EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
