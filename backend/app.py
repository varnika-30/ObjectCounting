import sys
import os

# allow importing from parent folder
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, jsonify, request
from flask_cors import CORS
from ai_engine.counter import run_counter

app = Flask(__name__)
CORS(app)

@app.route("/start", methods=["POST"])
def start():
    file = request.files.get("video")

    if not file:
        return jsonify({"error": "No video uploaded"}), 400

    video_path = "videos/uploaded.mp4"
    file.save(video_path)

    count = run_counter(video_path)
    print("FINAL COUNT:", count)
    return jsonify({"final_count": int(count)})

if __name__ == "__main__":
    app.run(debug=True)