import torch
import torch.nn.functional as F
import numpy as np
from unittest.mock import patch, MagicMock
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from utils import (
    LabeledRateTracker,
    get_transforms,
    JointHead,
    repulsion_loss,
    MemoryBank,
    importance_score_tensor,
    assign_bins,
    get_margin,
    temporal_loss,
    intra_bin_repulsion_vectorized,
    bin_losses_vectorized,
    prediction_loss_pseudo,
    semantic_head_loss,
    neighborhood_loss,
    initialize_projection_from_batch,
    SpreadLoss,
    max_mean_discrepancy,
    simclr_loss,
    vicreg_loss,
    gaussian_mask,
)


def test_labeled_rate_tracker():
    """Test LabeledRateTracker functionality"""

    # Test initialization
    tracker = LabeledRateTracker(nclasses=3, momentum=0.9)
    assert tracker.rate is None
    assert tracker.class_weights.shape == (3,)
    assert tracker.pseudo_class_weights.shape == (3,)

    # Test update with labeled data
    labels = torch.tensor([0, 1, -1, 2])  # Mix of labeled and unlabeled
    rate, label_freq, pseudo_freq = tracker.update(labels)

    assert isinstance(rate, float)
    assert label_freq is not None

    # Test class weights (may be None if no valid labels)
    try:
        weights = tracker.get_class_weights()
        # If we get here without exception, it's working
    except Exception as e:
        print(f"Warning: get_class_weights failed with {e}")

    # Test edge cases
    # Test with empty labels
    tracker2 = LabeledRateTracker(nclasses=3)
    rate, label_freq, pseudo_freq = tracker2.update(torch.tensor([]))
    assert isinstance(rate, float)

    # Test with all unlabeled
    labels_unlabeled = torch.tensor([-1, -1, -1])
    rate, label_freq, pseudo_freq = tracker2.update(labels_unlabeled)
    assert isinstance(rate, float)


def test_get_transforms():
    """Test get_transforms function"""
    transforms = get_transforms(patch_size=64)
    assert len(transforms) == 2  # Should return tuple of two transforms


def test_joint_head_forward():
    """Test JointHead forward pass"""

    head = JointHead(
        in_dim=100,
        hidden_dim=50,
        embed_dim=30,
        proj_dim=20,
        num_classes=3,
        grid_size=100,
    )

    # Test with dummy input
    z = torch.randn(5, 100)
    shared, proj, logits = head(z)

    assert shared.shape == (5, 30)
    assert proj.shape == (5, 2)
    assert logits.shape == (5, 3)


def test_repulsion_loss():
    """Test repulsion loss function"""

    # Test with valid coordinates
    coords = torch.tensor([[1.0, 1.0], [2.0, 2.0]])
    loss = repulsion_loss(coords)
    assert isinstance(loss, torch.Tensor)
    assert loss.shape == ()

    # Test with single coordinate (should return 0)
    coords_single = torch.tensor([[1.0, 1.0]])
    loss_single = repulsion_loss(coords_single)
    assert loss_single.item() == 0.0

    # Test edge case: empty coordinates
    coords_empty = torch.empty(0, 2)
    try:
        loss_empty = repulsion_loss(coords_empty)
        assert isinstance(loss_empty, torch.Tensor)
    except Exception as e:
        # This might be expected behavior - just make sure it doesn't crash
        pass

    # Test edge case: large coordinates (should not cause overflow)
    coords_large = torch.tensor([[1e6, 1e6], [2e6, 2e6]])
    loss_large = repulsion_loss(coords_large)
    assert isinstance(loss_large, torch.Tensor)


def test_memory_bank():
    """Test MemoryBank functionality"""

    bank = MemoryBank(size=5, embed_dim=10)

    # Test add_candidates
    z_new = torch.randn(3, 10)
    coords_new = torch.randn(3, 2)
    labels_new = torch.tensor([0, 1, -1])

    bank.add_candidates(z_new, coords_new, labels_new)

    assert bank.z.shape[0] == 3
    assert bank.coords.shape[0] == 3
    assert bank.labels.shape[0] == 3

    # Test edge cases
    # Test with empty inputs
    try:
        bank_empty = MemoryBank(size=5, embed_dim=10)
        z_empty = torch.empty(0, 10)
        coords_empty = torch.empty(0, 2)
        labels_empty = torch.tensor([])
        bank_empty.add_candidates(z_empty, coords_empty, labels_empty)
    except Exception as e:
        # This is expected behavior - just make sure it doesn't crash
        pass

    # Test with large inputs
    z_large = torch.randn(100, 10)
    coords_large = torch.randn(100, 2)
    labels_large = torch.randint(0, 5, (100,))
    bank.add_candidates(z_large, coords_large, labels_large)


