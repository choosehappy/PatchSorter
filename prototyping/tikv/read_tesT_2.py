import random
import time
from multiprocessing import Process, cpu_count
from tikv_client import RawClient


TIKV_ENDPOINTS = ["127.0.0.1:2379"]
TOTAL_IMAGES = 1_000_000
N_READS = 1000 * cpu_count()
N_PROCESSES = cpu_count()
BATCH_SIZE = 1024
KEY_PREFIX = "img_"


def generate_random_keys(n_reads):
    ids = random.sample(range(TOTAL_IMAGES), n_reads)
    return [f"{KEY_PREFIX}{i}".encode() for i in ids]


def worker(keys):
    client = RawClient.connect(TIKV_ENDPOINTS)
    bytes_fetched = 0
    i = 0
    while i < len(keys):
        batch = keys[i:i + BATCH_SIZE]
        result = {k: v for k, v in client.batch_get(batch)}
        # Count bytes fetched
        for v in result.values():
            if v is not None:
                bytes_fetched += len(v)
        missing = [k for k in batch if k not in result]
        if missing:
            print(f"Batch {i // BATCH_SIZE}: {len(missing)} missing keys")
        i += BATCH_SIZE
    return bytes_fetched



def main():
    keys = generate_random_keys(N_READS)
    # meilleure distribution (évite perte)
    chunks = [keys[i::N_PROCESSES] for i in range(N_PROCESSES)]
    from multiprocessing import Manager
    from multiprocessing import Queue
    import queue as pyqueue
    import multiprocessing
    manager = Manager()
    return_queue = manager.Queue()
    processes = []
    start_time = time.time()
    def worker_wrapper(chunk, return_queue):
        bytes_fetched = worker(chunk)
        return_queue.put(bytes_fetched)
    for chunk in chunks:
        if not chunk:
            continue
        p = Process(target=worker_wrapper, args=(chunk, return_queue))
        p.start()
        processes.append(p)
    total_bytes = 0
    for _ in processes:
        total_bytes += return_queue.get()
    for p in processes:
        p.join()
    duration = time.time() - start_time
    print(f"Read {len(keys)} images in {duration:.2f} seconds")
    print(f"Throughput: {len(keys)/duration:.2f} reads/sec")
    print(f"Data transferred: {total_bytes / 1024**2:.1f} MB  ({total_bytes / duration / 1024**2:.1f} MB/s)")


if __name__ == "__main__":
    main()