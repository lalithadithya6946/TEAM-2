import os
import sqlite3
import json
import cv2
import face_recognition
import numpy as np
import io
import csv

from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify, make_response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from data_manager import DataManager
import threading
from flask import current_app


# ---------------------- APP CONFIG ----------------------
app = Flask(__name__)
# Use environment variable for secret key in production; keep default for local dev
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
PHOTO_FOLDER = os.path.join(BASE_DIR, "static", "photos")
STUDENT_PHOTOS_FOLDER = os.path.join(BASE_DIR, "student_photos")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PHOTO_FOLDER, exist_ok=True)
os.makedirs(STUDENT_PHOTOS_FOLDER, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "auth.db")
DATA_MANAGER = DataManager()
WEBCAM_DEVICE_INDEX = int(os.environ.get("WEBCAM_DEVICE_INDEX", "0"))
# Standard defaults for live streaming
LIVE_FRAME_STRIDE = int(os.environ.get("LIVE_FRAME_STRIDE", "2"))
LIVE_DOWNSCALE = float(os.environ.get("LIVE_DOWNSCALE", "0.5"))  # 0.5 => 50% size
# SKIPPED_FRAME_DOWNSCALE of 1.0 means don't downscale skipped frames (stream at full size)
SKIPPED_FRAME_DOWNSCALE = float(os.environ.get("SKIPPED_FRAME_DOWNSCALE", "1.0"))
# Higher JPEG quality by default for clearer stream
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "95"))
LIVE_WIDTH = int(os.environ.get("LIVE_WIDTH", "640"))
LIVE_HEIGHT = int(os.environ.get("LIVE_HEIGHT", "480"))
LIVE_TRACKS = {}

# Maximum allowed face distance for a positive match. Lower => stricter matching.
# Tune this between ~0.35 (strict) and 0.95 (lenient). Can be overridden with env var.
# Note: the confidence check (1 - distance >= 0.45) and clear-win margin still apply.
MATCH_DISTANCE_THRESHOLD = float(os.environ.get("MATCH_DISTANCE_THRESHOLD", "0.9"))

# Global holder for known face encodings loaded in background
KNOWN_HOLDER = {'encodings': [], 'regnos': [], 'loaded': False}

def _background_load_known():
    try:
        encs, regnos = load_known_faces()
        KNOWN_HOLDER['encodings'] = encs
        KNOWN_HOLDER['regnos'] = regnos
        KNOWN_HOLDER['loaded'] = True
        print(f"DEBUG: Background loaded {len(encs)} known encodings")
    except Exception as e:
        print(f"DEBUG: Background load error: {e}")

def append_new_face_to_cache(regno, filepath):
    """Immediately encodes a new photo and appends it to the live stream memory & disk cache without a full rebuild."""
    try:
        image = face_recognition.load_image_file(filepath)
        encs = face_recognition.face_encodings(image)
        if encs and len(encs) > 0:
            new_encoding = encs[0]
            
            # Append to memory immediately
            if KNOWN_HOLDER['loaded']:
                KNOWN_HOLDER['encodings'].append(new_encoding)
                KNOWN_HOLDER['regnos'].append(regno)
            
            # Append to disk cache immediately
            cache_path = os.path.join(BASE_DIR, 'encodings_cache.npz')
            if os.path.exists(cache_path):
                npz = np.load(cache_path, allow_pickle=True)
                disk_encs = list(npz['encodings'])
                disk_regnos = list(npz['regnos'])
                
                disk_encs.append(new_encoding)
                disk_regnos.append(regno)
                
                enc_array = np.array(disk_encs)
                reg_array = np.array(disk_regnos, dtype=object)
                np.savez_compressed(cache_path, encodings=enc_array, regnos=reg_array)
            # If cache file doesn't exist, we don't need to append (it will be built next restart)

            print(f"DEBUG: Successfully appended new encoding for {regno} to live cache.")
            return True
        else:
            print(f"DEBUG: No face detected in uploaded photo {filepath}")
            return False
    except Exception as e:
        print(f"DEBUG: Error caching new photo {filepath}: {e}")
        return False

# NOTE: background loader will be started after `load_known_faces` is defined


@app.route('/reload_encodings')
def reload_encodings():
    """Trigger reloading of known face encodings in background."""
    try:
        import subprocess
        # Run the standalone cache builder we created
        subprocess.Popen(["python", "build_cache.py"], cwd=BASE_DIR)
        return jsonify({'started': True, 'message': 'Rebuilding cache in background. This may take a minute.'})
    except Exception as e:
        return jsonify({'started': False, 'error': str(e)})

@app.route('/load_encodings_sync')
def load_encodings_sync():
    """Synchronously load encodings (runs in request thread) and return count."""
    try:
        import subprocess
        # Run the builder synchronously
        subprocess.run(["python", "build_cache.py"], cwd=BASE_DIR, check=True)
        # Reload the cache into memory
        encs, regnos = load_known_faces()
        KNOWN_HOLDER['encodings'] = encs
        KNOWN_HOLDER['regnos'] = regnos
        KNOWN_HOLDER['loaded'] = True
        return jsonify({'loaded': True, 'count': len(encs), 'regnos_sample': regnos[:10]})
    except Exception as e:
        return jsonify({'loaded': False, 'error': str(e)})

