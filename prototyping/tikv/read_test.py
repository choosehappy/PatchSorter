import random
import time
from multiprocessing import Process, cpu_count
from tikv_client import RawClient

TIKV_ENDPOINTS = ["127.0.0.1:2379"]

TOTAL_IMAGES = 1_000_000
N_READS = 100_024
N_PROCESSES = cpu_count()


def generate_random_keys(n_reads):
    ids = random.sample(range(TOTAL_IMAGES), n_reads)
    return [f"img_{i}".encode() for i in ids]


def worker(keys):
    client = RawClient.connect(TIKV_ENDPOINTS)

    for k in keys:
        _ = client.get(k)


def main():
    keys = generate_random_keys(N_READS)

    reads_per_proc = len(keys) // N_PROCESSES
    processes = []

    start_time = time.time()

    for i in range(N_PROCESSES):
        chunk = keys[i * reads_per_proc:(i + 1) * reads_per_proc]
        if not chunk:
            continue

        p = Process(target=worker, args=(chunk,))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    duration = time.time() - start_time

    print(f"Read {len(keys)} images in {duration:.2f} seconds")
    print(f"Throughput: {len(keys)/duration:.2f} reads/sec")


if __name__ == "__main__":
    main()