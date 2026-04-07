import requests
import os

BASE_DIR = r"c:\Users\lalit\OneDrive\Desktop\CAPSTONE PROJECT CCTV"
test_image_path = os.path.join(BASE_DIR, "student_photos", "9924037023_front.jpg")

if not os.path.exists(test_image_path):
    print("Test image not found.")
    exit(1)

# We will just test the internal python function directly instead of mocking a multi-part form request to simplify
import sys
sys.path.append(BASE_DIR)
import app

# Mock the cache array size before
print(f"Before cache length: {len(app.KNOWN_HOLDER['encodings'])}")

# Call the append function
success = app.append_new_face_to_cache("9924037023", test_image_path)
print(f"Append success: {success}")

# Check length after
print(f"After cache length: {len(app.KNOWN_HOLDER['encodings'])}")
