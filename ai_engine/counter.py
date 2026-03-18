import os
import cv2
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODEL_PATH = os.path.join(PROJECT_ROOT, "backend", "runs", "detect", "train", "weights", "best.pt")


def run_counter(
    video_path,
    confidence_threshold=0.35,
    operator_id="operator_1",
    batch_id="batch_1",
    overlay_video_path="overlay_output.mp4"
):
    model = YOLO(MODEL_PATH)
    print(model.names)
    print("Using model:", MODEL_PATH)

    tracker = DeepSort(max_age=30)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise Exception("Could not open video file")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps is None or fps <= 0:
        fps = 20.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(overlay_video_path, fourcc, fps, (width, height))

    counted_ids = set()
    seen_frames = {}
    total_count = 0

    frame_index = 0
    frame_skip = 2
    min_frames_to_count = 4

    process_width = 640
    process_height = int((process_width / width) * height)

    scale_x = width / process_width
    scale_y = height / process_height

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_index += 1

        if frame_index % frame_skip != 0:
            continue

        small_frame = cv2.resize(frame, (process_width, process_height))

        results = model(small_frame, verbose=False)[0]
        detections = []

        for box in results.boxes:
            conf = float(box.conf[0])
            if conf < confidence_threshold:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()

            x1 *= scale_x
            x2 *= scale_x
            y1 *= scale_y
            y2 *= scale_y

            w = x2 - x1
            h = y2 - y1
            cls_id = int(box.cls[0])

            detections.append(([x1, y1, w, h], conf, cls_id))

        tracks = tracker.update_tracks(detections, frame=frame)

        if frame_index % 30 == 0:
            print("detections found:", len(detections))
            print("tracks found:", len(tracks))

        for track in tracks:
            if not track.is_confirmed():
                continue

            ltrb = track.to_ltrb()
            if ltrb is None:
                continue

            track_id = track.track_id
            x1, y1, x2, y2 = map(int, ltrb)

            seen_frames[track_id] = seen_frames.get(track_id, 0) + 1

            if track_id not in counted_ids and seen_frames[track_id] >= min_frames_to_count:
                counted_ids.add(track_id)
                total_count = len(counted_ids)
                print(f"New stable object counted: ID {track_id} | total_count = {total_count}")

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"ID:{track_id}",
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

        cv2.putText(
            frame,
            f"Count: {total_count}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (255, 255, 255),
            2
        )

        out.write(frame)

    cap.release()
    out.release()

    print("FINAL COUNT:", total_count)
    return total_count