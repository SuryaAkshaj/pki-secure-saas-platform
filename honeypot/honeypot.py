 from flask import Flask, request
import logging

app = Flask(__name__)

# Logging setup
logging.basicConfig(filename='honeypot.log', level=logging.INFO,
                    format='%(asctime)s - %(message)s')

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def catch_all(path):
    log_msg = f"Unauthorized access attempt from {request.remote_addr}, Path: {path}, Method: {request.method}"
    logging.info(log_msg)
    return {"status": "error", "message": "Access Denied"}, 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000)
