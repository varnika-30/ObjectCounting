import cv2
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

model = YOLO("yolov8n.pt")
tracker = DeepSort()

def run_counter(video_path):
    cap = cv2.VideoCapture(video_path)

    frame_count = 0

    seen_ids = set()
    id_lifetime = {}   # track how long each object exists

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (640, 480))

        frame_count += 1
        if frame_count % 4 != 0:
            continue

        results = model(frame)
        detections = []

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])

                if conf < 0.3:
                    continue

                w = x2 - x1
                h = y2 - y1
                area = w * h

                if area < 5000:
                    continue

                # 🔥 shape filter
                aspect_ratio = w / h if h != 0 else 0
                if aspect_ratio < 0.5 or aspect_ratio > 2.5:
                    continue

                detections.append(([x1, y1, w, h], conf, "box"))

        tracks = tracker.update_tracks(detections, frame=frame)

        for t in tracks:
            if not t.is_confirmed():
                continue

            tid = t.track_id

            # track how long object exists
            if tid not in id_lifetime:
                id_lifetime[tid] = 0

            id_lifetime[tid] += 1

            # 🔥 only count stable objects
            if id_lifetime[tid] > 3:   # appears in multiple frames
                seen_ids.add(tid)

    cap.release()

    return len(seen_ids)