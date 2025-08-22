import os

workers = 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 2

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Bind to PORT if defined, otherwise default to 5000
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"