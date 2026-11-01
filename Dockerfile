# Optional: the project runs with Python only. This image just calls run.py.
#   docker build -t felix .
#   docker run --rm felix                                   # full pipeline
#   docker run --rm -p 8501:8501 felix sh -c "python run.py all && streamlit run dashboard/app.py --server.address 0.0.0.0"
FROM python:3.13-slim

# git: `dbt debug` checks for it
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV DO_NOT_TRACK=1
EXPOSE 8501
CMD ["python", "run.py", "all"]