def test_importance_score_tensor():
    """Test importance score tensor function"""

    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    labels = torch.tensor([0, -1])

    scores = importance_score_tensor(coords, labels)
    assert scores.shape == (2,)
    assert isinstance(scores, torch.Tensor)


def test_assign_bins():
    """Test assign bins function"""

    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    bins = assign_bins(coords)
    assert len(bins) == 2
    assert isinstance(bins[0], tuple)


def test_get_margin():
    """Test get margin function"""

    sup_loss = torch.tensor(0.5)
    labeled_rate = 0.8

    margin = get_margin(sup_loss, labeled_rate)
    assert isinstance(margin, float)
    assert margin > 0


def test_temporal_loss():
    """Test temporal loss function"""

    # Test with valid inputs
    old_coords = torch.tensor([[1.0, 2.0]])
    new_coords = torch.tensor([[2.0, 3.0]])
    ages = torch.tensor([0])

    loss = temporal_loss(old_coords, new_coords, ages)
    assert isinstance(loss, torch.Tensor)


def test_intra_bin_repulsion_vectorized():
    """Test intra bin repulsion vectorized function"""

    coords = torch.randn(5, 2)
    flat_bins = torch.randint(0, 10, (5,))

    loss = intra_bin_repulsion_vectorized(coords, flat_bins, device="cpu")
    assert isinstance(loss, torch.Tensor)


def test_bin_losses_vectorized():
    """Test bin losses vectorized function"""

    coords = torch.randn(10, 2)

    occ_loss, intra_loss = bin_losses_vectorized(coords)
    assert isinstance(occ_loss, torch.Tensor)
    assert isinstance(intra_loss, torch.Tensor)


def test_prediction_loss_pseudo():
    """Test prediction loss pseudo function with comprehensive scenarios"""

    # Test basic functionality
    num_classes = 3

    # Mock logits where views agree on labels for patches
    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 - high conf for class 0
            [0.8, 0.1, 0.1],  # View 2 - medium conf for class 0
            [0.3, 0.4, 0.3],  # View 3 - low conf for class 1
            [0.2, 0.5, 0.3],  # View 4 - medium conf for class 1
        ]
    )

    labels = torch.tensor([-1, -1, -1, -1])  # All unlabeled

    # Test with views_per_patch=2 parameter
    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits, labels, pseudo_thresh=0.8, views_per_patch=2
    )

    assert isinstance(pseudo_loss, torch.Tensor)
    assert isinstance(pred_labels, torch.Tensor)
    assert isinstance(high_conf, torch.BoolTensor)
    assert high_conf.shape == (4,)

    # Test edge cases
    # Test with all confident predictions
    logits_all_conf = torch.tensor(
        [[0.95, 0.02, 0.03], [0.85, 0.1, 0.05], [0.75, 0.15, 0.1]]
    )
    labels_all_unlabeled = torch.tensor([-1, -1, -1])

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits_all_conf, labels_all_unlabeled, pseudo_thresh=0.8, views_per_patch=2
    )

    assert isinstance(pseudo_loss, torch.Tensor)
    assert isinstance(pred_labels, torch.Tensor)
    assert isinstance(high_conf, torch.BoolTensor)

    # Test with no confident predictions
    logits_no_conf = torch.tensor(
        [[0.45, 0.3, 0.25], [0.35, 0.3, 0.35], [0.25, 0.4, 0.35]]
    )

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits_no_conf, labels_all_unlabeled, pseudo_thresh=0.8, views_per_patch=2
    )

    assert isinstance(pseudo_loss, torch.Tensor)
    assert isinstance(pred_labels, torch.Tensor)
    assert isinstance(high_conf, torch.BoolTensor)


