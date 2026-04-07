#!/usr/bin/env python3
"""
Test script for face detection functionality
"""

import os
import sys
import cv2
import face_recognition
import numpy as np

# Use script directory as base so tests work regardless of cwd
BASE_DIR = os.path.dirname(__file__)

def test_face_detection():
    """Test basic face detection functionality"""
    print("Testing face detection functionality...")
    
    # Check if student_photos folder exists
    student_photos_folder = os.path.join(BASE_DIR, "student_photos")
    if not os.path.exists(student_photos_folder):
        print(f"❌ Student photos folder '{student_photos_folder}' not found")
        return False
    
    # Check if there are any student photos
    photo_files = [f for f in os.listdir(student_photos_folder) if f.endswith(('.jpg', '.jpeg', '.png'))]
    if not photo_files:
        print(f"❌ No student photos found in '{student_photos_folder}'")
        return False
    
    print(f"✅ Found {len(photo_files)} student photos")
    
    # Test loading known faces
    try:
        known_encodings, known_regnos = [], []
        
        for file in photo_files:
            if file.endswith((".jpg", ".jpeg", ".png")):
                regno = file.split("_")[0]
                image_path = os.path.join(student_photos_folder, file)
                print(f"  Processing {file} for student {regno}")
                
                image = face_recognition.load_image_file(image_path)
                encs = face_recognition.face_encodings(image)
                if encs:
                    known_encodings.append(encs[0])
                    known_regnos.append(regno)
                    print(f"    ✅ Face encoding extracted for {regno}")
                else:
                    print(f"    ⚠️  No face detected in {file}")
        
        print(f"✅ Successfully loaded {len(known_encodings)} face encodings")
        
        if len(known_encodings) > 0:
            print("✅ Face detection system is working properly!")
            return True
        else:
            print("❌ No face encodings could be extracted")
            return False
            
    except Exception as e:
        print(f"❌ Error during face detection test: {e}")
        return False

def test_video_processing():
    """Test video processing functionality"""
    print("\nTesting video processing functionality...")
    
    # Check if uploads folder exists
    uploads_folder = os.path.join(BASE_DIR, "static", "uploads")
    if not os.path.exists(uploads_folder):
        print(f"❌ Uploads folder '{uploads_folder}' not found")
        return False
    
    # Check if there are any video files
    video_files = [f for f in os.listdir(uploads_folder) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
    if not video_files:
        print(f"⚠️  No video files found in '{uploads_folder}'")
        print("   Upload a video file to test video processing")
        return False
    
    print(f"✅ Found {len(video_files)} video files")
    
    # Check if track_cache folder exists
    track_cache_folder = os.path.join(BASE_DIR, "track_cache")
    if not os.path.exists(track_cache_folder):
        print(f"⚠️  Track cache folder '{track_cache_folder}' not found")
        print("   This will be created when videos are processed")
    else:
        cache_files = [f for f in os.listdir(track_cache_folder) if f.endswith('.json')]
        print(f"✅ Found {len(cache_files)} cached analysis results")
    
    return True

def main():
    """Main test function"""
    print("=" * 50)
    print("CCTV Face Detection System - Test Suite")
    print("=" * 50)
    
    # Test face detection
    face_detection_ok = test_face_detection()
    
    # Test video processing
    video_processing_ok = test_video_processing()
    
    print("\n" + "=" * 50)
    print("Test Results Summary:")
    print("=" * 50)
    
    if face_detection_ok:
        print("✅ Face Detection: WORKING")
    else:
        print("❌ Face Detection: FAILED")
    
    if video_processing_ok:
        print("✅ Video Processing: READY")
    else:
        print("❌ Video Processing: ISSUES DETECTED")
    
    print("\nNext Steps:")
    if face_detection_ok:
        print("1. Upload a video file through the faculty dashboard")
        print("2. Click 'Process' to analyze the video for faces")
        print("3. View the results in 'Live View' mode")
        print("4. Hover over green boxes to see student information")
        print("5. Click on registration numbers to view student profiles")
    else:
        print("1. Ensure student photos are uploaded to student_photos/ folder")
        print("2. Check that photos contain clear, front-facing faces")
        print("3. Verify face_recognition library is properly installed")
    
    print("=" * 50)

if __name__ == "__main__":
    main()
