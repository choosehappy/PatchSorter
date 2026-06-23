import os
import shutil
import numpy as np
import zarr
import time

zarr_path = "/opt/PatchSorter/prototyping/agent_benchmarks/patch_array_benchmark.zarr"
num_patches = 1_000_000  # 1M patches (representative of large dataset)
patch_shape = (32, 32, 3)
dtype = "uint8"
batch_size = 10_000

try:
    # Cleanup any existing array
    if os.path.exists(zarr_path):
        shutil.rmtree(zarr_path)

    os.makedirs(os.path.dirname(zarr_path), exist_ok=True)

    # Create and seed Zarr array
    print("Creating Zarr array...")
    z = zarr.open(
        zarr_path,
        mode="w",
        shape=(num_patches,) + patch_shape,
        chunks=(1024,) + patch_shape,
        dtype=dtype,
    )

    # Seed in batches of 10k
    print("Seeding data...")
    seed_batch = 10_000
    for i in range(0, num_patches, seed_batch):
        end = min(i + seed_batch, num_patches)
        z[i:end] = np.random.randint(
            0, 256, size=(end - i,) + patch_shape, dtype=np.uint8
        )
    print("Seeding complete.")

    # Randomly sample batch_size patch_ids
    rng = np.random.default_rng(42)
    patch_ids = rng.choice(num_patches, size=batch_size, replace=False)
    patch_ids_sorted = np.sort(patch_ids)  # sort for better IO locality

    # Warm up (optional small read)
    _ = z[0]

    # Time the batch read
    print(f"Reading batch of {batch_size} patches...")
    start = time.perf_counter()
    # Use numpy advanced indexing instead of get_coordinate_selection
    batch = z[patch_ids_sorted]
    elapsed = time.perf_counter() - start

    throughput = batch_size / elapsed
    print(f"RESULT: Elapsed={elapsed:.3f}s, Throughput={throughput:,.0f} r/s")
    print(f"Batch shape: {batch.shape}")

except Exception as e:
    print(f"ERROR: {e}")
    raise
finally:
    # Cleanup
    if os.path.exists(zarr_path):
        shutil.rmtree(zarr_path)
        print("Zarr array cleaned up.")
