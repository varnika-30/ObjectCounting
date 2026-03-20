from flask import Flask, request, jsonify, render_template, send_from_directory, Response
from flask_cors import CORS
import os
import sys
import sqlite3
import uuid
import json
import time
from datetime import datetime, timedelta
from fpdf import FPDF

app = Flask(__name__)
CORS(app)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

VIDEOS_DIR = os.path.join(PROJECT_ROOT, "videos")
OVERLAY_DIR = os.path.join(PROJECT_ROOT, "overlay_videos")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
DB_PATH = os.path.join(PROJECT_ROOT, "sessions.db")

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(OVERLAY_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

from ai_engine.counter import (
    run_counter,
    generate_webcam_frames,
    stop_counter,
    pause_counter,
    resume_counter,
    get_webcam_count,
    get_webcam_product_count,
    get_webcam_product_counts,
    start_webcam_recording,
    finish_webcam_recording
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
            product_count INTEGER DEFAULT 0,
            product_counts TEXT DEFAULT '{}',
            input_video TEXT,
            output_video TEXT,
            report_file TEXT,
            status TEXT
        )
    """)

    cursor.execute("PRAGMA table_info(sessions)")
    columns = [row[1] for row in cursor.fetchall()]

    if "product_count" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN product_count INTEGER DEFAULT 0")

    if "product_counts" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN product_counts TEXT DEFAULT '{}'")

    conn.commit()
    conn.close()


def save_session(
    session_id,
    operator_id,
    batch_id,
    mode,
    timestamp,
    final_count,
    product_count,
    product_counts,
    input_video,
    output_video,
    report_file,
    status
):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO sessions
        (session_id, operator_id, batch_id, mode, timestamp, final_count, product_count, product_counts, input_video, output_video, report_file, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        operator_id,
        batch_id,
        mode,
        timestamp,
        int(final_count),
        int(product_count),
        json.dumps(product_counts),
        input_video,
        output_video,
        report_file,
        status
    ))

    conn.commit()
    conn.close()


def format_product_counts(product_counts):
    if not product_counts:
        return "None"
    return " | ".join([f"{k}: {v}" for k, v in product_counts.items()])


def generate_pdf_report(
    session_id,
    operator_id,
    batch_id,
    timestamp,
    final_count,
    product_count,
    product_counts,
    output_video
):
    report_filename = f"report_{session_id}.pdf"
    report_path = os.path.join(REPORTS_DIR, report_filename)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=10)

    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "CHALLAN", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Arial", size=10)

    pdf.cell(50, 8, "Challan No.", border=1)
    pdf.cell(140, 8, session_id, border=1, ln=True)

    pdf.cell(50, 8, "Date", border=1)
    pdf.cell(140, 8, timestamp, border=1, ln=True)

    pdf.cell(50, 8, "Customer's Name", border=1)
    pdf.cell(140, 8, operator_id, border=1, ln=True)

    pdf.cell(50, 8, "Batch / Order Ref", border=1)
    pdf.cell(140, 8, batch_id, border=1, ln=True)

    pdf.cell(50, 8, "Detected Products", border=1)
    pdf.cell(140, 8, str(product_count), border=1, ln=True)

    pdf.ln(5)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(20, 10, "Sr No.", border=1, align="C")
    pdf.cell(90, 10, "Goods", border=1, align="C")
    pdf.cell(35, 10, "Quantity", border=1, align="C")
    pdf.cell(45, 10, "Remarks", border=1, align="C", ln=True)

    pdf.set_font("Arial", size=10)
    pdf.cell(20, 10, "1", border=1, align="C")
    pdf.cell(90, 10, "Total Small Boxes", border=1)
    pdf.cell(35, 10, str(final_count), border=1, align="C")
    pdf.cell(45, 10, "Auto Counted", border=1, ln=True)

    row_no = 2
    for box_name, count in product_counts.items():
        pdf.cell(20, 10, str(row_no), border=1, align="C")
        pdf.cell(90, 10, box_name, border=1)
        pdf.cell(35, 10, str(count), border=1, align="C")
        pdf.cell(45, 10, "Per Product", border=1, ln=True)
        row_no += 1

    while row_no <= 7:
        pdf.cell(20, 10, str(row_no), border=1, align="C")
        pdf.cell(90, 10, "", border=1)
        pdf.cell(35, 10, "", border=1, align="C")
        pdf.cell(45, 10, "", border=1, ln=True)
        row_no += 1

    pdf.ln(5)
    pdf.multi_cell(0, 8, f"Detected Product Counts: {format_product_counts(product_counts)}")
    pdf.cell(0, 8, f"Overlay Video File: {output_video}", ln=True)
    pdf.cell(0, 8, "Receiver's Sign.: ____________________", ln=True)
    pdf.cell(0, 8, "Authorised Sign.: ____________________", ln=True)

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
        generate_webcam_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/start", methods=["POST"])
def start():
    global CURRENT_WEBCAM_SESSION
    cleanup_old_files()

    try:
        operator_id = request.form.get("operator_id", "operator_1")
        batch_id = request.form.get("batch_id", "batch_1")
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
                "report_file": None,
                "status": "live"
            }

            save_session(
                session_id=session_id,
                operator_id=operator_id,
                batch_id=batch_id,
                mode="webcam",
                timestamp=timestamp,
                final_count=0,
                product_count=0,
                product_counts={},
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
                "product_count": 0,
                "product_counts": {},
                "overlay_video": ""
            })

        if "video" not in request.files:
            return jsonify({"success": False, "error": "No video uploaded"}), 400

        video = request.files["video"]

        input_video_name = f"input_{session_id}.mp4"
        input_video_path = os.path.join(VIDEOS_DIR, input_video_name)

        output_video_name = f"overlay_{session_id}.mp4"
        output_video_path = os.path.join(OVERLAY_DIR, output_video_name)

        video.save(input_video_path)

        result = run_counter(
            video_path=input_video_path,
            overlay_video_path=output_video_path
        )

        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise Exception("Overlay video file was not created properly")

        total_count = int(result["total_count"])
        product_count = int(result["product_count"])
        product_counts = result["product_counts"]

        report_filename = generate_pdf_report(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            timestamp=timestamp,
            final_count=total_count,
            product_count=product_count,
            product_counts=product_counts,
            output_video=output_video_name
        )

        save_session(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            mode="upload",
            timestamp=timestamp,
            final_count=total_count,
            product_count=product_count,
            product_counts=product_counts,
            input_video=input_video_name,
            output_video=output_video_name,
            report_file=report_filename,
            status="completed"
        )

        cache_bust = int(time.time())

        return jsonify({
            "success": True,
            "count": total_count,
            "product_count": product_count,
            "product_counts": product_counts,
            "operator_id": operator_id,
            "batch_id": batch_id,
            "session_id": session_id,
            "timestamp": timestamp,
            "input_video": f"/input_video/{input_video_name}?t={cache_bust}",
            "overlay_video": f"/video/{output_video_name}?t={cache_bust}",
            "report_file": f"/report/{report_filename}?t={cache_bust}"
        })

    except Exception as e:
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
    global CURRENT_WEBCAM_SESSION
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
        product_count = int(get_webcam_product_count())
        product_counts = get_webcam_product_counts()

        for _ in range(20):
            if os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
                break
            time.sleep(0.2)

        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise Exception("Webcam overlay video file was not created properly")

        report_filename = generate_pdf_report(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            timestamp=timestamp,
            final_count=final_count,
            product_count=product_count,
            product_counts=product_counts,
            output_video=output_video_name
        )

        save_session(
            session_id=session_id,
            operator_id=operator_id,
            batch_id=batch_id,
            mode="webcam",
            timestamp=timestamp,
            final_count=final_count,
            product_count=product_count,
            product_counts=product_counts,
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

        cache_bust = int(time.time())

        return jsonify({
            "success": True,
            "message": "Recording finished",
            "count": final_count,
            "product_count": product_count,
            "product_counts": product_counts,
            "overlay_video": f"/video/{output_video_name}?t={cache_bust}",
            "report_file": f"/report/{report_filename}?t={cache_bust}"
        })

    except Exception as e:
        print("ERROR in /done:", str(e))
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/stop", methods=["POST"])
def stop():
    global CURRENT_WEBCAM_SESSION
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
    return send_from_directory(OVERLAY_DIR, filename, conditional=False)


@app.route("/input_video/<filename>")
def serve_input_video(filename):
    return send_from_directory(VIDEOS_DIR, filename, conditional=False)


@app.route("/report/<filename>")
def serve_report(filename):
    return send_from_directory(REPORTS_DIR, filename, conditional=False)


@app.route("/sessions", methods=["GET"])
def sessions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT session_id, operator_id, batch_id, mode, timestamp, final_count, product_count, product_counts, input_video, output_video, report_file, status
        FROM sessions
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        parsed_counts = {}
        try:
            parsed_counts = json.loads(row[7]) if row[7] else {}
        except Exception:
            parsed_counts = {}

        result.append({
            "session_id": row[0],
            "operator_id": row[1],
            "batch_id": row[2],
            "mode": row[3],
            "timestamp": row[4],
            "final_count": row[5],
            "product_count": row[6],
            "product_counts": parsed_counts,
            "input_video": row[8],
            "output_video": row[9],
            "report_file": row[10],
            "status": row[11]
        })

    return jsonify({
        "success": True,
        "sessions": result
    })


if __name__ == "__main__":
    init_db()
    print("Starting server...")
    app.run(debug=True, host="0.0.0.0", port=5001)