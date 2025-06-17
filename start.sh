#!/bin/bash

echo "🔁 Checking if Ollama is running..."

if ! pgrep -f "ollama serve" > /dev/null
then
  echo "🧠 Starting Ollama..."
  nohup ollama serve > ollama.log 2>&1 &
  sleep 2
else
  echo "✅ Ollama already running"
fi

# echo "📦 Ensuring model is pulled..."
# ollama list | grep -q llama3 || ollama pull llama3 


echo "🚀 Starting FastAPI backend..."
uvicorn main:app --reload --host 0.0.0.0 --port 8000
