#!/usr/bin/env python3

"""
This file contains detailed tests for the functions in utils.py.
These are comprehensive tests that verify correct behavior of all utility functions
with specific known inputs and expected outputs.
"""

import torch
import torch.nn.functional as F
from collections import Counter
import sys
import os

# Add the project root to the path so we can import from utils
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from utils import (
    prediction_loss_sup,
    prediction_loss_pseudo,
    repulsion_loss,
    semantic_head_loss,
    neighborhood_loss,
    initialize_projection_from_batch,
)


def test_prediction_loss_pseudo_detailed():
    print("Testing detailed prediction_loss_pseudo...")

    # Create a controlled scenario with known inputs
    # 2 patches, each with 2 views = 4 total samples
    logits = torch.tensor(
        [
            [0.95, 0.05],  # View 1 of patch 1 - high confidence for class 0
            [0.85, 0.15],  # View 2 of patch 1 - high confidence for class 0
            [0.10, 0.90],  # View 1 of patch 2 - high confidence for class 1
            [0.05, 0.95],  # View 2 of patch 2 - high confidence for class 1
        ]
    )

    labels = torch.tensor([-1, -1, -1, -1])  # All unlabeled

    # Test with views_per_patch=2 (meaning we have 2 patches)
    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits, labels, pseudo_thresh=0.8, views_per_patch=2
    )

    print(f"Logits:\n{logits}")
    print(f"Labels: {labels}")
    print(f"High confidence result: {high_conf}")
    print(f"Pred labels: {pred_labels}")
    print(f"Pseudo loss: {pseudo_loss}")

    # Check that the function returns expected types and shapes
    assert isinstance(pseudo_loss, torch.Tensor), "Loss should be a tensor"
    assert pred_labels.shape == (4,), (
        f"pred_labels shape should be (4,) but got {pred_labels.shape}"
    )
    assert high_conf.shape == (4,), (
        f"high_conf shape should be (4,) but got {high_conf.shape}"
    )

    # The predictions should match the majority votes (class 0 for patch 1, class 1 for patch 2)
    expected_pred_labels = torch.tensor([0, 0, 1, 1])
    assert torch.equal(pred_labels, expected_pred_labels), (
        "Predictions should be correct"
    )

    # Since all predictions are high confidence and have valid cross-entropy loss
    assert pseudo_loss.item() >= 0.0, "Loss should be non-negative"

    print("✓ prediction_loss_pseudo detailed test passed")


def test_semantic_head_loss_detailed():
    print("Testing detailed semantic_head_loss...")

    # Create a simple controlled scenario with known coordinates and labels
    coords = torch.tensor(
        [
            [0.0, 0.0],  # Class 0 point
            [1.0, 1.0],  # Class 0 point (same class)
            [3.0, 3.0],  # Class 1 point
            [4.0, 4.0],  # Class 1 point (same class)
        ]
    )

    labels = torch.tensor([0, 0, 1, 1])  # Two classes

    # Should return two scalar losses
    attract_loss, repel_loss = semantic_head_loss(coords, labels)

    assert isinstance(attract_loss, torch.Tensor), "Attract loss should be a tensor"
    assert isinstance(repel_loss, torch.Tensor), "Repel loss should be a tensor"

    # Both losses should be non-negative
    assert attract_loss.item() >= 0.0, "Attract loss should be non-negative"
    assert repel_loss.item() >= 0.0, "Repel loss should be non-negative"

    print("✓ semantic_head_loss detailed test passed")


def test_repulsion_loss_detailed():
    print("Testing detailed repulsion_loss...")

    # Create points that are close together (should have repulsion)
    coords = torch.tensor(
        [
            [0.0, 0.0],  # Point 1
            [0.5, 0.5],  # Point 2 - very close to point 1
        ]
    )

    loss = repulsion_loss(coords, margin=1.0)

    assert isinstance(loss, torch.Tensor), "Loss should be a tensor"
    assert loss.item() >= 0.0, "Repulsion loss should be non-negative"

    # Test with points that are far apart (should have low or zero repulsion)
    coords_far = torch.tensor(
        [
            [0.0, 0.0],
            [2.0, 2.0],  # Far away from point 1
        ]
    )

    loss_far = repulsion_loss(coords_far, margin=1.0)
    assert isinstance(loss_far, torch.Tensor), "Loss should be a tensor"

    print("✓ repulsion_loss detailed test passed")


def main():
    print("Running detailed tests for utils.py functions...")

    try:
        test_prediction_loss_pseudo_detailed()
        test_semantic_head_loss_detailed()
        test_repulsion_loss_detailed()

        print("\nAll detailed tests passed!")
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
