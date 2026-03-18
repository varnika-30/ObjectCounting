from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys

app = Flask(__name__)
CORS(app)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from ai_engine.counter import run_counter

session_active = False


@app.route("/start", methods=["POST"])
def start():
    global session_active
    session_active = True
    print("START Route hit")

    try:
        if "video" not in request.files:
            session_active = False
            return jsonify({"success": False, "error": "No video uploaded"}), 400

        video = request.files["video"]
        operator_id = request.form.get("operator_id", "operator_1")
        batch_id = request.form.get("batch_id", "batch_1")
        confidence = float(request.form.get("confidence", 0.5))

        videos_dir = os.path.join(PROJECT_ROOT, "videos")
        overlay_dir = os.path.join(PROJECT_ROOT, "overlay_videos")

        os.makedirs(videos_dir, exist_ok=True)
        os.makedirs(overlay_dir, exist_ok=True)

        input_video_path = os.path.join(videos_dir, "uploaded.mp4")
        overlay_video_path = os.path.join(overlay_dir, "overlay_output.mp4")

        video.save(input_video_path)

        print("About to call run_counter")

        count = run_counter(
            video_path=input_video_path,
            confidence_threshold=confidence,
            operator_id=operator_id,
            batch_id=batch_id,
            overlay_video_path=overlay_video_path
        )

        print("Run_counter finished")
        print("FINAL COUNT:", count)

        session_active = False

        return jsonify({
            "success": True,
            "count": int(count),
            "operator_id": operator_id,
            "batch_id": batch_id,
            "overlay_video": overlay_video_path
        })

    except Exception as e:
        session_active = False
        print("ERROR in /start:", str(e))
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/stop", methods=["POST"])
def stop():
    global session_active
    session_active = False
    return jsonify({"success": True, "message": "Session stopped"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)