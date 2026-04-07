import os
import numpy as np

BASE_DIR = r"c:\Users\lalit\OneDrive\Desktop\CAPSTONE PROJECT CCTV"
cache_path = os.path.join(BASE_DIR, 'encodings_cache.npz')

if os.path.exists(cache_path):
    npz = np.load(cache_path, allow_pickle=True)
    encs = npz['encodings']
    regnos = npz['regnos']
    print(f"Loaded {len(encs)} encodings")
    
    unique_regnos = set(regnos)
    print(f"Unique regnos: {len(unique_regnos)}")
    print(f"List: {sorted(list(unique_regnos))}")
else:
    print("Cache file does not exist")
