from flask import Flask, request, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
import os
import sys
import sqlite3
import uuid
from datetime import datetime, timedelta
from fpdf import FPDF

app = Flask(__name__)
CORS(app)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from ai_engine.counter import (
    run_counter,
    generate_webcam_frames,
    stop_counter,
    pause_counter,
    resume_counter,
    get_webcam_count,
    start_webcam_recording,
    finish_webcam_recording
)

session_active = False

VIDEOS_DIR = os.path.join(PROJECT_ROOT, "videos")
OVERLAY_DIR = os.path.join(PROJECT_ROOT, "overlay_videos")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
DB_PATH = os.path.join(PROJECT_ROOT, "sessions.db")

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(OVERLAY_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

CURRENT_WEBCAM_SESSION = {
    "session_id": None,
    "operator_id": None,
    "batch_id": None,
    "timestamp": None,
    "output_video_name": None,
    "report_file": None,
    "status": None
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            operator_id TEXT,
            batch_id TEXT,
            mode TEXT,
            timestamp TEXT,
            final_count INTEGER,
            input_video TEXT,
            output_video TEXT,
            report_file TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_session(
    session_id,
    operator_id,
    batch_id,
    mode,
    timestamp,
    final_count,
    input_video,
    output_video,
    report_file,
    status
):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sessions
        (session_id, operator_id, batch_id, mode, timestamp, final_count, input_video, output_video, report_file, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        operator_id,
        batch_id,
        mode,
        timestamp,
        final_count,
        input_video,
        output_video,
        report_file,
        status
    ))
    conn.commit()
    conn.close()


def generate_pdf_report(session_id, operator_id, batch_id, timestamp, final_count, output_video):
    report_filename = f"report_{session_id}.pdf"
    report_path = os.path.join(REPORTS_DIR, report_filename)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)

    pdf.cell(200, 10, txt="Box Counting Report", ln=True, align="C")
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Session ID: {session_id}", ln=True)
    pdf.cell(200, 10, txt=f"Operator ID: {operator_id}", ln=True)
    pdf.cell(200, 10, txt=f"Batch ID: {batch_id}", ln=True)
    pdf.cell(200, 10, txt=f"Timestamp: {timestamp}", ln=True)
    pdf.cell(200, 10, txt=f"Final Count: {final_count}", ln=True)
    pdf.cell(200, 10, txt=f"Overlay Video: {output_video}", ln=True)

    pdf.output(report_path)
    return report_filename


