import os
import face_recognition
import numpy as np

BASE_DIR = r"c:\Users\lalit\OneDrive\Desktop\CAPSTONE PROJECT CCTV"
STUDENT_PHOTOS_FOLDER = os.path.join(BASE_DIR, "student_photos")
PHOTO_FOLDER = os.path.join(BASE_DIR, "static", "photos")

known_encodings, known_regnos = [], []

print("Scanning student_photos...")
for file in os.listdir(STUDENT_PHOTOS_FOLDER):
    if file.lower().endswith((".jpg", ".jpeg", ".png")):
        regno = file.split("_")[0]
        image_path = os.path.join(STUDENT_PHOTOS_FOLDER, file)
        try:
            print(f"Processing {file}...", flush=True)
            image = face_recognition.load_image_file(image_path)
            encs = face_recognition.face_encodings(image)
            if encs and len(encs) > 0:
                known_encodings.append(encs[0])
                known_regnos.append(regno)
        except Exception as e:
            print(f"Error on {file}: {e}", flush=True)

print(f"Total valid encodings found: {len(known_encodings)}")

if len(known_encodings) > 0:
    cache_path = os.path.join(BASE_DIR, 'encodings_cache.npz')
    enc_array = np.array(known_encodings)
    reg_array = np.array(known_regnos, dtype=object)
    np.savez_compressed(cache_path, encodings=enc_array, regnos=reg_array)
    print(f"Successfully saved {len(known_encodings)} encodings to {cache_path}")
else:
    print("No faces found to cache.")
