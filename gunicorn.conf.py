# gunicorn.conf.py
import os

workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8007"

log_dir = "/home/ubuntu/Projects/Incident-Investigation-Report/app/logs"
os.makedirs(log_dir, exist_ok=True)
accesslog = f"{log_dir}/gunicorn_access.log"
errorlog = f"{log_dir}/gunicorn_error.log"
loglevel = "info"

def post_worker_init(worker):
    # Use worker.age as reliable index (0,1,2,3...)
    os.environ["PYTHON_WORKER_INDEX"] = str(worker.age)
    worker.log.info(f"Worker {worker.age} initialized (PID: {worker.pid})")

def when_ready(server):
    server.log.info("Gunicorn server is ready. All workers spawned.")

