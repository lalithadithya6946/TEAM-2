import os
import sys
import face_recognition

STUDENT_PHOTOS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "student_photos")

if not os.path.exists(STUDENT_PHOTOS_FOLDER):
    print("Folder does not exist")
    sys.exit(1)

files = [f for f in os.listdir(STUDENT_PHOTOS_FOLDER) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
print(f"Total photos found: {len(files)}")

students = set()
for f in files:
    students.add(f.split('_')[0])
    
print(f"Total unique students: {len(students)}")

known_encodings, known_regnos = [], []
processed, valid = 0, 0

for file in files:
    processed += 1
    regno = file.split("_")[0]
    image_path = os.path.join(STUDENT_PHOTOS_FOLDER, file)
    try:
        image = face_recognition.load_image_file(image_path)
        encs = face_recognition.face_encodings(image)
        if encs:
            known_encodings.append(encs[0])
            known_regnos.append(regno)
            valid += 1
            if valid <= 5: 
                print(f"DEBUG: Encoded {file} -> {regno}")
        else:
            print(f"DEBUG: No face found in {file}")
            
    except Exception as e:
        print(f"DEBUG: Error processing {image_path}: {e}")
        
    if processed % 10 == 0:
        print(f"Processed {processed}/{len(files)}, Valid: {valid}")

print(f"\nFinal count: {len(known_encodings)} encodings loaded from {len(files)} files.")