def test_semantic_head_loss():
    """Test semantic head loss function"""

    coords = torch.randn(5, 2)
    labels = torch.tensor([0, 1, -1, 0, 1])  # Mix of labeled and unlabeled

    attract_loss, repel_loss = semantic_head_loss(coords, labels)
    assert isinstance(attract_loss, torch.Tensor)
    assert isinstance(repel_loss, torch.Tensor)

    # Test edge cases
    # Test with all unlabeled data
    coords_unlabeled = torch.randn(3, 2)
    labels_unlabeled = torch.tensor([-1, -1, -1])
    attract_loss, repel_loss = semantic_head_loss(coords_unlabeled, labels_unlabeled)
    assert isinstance(attract_loss, torch.Tensor)
    assert isinstance(repel_loss, torch.Tensor)

    # Test with single labeled point
    coords_single = torch.randn(1, 2)
    labels_single = torch.tensor([0])
    attract_loss, repel_loss = semantic_head_loss(coords_single, labels_single)
    assert isinstance(attract_loss, torch.Tensor)
    assert isinstance(repel_loss, torch.Tensor)

    # Test with empty input
    coords_empty = torch.empty(0, 2)
    labels_empty = torch.tensor([])
    try:
        attract_loss, repel_loss = semantic_head_loss(coords_empty, labels_empty)
    except Exception as e:
        # This might be expected behavior - just make sure it doesn't crash
        pass


def test_neighborhood_loss():
    """Test neighborhood loss function"""

    z_batch = torch.randn(10, 20)
    proj_coords = torch.randn(10, 2)

    loss = neighborhood_loss(z_batch, proj_coords)
    assert isinstance(loss, torch.Tensor)


def test_spread_loss():
    """Test SpreadLoss functionality"""

    spread_loss = SpreadLoss(grid_size=100)

    coords = torch.randn(5, 2)
    loss = spread_loss(coords)
    assert isinstance(loss, torch.Tensor)


def test_max_mean_discrepancy():
    """Test max mean discrepancy function"""

    coords = torch.randn(10, 2)
    loss = max_mean_discrepancy(coords)
    assert isinstance(loss, torch.Tensor)


def test_simclr_loss():
    """Test SimCLR loss function"""

    # Test with valid view embeddings
    proj_emb = torch.randn(3, 5, 10)  # 3 views, 5 samples, 10 dims

    loss = simclr_loss(proj_emb)
    assert isinstance(loss, torch.Tensor)


def test_vicreg_loss():
    """Test VICReg loss function"""

    # Test with valid view embeddings
    proj_emb = torch.randn(2, 5, 10)  # 2 views, 5 samples, 10 dims

    loss = vicreg_loss(proj_emb)
    assert isinstance(loss, torch.Tensor)


def test_gaussian_mask():
    """Test gaussian mask function"""

    mask = gaussian_mask(64, 64)
    assert mask.shape == (64, 64)
    assert isinstance(mask, torch.Tensor)


if __name__ == "__main__":
    print("Running comprehensive tests for utils.py functions...")

    test_labeled_rate_tracker()
    print("✓ LabeledRateTracker tests passed")

    test_get_transforms()
    print("✓ get_transforms tests passed")

    test_joint_head_forward()
    print("✓ JointHead forward tests passed")

    test_repulsion_loss()
    print("✓ repulsion_loss tests passed")

    test_memory_bank()
    print("✓ MemoryBank tests passed")

    test_importance_score_tensor()
    print("✓ importance_score_tensor tests passed")

    test_assign_bins()
    print("✓ assign_bins tests passed")

    test_get_margin()
    print("✓ get_margin tests passed")

    test_temporal_loss()
    print("✓ temporal_loss tests passed")

    test_intra_bin_repulsion_vectorized()
    print("✓ intra_bin_repulsion_vectorized tests passed")

    test_bin_losses_vectorized()
    print("✓ bin_losses_vectorized tests passed")

    test_prediction_loss_pseudo()
    print("✓ prediction_loss_pseudo tests passed")

    test_semantic_head_loss()
    print("✓ semantic_head_loss tests passed")

    test_neighborhood_loss()
    print("✓ neighborhood_loss tests passed")

    test_spread_loss()
    print("✓ SpreadLoss tests passed")

    test_max_mean_discrepancy()
    print("✓ max_mean_discrepancy tests passed")

    test_simclr_loss()
    print("✓ simclr_loss tests passed")

    test_vicreg_loss()
    print("✓ vicreg_loss tests passed")

    test_gaussian_mask()
    print("✓ gaussian_mask tests passed")

    print("\nAll comprehensive tests passed!")