# ---------------------- DATABASE ----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # User login table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student','faculty')),
            is_first_login INTEGER DEFAULT 1
        )
    """)
    # Student details table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            regno TEXT PRIMARY KEY,
            name TEXT,
            dept TEXT,
            father_name TEXT,
            father_phno TEXT,
            portal TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------- HELPER FUNCTIONS ----------------------
def save_student_photos(regno, front_photo, left_photo, right_photo):
    """Save student photos by regno_side.jpg and encode immediately"""
    photos = {}
    
    # helper to save and encode
    def save_and_encode(photo, side):
        if photo:
            filename = f"{regno}_{side}.jpg"
            filepath = os.path.join(STUDENT_PHOTOS_FOLDER, filename)
            photo.save(filepath)
            photos[side] = filepath
            
            # Instantly encode and add to cache!
            append_new_face_to_cache(regno, filepath)

    save_and_encode(front_photo, 'front')
    save_and_encode(left_photo, 'left')
    save_and_encode(right_photo, 'right')
    
    return photos

def load_known_faces():
    """Load encodings of registered students from all 3 sides"""
    known_encodings, known_regnos = [], []

    # Try to load from on-disk cache first
    try:
        cache_path = os.path.join(BASE_DIR, 'encodings_cache.npz')
        if os.path.exists(cache_path):
            npz = np.load(cache_path, allow_pickle=True)
            encs = npz['encodings']
            regnos = npz['regnos']
            # Convert to list of arrays
            known_encodings = [e for e in encs]
            known_regnos = [r for r in regnos]
            print(f"DEBUG: Loaded {len(known_encodings)} encodings from cache")
            return known_encodings, known_regnos
    except Exception as e:
        print(f"DEBUG: Failed loading encodings cache: {e}")

    # Load from student_photos folder (3 sides)
    if os.path.exists(STUDENT_PHOTOS_FOLDER):
        for file in os.listdir(STUDENT_PHOTOS_FOLDER):
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                regno = file.split("_")[0]
                image_path = os.path.join(STUDENT_PHOTOS_FOLDER, file)
                try:
                    image = face_recognition.load_image_file(image_path)
                    encs = face_recognition.face_encodings(image)
                    if encs and len(encs) > 0:
                        known_encodings.append(encs[0])
                        known_regnos.append(regno)
                    else:
                        pass # Silently skip images without faces to keep logs clean
                except Exception as e:
                    print(f"DEBUG: Error processing {image_path}: {e}")

    # Also load from photos folder (legacy)
    if os.path.exists(PHOTO_FOLDER):
        for file in os.listdir(PHOTO_FOLDER):
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                regno = file.split(".")[0]
                image_path = os.path.join(PHOTO_FOLDER, file)
                try:
                    image = face_recognition.load_image_file(image_path)
                    encs = face_recognition.face_encodings(image)
                    if encs and len(encs) > 0:
                        known_encodings.append(encs[0])
                        known_regnos.append(regno)
                except Exception as e:
                    print(f"DEBUG: Error processing legacy {image_path}: {e}")

    # Save to cache for faster startup
    try:
        if len(known_encodings) > 0:
            enc_array = np.array(known_encodings)
            reg_array = np.array(known_regnos, dtype=object)
            np.savez_compressed(os.path.join(BASE_DIR, 'encodings_cache.npz'), encodings=enc_array, regnos=reg_array)
            print(f"DEBUG: Saved {len(known_encodings)} encodings to cache")
    except Exception as e:
        print(f"DEBUG: Failed saving encodings cache: {e}")

    return known_encodings, known_regnos



# Start background loader once (after load_known_faces is defined)
try:
    threading.Thread(target=_background_load_known, daemon=True).start()
except Exception as e:
    print(f"DEBUG: Could not start background loader: {e}")

# ---------------------- LIGHTING ADJUSTMENT ----------------------
# Global brightness adjustment value (user-controlled)
BRIGHTNESS_ADJUSTMENT = 0  # Range: -50 to +50

def adjust_lighting(frame, manual_brightness=0):
    """Adjust frame brightness and contrast based on lighting conditions"""
    try:
        # Convert to LAB color space for better lighting adjustment
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a, b = cv2.split(lab)
        
        # Calculate average brightness
        avg_brightness = cv2.mean(l_channel)[0]
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_channel = clahe.apply(l_channel)
        
        # Adjust brightness based on conditions
        if avg_brightness < 80:  # Low light - increase brightness
            l_channel = cv2.convertScaleAbs(l_channel, alpha=1.3, beta=30)
        elif avg_brightness > 180:  # Very bright - decrease brightness
            l_channel = cv2.convertScaleAbs(l_channel, alpha=0.8, beta=-20)
        
        # Apply manual brightness adjustment from user
        if manual_brightness != 0:
            l_channel = cv2.convertScaleAbs(l_channel, alpha=1.0, beta=manual_brightness)
        
        # Merge back
        lab = cv2.merge([l_channel, a, b])
        adjusted_frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        return adjusted_frame, avg_brightness
    except Exception as e:
        # If adjustment fails, return original frame
        return frame, 0

def get_student(regno):
    # Try data_manager first
    student = DATA_MANAGER.get_student(regno)
    if student:
        return {
            "regno": student["reg_no"], 
            "name": student["name"], 
            "dept": student["dept"], 
            "father_name": student["father_name"], 
            "father_phno": student["father_phone"], 
            "portal": f"/student/{regno}"
        }
    
    # Fallback to old database
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE regno=?", (regno,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"regno": row[0], "name": row[1], "dept": row[2], "father_name": row[3], "father_phno": row[4], "portal": row[5]}
    return None

def save_analysis_cache(video_filename, results):
    """Save analysis results to cache for faster loading"""
    try:
        import json
        cache_dir = os.path.join(BASE_DIR, "track_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, f"{video_filename}.json")
        with open(cache_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"DEBUG: Analysis results cached to {cache_file}")
    except Exception as e:
        print(f"DEBUG: Error saving cache: {e}")

def load_analysis_cache(video_filename):
    """Load analysis results from cache"""
    try:
        import json
        cache_file = os.path.join(BASE_DIR, "track_cache", f"{video_filename}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                results = json.load(f)
            print(f"DEBUG: Loaded analysis results from cache: {len(results)} faces")
            return results
    except Exception as e:
        print(f"DEBUG: Error loading cache: {e}")
    return None

def process_video_and_recognize(video_filename):
    video_path = os.path.join(UPLOAD_FOLDER, video_filename)
    results = []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"DEBUG: Error opening video file {video_path}")
        return []

    try:
        # Load known faces once
        known_encodings, known_regnos = load_known_faces()
        print(f"DEBUG: Loaded {len(known_encodings)} known face encodings")
        # Prepare unknown snapshot storage
        unknown_dir = os.path.join(BASE_DIR, "static", "photos", "unknowns")
        os.makedirs(unknown_dir, exist_ok=True)
        saved_unknown_encodings = []
        saved_unknown_count = 0
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0: fps = 25  # Default fps

        # Analyze every Nth frame (lower number => more boxes, higher CPU)
        FRAME_STRIDE = 3

        frame_count = 0
        processed_frames = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_count += 1
            
            # Process every Nth frame to balance performance and accuracy
            if frame_count % FRAME_STRIDE != 0:
                continue

            processed_frames += 1
            print(f"DEBUG: Processing frame {frame_count}/{total_frames} ({processed_frames} processed)")
            
            try:
                # Convert BGR (OpenCV) -> RGB (face_recognition expects RGB)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Find faces in the frame
                face_locations = face_recognition.face_locations(rgb_frame)
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                
                for face_encoding, face_location in zip(face_encodings, face_locations):
                    # Compare with known faces (use distance threshold to avoid false positives)
                    reg_no = "UNKNOWN"
                    confidence = 0.0
                    if len(known_encodings) > 0:
                        # Get distances to all known faces
                        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                        # Find the best match
                        best_match_index = int(np.argmin(face_distances))
                        best_distance = float(face_distances[best_match_index])
                        
                        # Calculate match confidence (1.0 = perfect match, 0.0 = completely different)
                        confidence = max(0.0, 1.0 - best_distance)
                        
                        # Multiple checks for accurate recognition:
                        # 1. Distance must be below threshold
                        # 2. Confidence must be high enough (at least 45%)
                        # 3. Must be significantly better than second-best match
                        is_good_match = (best_distance <= MATCH_DISTANCE_THRESHOLD and confidence >= 0.45)
                        
                        # Check if there's a clear winner (significantly better than other matches)
                        if len(face_distances) > 1:
                            # Sort distances and get second-best
                            sorted_distances = np.sort(face_distances)
                            second_best = float(sorted_distances[1])
                            # Ensure best match is significantly better than second best
                            margin = second_best - best_distance
                            is_good_match = is_good_match and margin > 0.1
                        
                        if is_good_match:
                            reg_no = known_regnos[best_match_index]
                        else:
                            # Explicitly mark as unknown with low confidence
                            reg_no = "UNKNOWN"
                            confidence = min(confidence, 0.3)  # Cap unknown confidence

                    # Get face coordinates
                    top, right, bottom, left = face_location
                    frame_h, frame_w, _ = frame.shape

                    results.append({
                        "t": frame_count / fps,
                        "x": left / frame_w, "y": top / frame_h,
                        "w": (right - left) / frame_w, "h": (bottom - top) / frame_h,
                        "reg_no": reg_no,
                        "score": confidence
                    })
                    if reg_no != "UNKNOWN":
                        print(f"DEBUG: Recognized {reg_no} with confidence {confidence:.2f}")
                    else:
                        # Unknown face
                        print(f"DEBUG: Found unknown face in frame {frame_count}")

                        # Save one snapshot per unique unknown person
                        try:
                            is_new_unknown = True
                            for enc in saved_unknown_encodings:
                                d = np.linalg.norm(enc - face_encoding)
                                if d < 0.6:  # similar to an already saved unknown
                                    is_new_unknown = False
                                    break
                            if is_new_unknown:
                                crop = frame[max(0, top):max(0, bottom), max(0, left):max(0, right)]
                                if crop.size > 0:
                                    saved_unknown_count += 1
                                    fname = f"{os.path.splitext(video_filename)[0]}_unknown_{saved_unknown_count:03d}.jpg"
                                    cv2.imwrite(os.path.join(unknown_dir, fname), crop)
                                    saved_unknown_encodings.append(face_encoding)
                                    print(f"DEBUG: Saved unknown snapshot {fname}")
                        except Exception as se:
                            print(f"DEBUG: Failed saving unknown snapshot: {se}")
                    
            except Exception as e:
                print(f"DEBUG: Face recognition error in frame {frame_count}: {e}")

    except Exception as e:
        print(f"DEBUG: Error in video processing: {str(e)}")
    finally:
        cap.release()
        print(f"DEBUG: Video analysis complete. Processed {processed_frames} frames, found {len(results)} faces")
        
        # Save results to cache
        save_analysis_cache(video_filename, results)
        
    return results

# ---------------------- LIVE WEBCAM STREAM ----------------------
def generate_webcam_frames():
    """Generator that yields MJPEG frames from the default webcam with face boxes and labels."""
    cap = cv2.VideoCapture(WEBCAM_DEVICE_INDEX)
    if not cap.isOpened():
        print(f"DEBUG: Could not open webcam at index {WEBCAM_DEVICE_INDEX}")
        return

    # Try to set modest resolution to improve FPS
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, LIVE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LIVE_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, 30)
    except Exception:
        pass

    # Use global KNOWN_HOLDER started at module import
    global KNOWN_HOLDER

    try:
        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                print("DEBUG: Webcam frame grab failed")
                break

            try:
                frame_index += 1
                if LIVE_FRAME_STRIDE > 1 and (frame_index % LIVE_FRAME_STRIDE != 0):
                    # Still send a downscaled frame to keep stream smooth and reduce encoding cost
                    encode_frame = frame
                    if SKIPPED_FRAME_DOWNSCALE > 0 and SKIPPED_FRAME_DOWNSCALE < 1.0:
                        encode_frame = cv2.resize(frame, (0, 0), fx=SKIPPED_FRAME_DOWNSCALE, fy=SKIPPED_FRAME_DOWNSCALE)
                    ret2, buffer = cv2.imencode('.jpg', encode_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                    if ret2:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    continue

                # Downscale for faster face detection
                small_frame = frame
                scale = 1.0
                if LIVE_DOWNSCALE > 0 and LIVE_DOWNSCALE < 1.0:
                    small_frame = cv2.resize(frame, (0, 0), fx=LIVE_DOWNSCALE, fy=LIVE_DOWNSCALE)
                    scale = LIVE_DOWNSCALE

                # If known encodings are not yet loaded, skip face detection
                # and stream raw frames immediately to the client to reduce startup delay.
                if not KNOWN_HOLDER.get('loaded'):
                    # Update live tracks with empty boxes so overlay polling works
                    LIVE_TRACKS['webcam'] = {'ts': datetime.utcnow().timestamp(), 'boxes': []}
                    try:
                        encode_frame = frame
                        if SKIPPED_FRAME_DOWNSCALE > 0 and SKIPPED_FRAME_DOWNSCALE < 1.0:
                            encode_frame = cv2.resize(frame, (0, 0), fx=SKIPPED_FRAME_DOWNSCALE, fy=SKIPPED_FRAME_DOWNSCALE)
                        ret2, buffer = cv2.imencode('.jpg', encode_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                        if not ret2:
                            continue
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                        continue
                    except Exception:
                        # If encoding fails, fall back to continuing loop
                        continue

                rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=0, model='hog')
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

                detections = []
                for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                    # Rescale boxes back to original frame size
                    if scale != 1.0:
                        top = int(top / scale)
                        right = int(right / scale)
                        bottom = int(bottom / scale)
                        left = int(left / scale)
                    label = "UNKNOWN"
                    color = (0, 255, 0)
                    if len(KNOWN_HOLDER['encodings']) > 0:
                        face_distances = face_recognition.face_distance(KNOWN_HOLDER['encodings'], face_encoding)
                        best_match_index = int(np.argmin(face_distances))
                        best_distance = float(face_distances[best_match_index])
                        if best_distance <= MATCH_DISTANCE_THRESHOLD:
                            label = KNOWN_HOLDER['regnos'][best_match_index]
                    # Draw rectangle and label
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom - 20), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, label, (left + 4, bottom - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                    # Publish normalized box for overlays
                    h, w = frame.shape[:2]
                    detections.append({
                        'x': max(0.0, left / w),
                        'y': max(0.0, top / h),
                        'w': max(0.0, (right - left) / w),
                        'h': max(0.0, (bottom - top) / h),
                        'reg_no': label
                    })

                # Update live tracks for webcam
                LIVE_TRACKS['webcam'] = {
                    'ts': datetime.utcnow().timestamp(),
                    'boxes': detections
                }

                # Apply lighting adjustment based on ambient conditions
                frame, brightness = adjust_lighting(frame, BRIGHTNESS_ADJUSTMENT)

                # Encode frame as JPEG for MJPEG stream (use configured quality)
                ret2, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if not ret2:
                    continue
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception as e:
                print(f"DEBUG: Error processing webcam frame: {e}")
                continue
    finally:
        cap.release()

def generate_stream_frames(source):
    """Generic MJPEG generator for any cv2.VideoCapture source (e.g., RTSP/HTTP file/camera)."""
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"DEBUG: Could not open stream source: {source}")
        return

    known_encodings, known_regnos = load_known_faces()
    print(f"DEBUG: Stream source loaded {len(known_encodings)} known encodings")

    try:
        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                print("DEBUG: Stream frame grab failed")
                break

            try:
                frame_index += 1
                if LIVE_FRAME_STRIDE > 1 and (frame_index % LIVE_FRAME_STRIDE != 0):
                    encode_frame = frame
                    if SKIPPED_FRAME_DOWNSCALE > 0 and SKIPPED_FRAME_DOWNSCALE < 1.0:
                        encode_frame = cv2.resize(frame, (0, 0), fx=SKIPPED_FRAME_DOWNSCALE, fy=SKIPPED_FRAME_DOWNSCALE)
                    ret2, buffer = cv2.imencode('.jpg', encode_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                    if ret2:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    continue

                scale = 1.0
                small_frame = frame
                if LIVE_DOWNSCALE > 0 and LIVE_DOWNSCALE < 1.0:
                    small_frame = cv2.resize(frame, (0, 0), fx=LIVE_DOWNSCALE, fy=LIVE_DOWNSCALE)
                    scale = LIVE_DOWNSCALE

                rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=0, model='hog')
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

                detections = []
                for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                    if scale != 1.0:
                        top = int(top / scale)
                        right = int(right / scale)
                        bottom = int(bottom / scale)
                        left = int(left / scale)

                    label = "UNKNOWN"
                    color = (0, 255, 0)
                    if len(known_encodings) > 0:
                        matches = face_recognition.compare_faces(known_encodings, face_encoding)
                        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                        if True in matches:
                            best_match_index = np.argmin(face_distances)
                            label = known_regnos[best_match_index]
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom - 20), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, label, (left + 4, bottom - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                    h, w = frame.shape[:2]
                    detections.append({
                        'x': max(0.0, left / w),
                        'y': max(0.0, top / h),
                        'w': max(0.0, (right - left) / w),
                        'h': max(0.0, (bottom - top) / h),
                        'reg_no': label
                    })

                # Update live tracks for cctv keyed by src
                LIVE_TRACKS[f'cctv::{source}'] = {
                    'ts': datetime.utcnow().timestamp(),
                    'boxes': detections
                }

                # Apply lighting adjustment based on ambient conditions
                frame, brightness = adjust_lighting(frame, BRIGHTNESS_ADJUSTMENT)

                ret2, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if not ret2:
                    continue
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception as e:
                print(f"DEBUG: Error processing stream frame: {e}")
                continue
    finally:
        cap.release()

# ---------------------- ROUTES ----------------------
@app.route("/")
def index():
    if "role" in session:
        if session["role"] == "student":
            return redirect(url_for("student_dashboard"))
        else:
            return redirect(url_for("faculty_dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        reg_no = request.form.get("reg_no")
        password = request.form.get("password")
        
        role, message = DATA_MANAGER.verify_user(reg_no, password)
        if role:
            session["reg_no"] = reg_no
            session["role"] = role
            flash(f"Welcome {reg_no}!", "success")
            return redirect(url_for("index"))
        else:
            flash(message or "Invalid credentials", "danger")
    
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "info")
    return redirect(url_for("login"))

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "reg_no" not in session:
        flash("Please login to continue", "danger")
        return redirect(url_for("login"))

    message = None
    if request.method == "POST":
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if not old_password or not new_password or not confirm_password:
            message = "All fields are required"
        elif new_password != confirm_password:
            message = "New passwords do not match"
        else:
            ok, msg = DATA_MANAGER.update_user_password(session["reg_no"], old_password, new_password)
            if ok:
                flash("Password updated successfully", "success")
                # Redirect to appropriate dashboard based on role
                if session.get("role") == "faculty":
                    return redirect(url_for("faculty_dashboard"))
                else:
                    return redirect(url_for("student_dashboard"))
            else:
                message = msg

    return render_template("change_password.html", message=message)

@app.route("/faculty_dashboard")
def faculty_dashboard():
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    # Get uploaded videos with metadata
    videos = []
    if os.path.exists(UPLOAD_FOLDER):
        video_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        for video_file in video_files:
            video_path = os.path.join(UPLOAD_FOLDER, video_file)
            try:
                # Get file stats
                stat = os.stat(video_path)
                file_size = stat.st_size
                modified_time = stat.st_mtime
                
                # Check if analysis results exist
                analysis_file = os.path.join(BASE_DIR, "track_cache", f"{video_file}.json")
                has_analysis = os.path.exists(analysis_file)
                
                videos.append({
                    'filename': video_file,
                    'size': file_size,
                    'modified': datetime.fromtimestamp(modified_time).strftime('%Y-%m-%d %H:%M'),
                    'has_analysis': has_analysis
                })
            except Exception as e:
                print(f"Error getting video info for {video_file}: {e}")
                videos.append({
                    'filename': video_file,
                    'size': 0,
                    'modified': 'Unknown',
                    'has_analysis': False
                })
    
    # Sort videos by modification time (newest first)
    videos.sort(key=lambda x: x['modified'] if x['modified'] != 'Unknown' else '1970-01-01 00:00', reverse=True)
    
    # Get gallery clips
    gallery = []
    gallery_path = os.path.join(BASE_DIR, "static", "gallery")
    if os.path.exists(gallery_path):
        gallery = [f for f in os.listdir(gallery_path) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
    
    return render_template("faculty_dashboard.html", videos=videos, gallery=gallery)

@app.route("/student_dashboard")
def student_dashboard():
    if session.get("role") != "student":
        flash("Student access only", "danger")
        return redirect(url_for("login"))
    
    reg_no = session.get("reg_no")
    if not reg_no:
        flash("Please login first", "danger")
        return redirect(url_for("login"))
    
    # Get student details from database
    student = DATA_MANAGER.get_student(reg_no)
    
    # Prepare student details for template
    student_details = {
        'reg_no': reg_no,
        'full_name': student.get('name', '') if student else '',
        'department': student.get('dept', '') if student else '',
        'room_number': student.get('room_no', '') if student else '',
        'fathers_name': student.get('father_name', '') if student else '',
        'fathers_phone': student.get('father_phone', '') if student else ''
    }
    
    # Update session with latest details
    session['student_details'] = student_details

    # Get student photos (prefer static/photos first, fallback to student_photos folder)
    student_photos = {}
    photos_folder = os.path.join(os.path.dirname(__file__), 'static', 'photos')
    for side in ['front', 'left', 'right']:
        photo_path = os.path.join(photos_folder, f"{reg_no}_{side}.jpg")
        if os.path.exists(photo_path):
            student_photos[side] = f"/static/photos/{reg_no}_{side}.jpg"
        else:
            alt_path = os.path.join(STUDENT_PHOTOS_FOLDER, f"{reg_no}_{side}.jpg")
            if os.path.exists(alt_path):
                student_photos[side] = f"/student_photos/{reg_no}_{side}.jpg"

    return render_template("student_dashboard.html", 
                         student_details=student_details,
                         student_photos=student_photos)

@app.route("/upload_student_photos", methods=["POST"])
def upload_student_photos():
    if session.get("role") != "student":
        flash("Student access only", "danger")
        return redirect(url_for("login"))
    
    reg_no = session.get("reg_no")
    
    # Get the photos
    front_photo = request.files.get("front_photo")
    left_photo = request.files.get("left_photo")
    right_photo = request.files.get("right_photo")

    if not front_photo:
        flash("⚠ Front photo is required!", "danger")
        return redirect(url_for("student_dashboard"))

    # Save photos
    photos = save_student_photos(reg_no, front_photo, left_photo, right_photo)
    
    flash(f"✅ Photos uploaded successfully! {len(photos)} photo(s) saved.", "success")
    return redirect(url_for("student_dashboard"))

@app.route("/upload_photo", methods=["POST"]) 
def upload_photo():
    try:
        regno = request.form.get("regno")
        name = request.form.get("name")
        dept = request.form.get("dept")
        father_name = request.form.get("father_name")
        father_phno = request.form.get("father_phno")
        
        # Validate required fields
        if not regno or not name or not dept:
            flash("Registration number, name and department are required", "danger")
            return redirect(url_for("faculty_dashboard"))
            
        # Validate registration number format
        if not regno.isdigit() or len(regno) != 12:
            flash("Invalid registration number format", "danger")
            return redirect(url_for("faculty_dashboard"))
            
        # Get the photos
        front_photo = request.files.get("front_photo")
        left_photo = request.files.get("left_photo")
        right_photo = request.files.get("right_photo")

        if not front_photo:
            flash("Front photo is required", "danger") 
            return redirect(url_for("faculty_dashboard"))

        # Save photos
        photos = save_student_photos(regno, front_photo, left_photo, right_photo)

        # Save student data using data_manager
        success = DATA_MANAGER.update_student(regno, name, dept, "", father_name, father_phno)
        
        if success:
            flash(f"✅ Student {name} (Reg: {regno}) registered successfully", "success")
        else:
            flash("Failed to save student details", "danger")
            
    except Exception as e:
        print(f"Error registering student: {str(e)}")
        flash("An error occurred while registering student", "danger")
        
    return redirect(url_for("faculty_dashboard"))

@app.route("/upload_video", methods=["GET", "POST"])
def upload_video():
    print(f"DEBUG: upload_video called, method: {request.method}")
    print(f"DEBUG: session role: {session.get('role')}")
    
    if session.get("role") != "faculty":
        print("DEBUG: Not faculty, redirecting to login")
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
        
    if request.method == "POST":
        print("DEBUG: Processing POST request")
        try:
            print(f"DEBUG: Files in request: {list(request.files.keys())}")
            
            if "video" not in request.files:
                print("DEBUG: No video file in request")
                flash("No video file selected", "danger")
                return redirect(url_for("faculty_dashboard"))
            
            video = request.files["video"]
            print(f"DEBUG: Video filename: {video.filename}")
            
            if video.filename == "":
                print("DEBUG: Empty filename")
                flash("No video file selected", "danger")
                return redirect(url_for("faculty_dashboard"))
            
            # Check file extension
            allowed_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.MP4', '.AVI', '.MOV', '.MKV'}
            file_ext = os.path.splitext(video.filename)[1]
            print(f"DEBUG: File extension: {file_ext}")
            
            if file_ext not in allowed_extensions:
                print(f"DEBUG: Invalid file type: {file_ext}")
                flash(f"Invalid file type. Allowed: {', '.join(allowed_extensions)}", "danger")
                return redirect(url_for("faculty_dashboard"))
            
            if video:
                filename = secure_filename(video.filename)
                video_path = os.path.join(UPLOAD_FOLDER, filename)
                print(f"DEBUG: Saving to: {video_path}")
                
                # Ensure upload folder exists
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                print(f"DEBUG: Upload folder ensured: {UPLOAD_FOLDER}")
                
                # Save video
                video.save(video_path)
                print(f"DEBUG: Video saved, checking if exists: {os.path.exists(video_path)}")
                
                # Verify file was saved
                if os.path.exists(video_path):
                    print(f"DEBUG: File exists, redirecting to live video stream view")
                    flash(f"Video uploaded successfully: {filename}", "success")
                    # Open the interactive live view with green boxes overlaid while playing
                    return redirect(url_for("video_stream", filename=filename))
                else:
                    print("DEBUG: File not saved properly")
                    flash("Error: Video file was not saved properly", "danger")
                    return redirect(url_for("faculty_dashboard"))
            else:
                print("DEBUG: Invalid video file")
                flash("Error: Invalid video file", "danger")
                return redirect(url_for("faculty_dashboard"))
                
        except Exception as e:
            print(f"DEBUG: Exception occurred: {str(e)}")
            flash(f"Upload error: {str(e)}", "danger")
            return redirect(url_for("faculty_dashboard"))
    
    print("DEBUG: Returning upload template")
    return render_template("upload_video.html")

@app.route("/view_video/<path:filename>")
def view_video(filename):
    print(f"DEBUG: view_video called with filename: {filename}")
    print(f"DEBUG: session role: {session.get('role')}")
    
    if session.get("role") != "faculty":
        print("DEBUG: Not faculty, redirecting to login")
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
        
    try:
        video_path = os.path.join(UPLOAD_FOLDER, filename)
        print(f"DEBUG: Video path: {video_path}")
        
        if not os.path.exists(video_path):
            print("DEBUG: Video file not found")
            flash("Video file not found", "danger")
            return redirect(url_for("faculty_dashboard"))
        
        # Check if file is actually a video
        if not filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
            print("DEBUG: Invalid video file format")
            flash("Invalid video file format", "danger")
            return redirect(url_for("faculty_dashboard"))
        
        print("DEBUG: Starting video analysis...")
        
        # Process video for face recognition
        raw_faces = process_video_and_recognize(filename)
        print(f"DEBUG: Video analysis complete, found {len(raw_faces)} faces")

        if not raw_faces:
            print("DEBUG: No faces detected")
            flash("No faces detected in the video", "info")

        # Enrich raw results with student info expected by the template
        faces = []
        for f in raw_faces:
            reg = f.get('reg_no', 'UNKNOWN')
            student = get_student(reg) if reg != 'UNKNOWN' else None
            face_entry = {
                'reg': reg if reg else '-',
                'name': student['name'] if student else 'Unknown',
                'dept': student['dept'] if student else '',
                'father_name': student.get('father_name', '') if student else '',
                'father_phno': student.get('father_phno', '') if student else '',
                # frame: round timestamp (seconds) to nearest int for template display
                'frame': int(round(f.get('t', 0))),
                # pass box coords through (normalized 0..1)
                'x': f.get('x', 0),
                'y': f.get('y', 0),
                'w': f.get('w', 0),
                'h': f.get('h', 0),
                # precompute CSS style as percentages to avoid Jinja arithmetic
                'style': None,
                'score': f.get('score', 0.0)
            }
            try:
                fx = float(face_entry['x']) * 100
                fy = float(face_entry['y']) * 100
                fw = float(face_entry['w']) * 100
                fh = float(face_entry['h']) * 100
                face_entry['style'] = f"left: {fx:.2f}%; top: {fy:.2f}%; width: {fw:.2f}%; height: {fh:.2f}%;"
            except Exception:
                face_entry['style'] = "left: 0%; top: 0%; width: 0%; height: 0%;"
            faces.append(face_entry)

        print("DEBUG: Rendering view_video template")
        return render_template("view_video.html", video_file=filename, faces=faces)
        
    except Exception as e:
        print(f"DEBUG: Exception in view_video: {str(e)}")
        flash(f"Video analysis error: {str(e)}", "danger")
        return redirect(url_for("faculty_dashboard"))

@app.route("/static/uploads/<path:filename>")
def serve_uploaded_video(filename):
    """Serve uploaded video files"""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/student_photos/<path:filename>')
def serve_student_photo(filename):
    """Serve student photos saved in the `student_photos` folder."""
    try:
        return send_from_directory(STUDENT_PHOTOS_FOLDER, filename)
    except Exception as e:
        print(f"DEBUG: Error serving student photo {filename}: {e}")
        return ("Not Found", 404)

@app.route("/serve_upload/<path:filename>")
def serve_upload(filename):
    """Serve uploaded video files for video stream viewer"""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/api/tracks/<path:filename>")
def api_tracks(filename):
    """API endpoint to get face tracking data for video"""
    try:
        # Load analysis results from cache
        video_filename = os.path.basename(filename)
        results = load_analysis_cache(video_filename)
        
        if not results:
            print(f"DEBUG: No cached results for {video_filename}, processing video...")
            # Process the video if no cached results
            results = process_video_and_recognize(video_filename)
            
            if not results:
                print(f"DEBUG: No faces detected in {video_filename}, creating test data")
                # Create test data if no results found
                results = [
                    {
                        "t": 1.0,
                        "x": 0.25, "y": 0.17, "w": 0.19, "h": 0.33,
                        "reg_no": "UNKNOWN", "score": 0.5
                    },
                    {
                        "t": 1.0,
                        "x": 0.5, "y": 0.2, "w": 0.18, "h": 0.3,
                        "reg_no": "UNKNOWN", "score": 0.5
                    }
                ]
        
        # Convert results to the format expected by the frontend
        tracks = []
        for face in results:
            # Ensure we have the required fields
            if 't' in face and 'x' in face and 'y' in face and 'w' in face and 'h' in face:
                track = {
                    't': face['t'],
                    'x': face['x'],
                    'y': face['y'],
                    'w': face['w'],
                    'h': face['h'],
                    'reg_no': face.get('reg_no', 'UNKNOWN'),
                    'score': face.get('score', 0.5)
                }
                tracks.append(track)
            else:
                print(f"DEBUG: Skipping malformed face data: {face}")
        
        print(f"DEBUG: API returning {len(tracks)} tracks for {video_filename}")
        return jsonify(tracks)
        
    except Exception as e:
        print(f"Error in api_tracks: {e}")
        return jsonify([])


@app.route("/export_tracks/<path:filename>")
def export_tracks(filename):
    """Export tracked faces for a video as CSV. Columns: reg_no, name, uploaded, t, x, y, w, h, score"""
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))

    video_filename = os.path.basename(filename)
    results = load_analysis_cache(video_filename)
    if not results:
        # try processing if cache missing
        results = process_video_and_recognize(video_filename)

    # Prepare CSV in-memory
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["reg_no", "name", "uploaded", "t", "x", "y", "w", "h", "score"])

    for face in results:
        reg = face.get('reg_no', 'UNKNOWN')
        name = ''
        uploaded = 'No'
        if reg != 'UNKNOWN':
            student = DATA_MANAGER.get_student(reg)
            if student:
                uploaded = 'Yes'
                name = student.get('name', '')

        writer.writerow([
            reg,
            name,
            uploaded,
            face.get('t', ''),
            face.get('x', ''),
            face.get('y', ''),
            face.get('w', ''),
            face.get('h', ''),
            face.get('score', '')
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={os.path.splitext(video_filename)[0]}_tracks.csv"
    output.headers["Content-Type"] = "text/csv"
    return output

@app.route("/video_stream/<path:filename>")
def video_stream(filename):
    """Serve video stream viewer with real-time tracking"""
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    try:
        video_path = os.path.join(UPLOAD_FOLDER, filename)
        
        if not os.path.exists(video_path):
            flash("Video file not found", "danger")
            return redirect(url_for("faculty_dashboard"))
        
        # Get all students for the student map
        students = DATA_MANAGER.get_all_students()
        student_map = {}
        for student in students:
            student_map[student['reg_no']] = {
                'name': student['name'],
                'reg_no': student['reg_no'],
                'dept': student['dept'],
                'room_no': student.get('room_no', 'N/A'),
                'father_name': student.get('father_name', 'N/A'),
                'father_phone': student.get('father_phone', 'N/A')
            }
        
        return render_template("video_stream.html", filename=filename, student_map=student_map)
        
    except Exception as e:
        print(f"Error in video_stream: {e}")
        flash(f"Video stream error: {str(e)}", "danger")
        return redirect(url_for("faculty_dashboard"))

@app.route("/webcam")
def webcam():
    """Simple webcam viewer page."""
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    # Ensure encodings are loading — if not loaded yet, load synchronously
    if not KNOWN_HOLDER.get('loaded'):
        try:
            encs, regnos = load_known_faces()
            KNOWN_HOLDER['encodings'] = encs
            KNOWN_HOLDER['regnos'] = regnos
            KNOWN_HOLDER['loaded'] = True
            print(f"DEBUG: Synchronously loaded {len(encs)} known encodings for webcam page")
        except Exception as e:
            print(f"DEBUG: Failed to synchronously load encodings: {e}")

    return render_template("webcam_stream.html")

@app.route('/webcam_feed')
def webcam_feed():
    """MJPEG streaming response for the webcam."""
    if session.get("role") != "faculty":
        return ("Forbidden", 403)
    return app.response_class(generate_webcam_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/cctv', methods=['GET', 'POST'])
def cctv():
    """CCTV stream viewer - accepts RTSP/HTTP URL and renders a page with the stream."""
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))

    src = request.args.get('src')
    if request.method == 'POST':
        src = request.form.get('src')
        if not src:
            flash("Please enter a CCTV/RTSP URL", "danger")
            return redirect(url_for('cctv'))
        return redirect(url_for('cctv', src=src))

    return render_template('cctv_stream.html', src=src)

@app.route('/cctv_feed')
def cctv_feed():
    if session.get("role") != "faculty":
        return ("Forbidden", 403)
    src = request.args.get('src')
    if not src:
        return ("Missing src", 400)
    return app.response_class(generate_stream_frames(src), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/live_tracks')
def live_tracks():
    """Return latest live boxes for overlays. Params:
    - source=webcam | cctv, and if cctv then provide src=...
    """
    if session.get("role") not in ("faculty", "student"):
        return jsonify([])
    source = request.args.get('source', 'webcam')
    key = 'webcam'
    if source == 'cctv':
        src = request.args.get('src', '')
        key = f'cctv::{src}'
    data = LIVE_TRACKS.get(key, {'boxes': []})
    return jsonify(data.get('boxes', []))


@app.route('/encoding_status')
def encoding_status():
    """Return whether known face encodings have been loaded and how many."""
    return jsonify({
        'loaded': KNOWN_HOLDER.get('loaded', False),
        'count': len(KNOWN_HOLDER.get('encodings', []))
    })


@app.route('/debug_tracks')
def debug_tracks():
    """Return the entire LIVE_TRACKS structure for debugging."""
    return jsonify(LIVE_TRACKS)

# ---------------------- BRIGHTNESS CONTROL ----------------------
@app.route('/set_brightness', methods=['POST'])
def set_brightness():
    """Set brightness adjustment level (-50 to +50)"""
    global BRIGHTNESS_ADJUSTMENT
    try:
        data = request.get_json()
        brightness = int(data.get('brightness', 0))
        # Clamp value between -50 and +50
        BRIGHTNESS_ADJUSTMENT = max(-50, min(50, brightness))
        return jsonify({'success': True, 'brightness': BRIGHTNESS_ADJUSTMENT})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/get_brightness')
def get_brightness():
    """Get current brightness adjustment level"""
    return jsonify({'brightness': BRIGHTNESS_ADJUSTMENT})

@app.route("/process_video/<path:filename>")
def process_video_route(filename):
    """Manually trigger video processing for face detection"""
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    try:
        video_filename = os.path.basename(filename)
        video_path = os.path.join(UPLOAD_FOLDER, video_filename)
        
        if not os.path.exists(video_path):
            flash("Video file not found", "danger")
            return redirect(url_for("faculty_dashboard"))
        
        # Check if already processed
        cache_file = os.path.join(BASE_DIR, "track_cache", f"{video_filename}.json")
        if os.path.exists(cache_file):
            flash("Video already processed. Results available in cache.", "info")
        else:
            flash("Starting video processing for face detection...", "info")
            # Process the video
            results = process_video_and_recognize(video_filename)
            if results:
                flash(f"Video processed successfully! Found {len(results)} face detections.", "success")
            else:
                flash("Video processed but no faces detected.", "warning")
        
        return redirect(url_for("video_stream", filename=filename))
        
    except Exception as e:
        print(f"Error processing video: {e}")
        flash(f"Error processing video: {str(e)}", "danger")
        return redirect(url_for("faculty_dashboard"))

@app.route("/student/<regno>")
def student_profile(regno):
    student = get_student(regno)
    if not student:
        flash("Student not found", "danger")
        return redirect(url_for("faculty_dashboard"))
    
    # Get photo paths
    photos = {}
    for side in ['front', 'left', 'right']:
        photo_path = os.path.join(STUDENT_PHOTOS_FOLDER, f"{regno}_{side}.jpg")
        if os.path.exists(photo_path):
            photos[side] = f"../student_photos/{regno}_{side}.jpg"
    
    return render_template("student_profile.html", student=student, photos=photos)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    print(f"DEBUG: Serving video file: {filename}")
    print(f"DEBUG: Upload folder: {UPLOAD_FOLDER}")
    print(f"DEBUG: Full path: {os.path.join(UPLOAD_FOLDER, filename)}")
    print(f"DEBUG: File exists: {os.path.exists(os.path.join(UPLOAD_FOLDER, filename))}")
    
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        print(f"DEBUG: File not found: {file_path}")
        return "File not found", 404
    
    # Get file size for debugging
    file_size = os.path.getsize(file_path)
    print(f"DEBUG: File size: {file_size} bytes")
    
    # Set proper MIME type for video files
    response = send_from_directory(UPLOAD_FOLDER, filename)
    
    # Add headers for better video streaming support
    if filename.lower().endswith('.mp4'):
        response.headers['Content-Type'] = 'video/mp4'
        response.headers['Accept-Ranges'] = 'bytes'
    elif filename.lower().endswith('.avi'):
        response.headers['Content-Type'] = 'video/x-msvideo'
    elif filename.lower().endswith('.mov'):
        response.headers['Content-Type'] = 'video/quicktime'
    elif filename.lower().endswith('.mkv'):
        response.headers['Content-Type'] = 'video/x-matroska'
    
    return response

@app.route("/build_gallery", methods=["GET", "POST"])
def build_gallery():
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        reg_no = request.form.get("reg_no")
        clip = request.files.get("clip")
        
        if not reg_no or not clip:
            flash("Please provide registration number and video clip", "danger")
            return redirect(url_for("faculty_dashboard"))
        
        # Save to gallery folder
        gallery_path = os.path.join(BASE_DIR, "static", "gallery")
        os.makedirs(gallery_path, exist_ok=True)
        
        filename = f"{reg_no}.mp4"
        filepath = os.path.join(gallery_path, filename)
        clip.save(filepath)
        
        flash(f"Gait gallery clip created for {reg_no}", "success")
        return redirect(url_for("faculty_dashboard"))
    
    return render_template("build_gallery.html")

@app.route("/get_student_details/<reg_no>")
def get_student_details(reg_no):
    """API endpoint to fetch student details"""
    # Get student details from database
    student = DATA_MANAGER.get_student(reg_no)
    
    if student:
        details = {
            'full_name': student.get('name', ''),
            'department': student.get('dept', ''),
            'room_number': student.get('room_no', ''),
            'fathers_name': student.get('father_name', ''),
            'fathers_phone': student.get('father_phone', ''),
            'reg_no': reg_no  # Always include reg_no
        }
        # Update session with student details
        session['student_details'] = details
        return jsonify(details)
    
    # For new valid registration numbers
    if reg_no.startswith("99") and len(reg_no) == 11:
        return jsonify({'reg_no': reg_no})  # Return registration number for new registrations
    
    return jsonify({'error': 'Student not found'})

@app.route("/student_upload_details")
def student_upload_details():
    if session.get("role") != "student":
        flash("Student access only", "danger")
        return redirect(url_for("login"))
    
    reg_no = session.get("reg_no")
    if not reg_no:
        flash("Please login first", "danger")
        return redirect(url_for("login"))
    
    # Get existing student details if any
    student = DATA_MANAGER.get_student(reg_no)
    student_details = {
        'reg_no': reg_no,
        'full_name': student.get('name', '') if student else '',
        'department': student.get('dept', '') if student else '',
        'room_number': student.get('room_no', '') if student else '',
        'fathers_name': student.get('father_name', '') if student else '',
        'fathers_phone': student.get('father_phone', '') if student else ''
    }
    
    return render_template("student_upload_details.html", student_details=student_details)

@app.route("/update_student_details", methods=["POST"])
def update_student_details():
    # Get form data
    reg_no = request.form.get("reg_no")
    name = request.form.get("full_name")
    dept = request.form.get("department")
    room_no = request.form.get("room_number")
    father_name = request.form.get("fathers_name")
    father_phone = request.form.get("fathers_phone")
    
    # Check if any required fields are missing
    if not all([reg_no, name, dept]):
        flash("Name and department are required fields", "danger")
        return redirect(url_for("student_upload_details"))

    # Update student details in database
    success, message = DATA_MANAGER.update_student(
        reg_no=reg_no,
        name=name,
        dept=dept,
        room_no=room_no or "",
        father_name=father_name or "",
        father_phone=father_phone or ""
    )

    if success:
        # Store updated details in session
        session['student_details'] = {
            'reg_no': reg_no,
            'full_name': name,
            'department': dept,
            'room_number': room_no or "",
            'fathers_name': father_name or "",
            'fathers_phone': father_phone or ""
        }
        session['reg_no'] = reg_no  # Ensure reg_no is in session
        flash("✅ Student details updated successfully!", "success")
        return redirect(url_for("student_dashboard"))
    else:
        flash(message or "Failed to update student details", "danger")
        return redirect(url_for("student_upload_details"))

@app.route("/view_students")
def view_students():
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    # Get all students from data manager
    students = DATA_MANAGER.get_all_students()
    
    # Add photo information for each student
    for student in students:
        student['photos'] = {}
        for side in ['front', 'left', 'right']:
            photo_path = os.path.join(STUDENT_PHOTOS_FOLDER, f"{student['reg_no']}_{side}.jpg")
            if os.path.exists(photo_path):
                student['photos'][side] = f"../student_photos/{student['reg_no']}_{side}.jpg"
    
    return render_template("view_students.html", students=students)

@app.route("/student_management")
def student_management():
    if session.get("role") != "faculty":
        flash("Faculty access only", "danger")
        return redirect(url_for("login"))
    
    # Get statistics
    students = DATA_MANAGER.get_all_students()
    total_students = len(students)
    
    students_with_photos = 0
    for student in students:
        # Check if student has at least front photo
        front_photo_path = os.path.join(STUDENT_PHOTOS_FOLDER, f"{student['reg_no']}_front.jpg")
        if os.path.exists(front_photo_path):
            students_with_photos += 1
    
    return render_template("student_management.html", 
                         total_students=total_students, 
                         students_with_photos=students_with_photos)

@app.route("/debug/upload_test")
def debug_upload_test():
    """Debug route to test upload folder and permissions"""
    if session.get("role") != "faculty":
        return "Faculty access only", 403
    
    debug_info = {
        "upload_folder": UPLOAD_FOLDER,
        "upload_folder_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_folder_writable": os.access(UPLOAD_FOLDER, os.W_OK),
        "upload_folder_contents": [],
        "base_dir": BASE_DIR,
        "session": dict(session)
    }
    
    if os.path.exists(UPLOAD_FOLDER):
        try:
            debug_info["upload_folder_contents"] = os.listdir(UPLOAD_FOLDER)
        except Exception as e:
            debug_info["upload_folder_error"] = str(e)
    
    return jsonify(debug_info)

@app.route("/test")
def test_route():
    """Simple test route to check if system is working"""
    video_info = ""
    if os.path.exists(UPLOAD_FOLDER):
        for file in os.listdir(UPLOAD_FOLDER):
            if file.endswith(('.mp4', '.avi', '.mov', '.mkv')):
                file_path = os.path.join(UPLOAD_FOLDER, file)
                file_size = os.path.getsize(file_path)
                video_info += f"<p>📹 {file} - {file_size} bytes</p>"
    
    return f"""
    <h1>System Test</h1>
    <p>✅ Flask is working</p>
    <p>✅ UPLOAD_FOLDER: {UPLOAD_FOLDER}</p>
    <p>✅ UPLOAD_FOLDER exists: {os.path.exists(UPLOAD_FOLDER)}</p>
    <p>✅ Current working directory: {os.getcwd()}</p>
    <p>✅ Session: {dict(session)}</p>
    <p>✅ Upload folder contents: {os.listdir(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else 'Folder not found'}</p>
    {video_info}
    <p><a href="/faculty_dashboard">Go to Faculty Dashboard</a></p>
    <p><a href="/login">Go to Login</a></p>
    <p><a href="/uploads/press_meet.mp4">Test Video Direct Link</a></p>

    <video controls width="400">
        <source src="/uploads/press_meet.mp4" type="video/mp4">
        Your browser does not support the video tag.
    </video>
    """


# ---------------------- EXCEL DATASET MANAGEMENT ----------------------
@app.route("/export_students_excel")
def export_students_excel():
    """Export all students to Excel file"""
    if "reg_no" not in session or session.get("role") != "faculty":
        flash("Only faculty can export student data", "danger")
        return redirect(url_for("login"))
    
    try:
        # Create exports folder if not exists
        export_folder = os.path.join(BASE_DIR, "exports")
        os.makedirs(export_folder, exist_ok=True)
        
        # Generate Excel file
        filename = f"students_dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = os.path.join(export_folder, filename)
        
        success, message = DATA_MANAGER.export_students_to_excel(filepath)
        
        if success:
            return send_from_directory(export_folder, filename, as_attachment=True)
        else:
            flash(message, "danger")
            return redirect(url_for("student_management"))
    except Exception as e:
        flash(f"Error exporting Excel: {str(e)}", "danger")
        return redirect(url_for("student_management"))


@app.route("/import_students_excel", methods=["POST"])
def import_students_excel():
    """Import/Update students from Excel file"""
    if "reg_no" not in session or session.get("role") != "faculty":
        flash("Only faculty can import student data", "danger")
        return redirect(url_for("login"))
    
    try:
        if "excel_file" not in request.files:
            flash("No file selected", "danger")
            return redirect(url_for("student_management"))
        
        excel_file = request.files["excel_file"]
        
        if excel_file.filename == "":
            flash("No file selected", "danger")
            return redirect(url_for("student_management"))
        
        if not excel_file.filename.endswith(".xlsx"):
            flash("Please upload a .xlsx file", "danger")
            return redirect(url_for("student_management"))
        
        # Save uploaded file temporarily
        temp_folder = os.path.join(BASE_DIR, "temp")
        os.makedirs(temp_folder, exist_ok=True)
        temp_filepath = os.path.join(temp_folder, "temp_import.xlsx")
        excel_file.save(temp_filepath)
        
        # Import from Excel
        success, message = DATA_MANAGER.import_students_from_excel(temp_filepath)
        
        # Clean up temp file
        os.remove(temp_filepath)
        
        if success:
            flash(f"✓ {message}", "success")
        else:
            flash(f"✗ {message}", "danger")
        
        return redirect(url_for("student_management"))
    except Exception as e:
        flash(f"Error importing Excel: {str(e)}", "danger")
        return redirect(url_for("student_management"))


@app.route("/delete_student/<reg_no>", methods=["POST"])
def delete_student(reg_no):
    """Delete a student from dataset"""
    if "reg_no" not in session or session.get("role") != "faculty":
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    try:
        success, message = DATA_MANAGER.delete_student(reg_no)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/cleanup_students", methods=["POST"])
def cleanup_students():
    """Delete students and their photos who registered more than 4.5 years ago"""
    if "reg_no" not in session or session.get("role") != "faculty":
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    try:
        success, message = DATA_MANAGER.cleanup_old_students(STUDENT_PHOTOS_FOLDER)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ---------------------- MAIN ----------------------
if __name__ == "__main__":
    app.run(debug=True)