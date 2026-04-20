import io
import time
import numpy as np
from multiprocessing import Process, cpu_count, Value
from tikv_client import RawClient
from PIL import Image
from tqdm import tqdm

TIKV_ENDPOINTS = ["127.0.0.1:2379"]
TOTAL_IMAGES = 80_000
IMAGE_SIZE = (64, 64, 3)
N_PROCESSES = cpu_count()


def generate_jpeg_bytes():
    arr = np.random.randint(0, 256, IMAGE_SIZE, dtype=np.uint8)
    img = Image.fromarray(arr)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def worker(start_idx, n_images, counter):
    client = RawClient.connect(TIKV_ENDPOINTS)

    value = generate_jpeg_bytes()

    local_count = 0
    for i in range(n_images):
        key = f"img_{start_idx + i}".encode()
        client.put(key, value)

        local_count += 1

        # réduire contention: update par batch
        if local_count % 100 == 0:
            with counter.get_lock():
                counter.value += 100

    # flush restant
    remaining = local_count % 100
    if remaining:
        with counter.get_lock():
            counter.value += remaining


def main():
    images_per_proc = TOTAL_IMAGES // N_PROCESSES
    processes = []

    counter = Value('i', 0)

    start_time = time.time()

    for i in range(N_PROCESSES):
        start_idx = i * images_per_proc
        p = Process(target=worker, args=(start_idx, images_per_proc, counter))
        p.start()
        processes.append(p)

    # tqdm dans le process principal
    with tqdm(total=TOTAL_IMAGES) as pbar:
        last = 0
        while any(p.is_alive() for p in processes):
            current = counter.value
            pbar.update(current - last)
            last = current
            time.sleep(0.1)

        # update final
        current = counter.value
        pbar.update(current - last)

    for p in processes:
        p.join()

    duration = time.time() - start_time

    print(f"Inserted {TOTAL_IMAGES} images in {duration:.2f} seconds")
    print(f"Throughput: {TOTAL_IMAGES / duration:.2f} images/sec")


if __name__ == "__main__":
    main()