import io
import time
import uuid
import numpy as np
from multiprocessing import Process, cpu_count
from tikv_client import RawClient
from PIL import Image

TIKV_ENDPOINTS = ["127.0.0.1:2379"]
TOTAL_IMAGES = 80_000 #1_000_000
IMAGE_SIZE = (64, 64, 3)
N_PROCESSES = cpu_count()  # ou fixe, ex: 8


def generate_jpeg_bytes():
    arr = np.random.randint(0, 256, IMAGE_SIZE, dtype=np.uint8)
    img = Image.fromarray(arr)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def worker(start_idx, n_images):
    client = RawClient.connect(TIKV_ENDPOINTS)

    value = generate_jpeg_bytes()
    
    for i in range(n_images):
        key = f"img_{start_idx + i}".encode()
        #value = generate_jpeg_bytes()
        client.put(key, value)


def main():
    images_per_proc = TOTAL_IMAGES // N_PROCESSES
    processes = []

    start_time = time.time()

    for i in range(N_PROCESSES):
        start_idx = i * images_per_proc
        p = Process(target=worker, args=(start_idx, images_per_proc))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    end_time = time.time()
    duration = end_time - start_time

    print(f"Inserted {TOTAL_IMAGES} images in {duration:.2f} seconds")
    print(f"Throughput: {TOTAL_IMAGES / duration:.2f} images/sec")


if __name__ == "__main__":
    main()