def cleanup_old_files(days=30):
    cutoff = datetime.now() - timedelta(days=days)

    for folder in [VIDEOS_DIR, OVERLAY_DIR, REPORTS_DIR]:
        for filename in os.listdir(folder):
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                modified_time = datetime.fromtimestamp(os.path.getmtime(path))
                if modified_time < cutoff:
                    try:
                        os.remove(path)
                    except Exception as e:
                        print(f"Could not delete {path}: {e}")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    confidence = float(request.args.get("confidence", 0.5))
    return Response(
        generate_webcam_frames(confidence_threshold=confidence),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/start", methods=["POST"])
def start():
    global session_active, CURRENT_WEBCAM_SESSION
    session_active = True
    cleanup_old_files()

    try:
        operator_id = request.form.get("operator_id", "operator_1")
        batch_id = request.form.get("batch_id", "batch_1")
        confidence = float(request.form.get("confidence", 0.5))
        mode = request.form.get("mode", "upload")

        session_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if mode == "webcam":
            output_video_name = f"overlay_{session_id}.mp4"
            output_video_path = os.path.join(OVERLAY_DIR, output_video_name)

            start_webcam_recording(output_video_path)

            CURRENT_WEBCAM_SESSION = {
                "session_id": session_id,
                "operator_id": operator_id,
                "batch_id": batch_id,
                "timestamp": timestamp,
                "output_video_name": output_video_name,
                "report_file": "",
                "status": "live"
            }

            save_session(
                session_id=session_id,
                operator_id=operator_id,
                batch_id=batch_id,
                mode="webcam",
                timestamp=timestamp,
                final_count=0,
                input_video="webcam",
                output_video=output_video_name,
                report_file="",
                status="live"
            )

            return jsonify({
                "success": True,
                "message": "Webcam live feed started",
                "session_id": session_id,
                "timestamp": timestamp,
                "overlay_video": f"/video/{output_video_name}"
            })

        if "video" not in request.files:
            session_active = False
            return jsonify({"success": False, "error": "No video uploaded"}), 400

        video = request.files["video"]

        input_video_name = f"input_{session_id}.mp4"
        input_video_path = os.path.join(VIDEOS_DIR, input_video_name)

        output_video_name = f"overlay_{session_id}.mp4"
        output_video_path = os.path.join(OVERLAY_DIR, output_video_name)

        video.save(input_video_path)

        count = run_counter(
            video_path=input_video_path,
            confidence_threshold=confidence,
            operator_id=operator_id,
            batch_id=batch_id,
            overlay_video_path=output_video_path
        )

        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise Exception("Overlay video file was not created properly")

        report_filename = generate_pdf_report(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            timestamp=timestamp,
            final_count=int(count),
            output_video=output_video_name
        )

        save_session(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            mode="upload",
            timestamp=timestamp,
            final_count=int(count),
            input_video=input_video_name,
            output_video=output_video_name,
            report_file=report_filename,
            status="completed"
        )

        session_active = False

        return jsonify({
            "success": True,
            "count": int(count),
            "operator_id": operator_id,
            "batch_id": batch_id,
            "session_id": session_id,
            "timestamp": timestamp,
            "overlay_video": f"/video/{output_video_name}",
            "report_file": f"/report/{report_filename}"
        })

    except Exception as e:
        session_active = False
        print("ERROR in /start:", str(e))
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/pause", methods=["POST"])
def pause():
    pause_counter()
    return jsonify({"success": True, "message": "Session paused"})


@app.route("/resume", methods=["POST"])
def resume():
    resume_counter()
    return jsonify({"success": True, "message": "Session resumed"})


@app.route("/done", methods=["POST"])
def done():
    global session_active, CURRENT_WEBCAM_SESSION
    session_active = False
    stop_counter()

    try:
        if not CURRENT_WEBCAM_SESSION["session_id"]:
            return jsonify({"success": False, "error": "No active webcam session found"}), 400

        finish_webcam_recording()

        session_id = CURRENT_WEBCAM_SESSION["session_id"]
        operator_id = CURRENT_WEBCAM_SESSION["operator_id"]
        batch_id = CURRENT_WEBCAM_SESSION["batch_id"]
        timestamp = CURRENT_WEBCAM_SESSION["timestamp"]
        output_video_name = CURRENT_WEBCAM_SESSION["output_video_name"]

        output_video_path = os.path.join(OVERLAY_DIR, output_video_name)
        final_count = int(get_webcam_count())

        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise Exception("Webcam overlay video file was not created properly")

        report_filename = generate_pdf_report(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            timestamp=timestamp,
            final_count=final_count,
            output_video=output_video_name
        )

        save_session(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            mode="webcam",
            timestamp=timestamp,
            final_count=final_count,
            input_video="webcam",
            output_video=output_video_name,
            report_file=report_filename,
            status="completed"
        )

        CURRENT_WEBCAM_SESSION = {
            "session_id": None,
            "operator_id": None,
            "batch_id": None,
            "timestamp": None,
            "output_video_name": None,
            "report_file": None,
            "status": None
        }

        return jsonify({
            "success": True,
            "message": "Recording finished",
            "count": final_count,
            "overlay_video": f"/video/{output_video_name}",
            "report_file": f"/report/{report_filename}"
        })

    except Exception as e:
        print("ERROR in /done:", str(e))
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/stop", methods=["POST"])
def stop():
    global session_active, CURRENT_WEBCAM_SESSION
    session_active = False
    stop_counter()

    CURRENT_WEBCAM_SESSION = {
        "session_id": None,
        "operator_id": None,
        "batch_id": None,
        "timestamp": None,
        "output_video_name": None,
        "report_file": None,
        "status": None
    }

    return jsonify({"success": True, "message": "Session stopped"})


@app.route("/video/<filename>")
def serve_video(filename):
    return send_from_directory(OVERLAY_DIR, filename)


@app.route("/report/<filename>")
def serve_report(filename):
    return send_from_directory(REPORTS_DIR, filename)


@app.route("/sessions", methods=["GET"])
def sessions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT session_id, operator_id, batch_id, mode, timestamp, final_count, output_video, report_file, status
        FROM sessions
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "session_id": row[0],
            "operator_id": row[1],
            "batch_id": row[2],
            "mode": row[3],
            "timestamp": row[4],
            "final_count": row[5],
            "output_video": row[6],
            "report_file": row[7],
            "status": row[8]
        })

    return jsonify({
        "success": True,
        "sessions": result
    })


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)