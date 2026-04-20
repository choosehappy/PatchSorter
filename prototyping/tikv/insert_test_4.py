import io
import time
import numpy as np
from multiprocessing import Process, cpu_count, Value
from tikv_client import RawClient
from PIL import Image
from tqdm import tqdm

TIKV_ENDPOINTS = ["127.0.0.1:2379"]

TOTAL_IMAGES = 1_000_000
IMAGE_SIZE = (64, 64, 3)
N_PROCESSES = cpu_count()
BATCH_SIZE = 64

def generate_jpeg_bytes():
    arr = np.random.randint(0, 256, IMAGE_SIZE, dtype=np.uint8)
    img = Image.fromarray(arr)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def worker(start_idx, n_images, counter):
    client = RawClient.connect(TIKV_ENDPOINTS)

    i = 0
    while i < n_images:
        batch = {}

        for _ in range(BATCH_SIZE):
            if i >= n_images:
                break

            key = f"img_{start_idx + i}".encode()
            value = generate_jpeg_bytes()

            batch[key] = value
            i += 1

        remaining = dict(batch)
        for _ in range(3):
            client.batch_put(remaining)
            result = {k for k, v in client.batch_get(list(remaining.keys()))}
            remaining = {k: v for k, v in remaining.items() if k not in result}
            if not remaining:
                break

        with counter.get_lock():
            counter.value += len(batch)


def main():
    images_per_proc = TOTAL_IMAGES // N_PROCESSES
    remainder = TOTAL_IMAGES % N_PROCESSES
    processes = []

    counter = Value('i', 0)

    start_time = time.time()

    for i in range(N_PROCESSES):
        start_idx = i * images_per_proc
        n_imgs = images_per_proc + (remainder if i == N_PROCESSES - 1 else 0)
        p = Process(target=worker, args=(start_idx, n_imgs, counter))
        p.start()
        processes.append(p) 

    with tqdm(total=TOTAL_IMAGES) as pbar:
        last = 0
        while any(p.is_alive() for p in processes):
            current = counter.value
            pbar.update(current - last)
            last = current
            time.sleep(0.1)

        current = counter.value
        pbar.update(current - last)

    for p in processes:
        p.join()

    duration = time.time() - start_time

    print(f"Inserted {TOTAL_IMAGES} images in {duration:.2f} seconds")
    print(f"Throughput: {TOTAL_IMAGES / duration:.2f} images/sec")


if __name__ == "__main__":
    main()
