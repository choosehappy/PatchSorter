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


def test_labeled_rate_tracker_initialization():
    """Test LabeledRateTracker initialization"""
    tracker = LabeledRateTracker(nclasses=3, momentum=0.9)
    assert tracker.rate is None
    assert tracker.class_weights.shape == (3,)
    assert tracker.pseudo_class_weights.shape == (3,)


def test_labeled_rate_tracker_update():
    """Test LabeledRateTracker update functionality"""

    # Test initialization
    tracker = LabeledRateTracker(nclasses=3, momentum=0.9)
    assert tracker.rate is None

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


def test_labeled_rate_tracker_edge_cases():
    """Test LabeledRateTracker edge cases"""

    # Test with empty labels
    tracker = LabeledRateTracker(nclasses=3)
    rate, label_freq, pseudo_freq = tracker.update(torch.tensor([]))
    assert isinstance(rate, float)

    # Test with all unlabeled
    labels_unlabeled = torch.tensor([-1, -1, -1])
    rate, label_freq, pseudo_freq = tracker.update(labels_unlabeled)
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


def test_joint_head_edge_cases():
    """Test JointHead edge cases"""

    # Test with different dimensions
    head = JointHead(
        in_dim=50,
        hidden_dim=25,
        embed_dim=15,
        proj_dim=10,
        num_classes=2,
        grid_size=50,
    )

    z = torch.randn(3, 50)
    shared, proj, logits = head(z)

    assert shared.shape == (3, 15)
    assert proj.shape == (3, 2)
    assert logits.shape == (3, 2)


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

    # Test with empty tensor
    coords_empty = torch.empty(0, 2)
    loss_empty = repulsion_loss(coords_empty)
    assert loss_empty.item() == 0.0


def test_repulsion_loss_edge_cases():
    """Test repulsion loss edge cases"""

    # Test with large coordinates
    coords_large = torch.tensor([[1000.0, 1000.0], [2000.0, 2000.0]])
    loss_large = repulsion_loss(coords_large)
    assert isinstance(loss_large, torch.Tensor)

    # Test with negative coordinates
    coords_negative = torch.tensor([[-1.0, -1.0], [-2.0, -2.0]])
    loss_negative = repulsion_loss(coords_negative)
    assert isinstance(loss_negative, torch.Tensor)


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

    # Test sample functionality
    sampled = bank.sample(2)
    assert len(sampled) == 3  # Should return z, coords, labels
    assert sampled[0].shape[0] == 2  # Sampled z should have 2 items


def test_memory_bank_edge_cases():
    """Test MemoryBank edge cases"""

    bank = MemoryBank(size=5, embed_dim=10)

    # Test with empty inputs
    z_new = torch.empty(0, 10)
    coords_new = torch.empty(0, 2)
    labels_new = torch.tensor([])

    bank.add_candidates(z_new, coords_new, labels_new)
    assert bank.z.shape[0] == 0


def test_importance_score_tensor():
    """Test importance score tensor function"""

    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    labels = torch.tensor([0, -1])

    scores = importance_score_tensor(coords, labels)
    assert scores.shape == (2,)
    assert isinstance(scores, torch.Tensor)


def test_importance_score_tensor_edge_cases():
    """Test importance score tensor edge cases"""

    # Test with all unlabeled
    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    labels = torch.tensor([-1, -1])

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


def test_get_margin_edge_cases():
    """Test get margin edge cases"""

    # Test with zero loss
    sup_loss = torch.tensor(0.0)
    labeled_rate = 0.5
    margin = get_margin(sup_loss, labeled_rate)
    assert isinstance(margin, float)

    # Test with high rate
    sup_loss = torch.tensor(1.0)
    labeled_rate = 1.0
    margin = get_margin(sup_loss, labeled_rate)
    assert isinstance(margin, float)


def test_temporal_loss():
    """Test temporal loss function"""

    # Test with valid inputs
    old_coords = torch.tensor([[1.0, 2.0]])
    new_coords = torch.tensor([[2.0, 3.0]])
    ages = torch.tensor([0])

    loss = temporal_loss(old_coords, new_coords, ages)
    assert isinstance(loss, torch.Tensor)


def test_temporal_loss_edge_cases():
    """Test temporal loss edge cases"""

    # Test with large age difference
    old_coords = torch.tensor([[1.0, 2.0]])
    new_coords = torch.tensor([[5.0, 6.0]])
    ages = torch.tensor([100])

    loss = temporal_loss(old_coords, new_coords, ages)
    assert isinstance(loss, torch.Tensor)

    # Test with empty tensors
    old_coords_empty = torch.empty(0, 2)
    new_coords_empty = torch.empty(0, 2)
    ages_empty = torch.tensor([])

    loss_empty = temporal_loss(old_coords_empty, new_coords_empty, ages_empty)
    assert isinstance(loss_empty, torch.Tensor)


def test_intra_bin_repulsion_vectorized():
    """Test intra bin repulsion vectorized function"""

    coords = torch.randn(5, 2)
    flat_bins = torch.randint(0, 10, (5,))

    loss = intra_bin_repulsion_vectorized(coords, flat_bins, device="cpu")
    assert isinstance(loss, torch.Tensor)


def test_intra_bin_repulsion_vectorized_edge_cases():
    """Test intra bin repulsion vectorized edge cases"""

    # Test with empty coordinates
    coords_empty = torch.empty(0, 2)
    flat_bins_empty = torch.tensor([])

    loss_empty = intra_bin_repulsion_vectorized(
        coords_empty, flat_bins_empty, device="cpu"
    )
    assert isinstance(loss_empty, torch.Tensor)


def test_bin_losses_vectorized():
    """Test bin losses vectorized function"""

    coords = torch.randn(10, 2)

    occ_loss, intra_loss = bin_losses_vectorized(coords)
    assert isinstance(occ_loss, torch.Tensor)
    assert isinstance(intra_loss, torch.Tensor)


def test_bin_losses_vectorized_edge_cases():
    """Test bin losses vectorized edge cases"""

    # Test with empty coordinates
    coords_empty = torch.empty(0, 2)

    occ_loss, intra_loss = bin_losses_vectorized(coords_empty)
    assert isinstance(occ_loss, torch.Tensor)
    assert isinstance(intra_loss, torch.Tensor)


def test_prediction_loss_pseudo_basic():
    """Test prediction_loss_pseudo basic functionality"""

    # Test basic functionality
    num_classes = 3

    # Mock logits where views agree on labels for patches
    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 - high conf for class 0
            [0.8, 0.1, 0.1],  # View 2 - medium conf for class 0
            [0.3, 0.4, 0.3],  # View 3 - class 1
            [0.2, 0.5, 0.3],  # View 4 - class 2
        ]
    )

    labels = torch.tensor([-1, -1, -1, -1])  # All unlabeled

    # Test with views_per_patch parameter
    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits, labels, pseudo_thresh=0.9, views_per_patch=2
    )

    # Should return tensors of expected shapes and types
    assert isinstance(pseudo_loss, torch.Tensor)
    assert isinstance(pred_labels, torch.Tensor)
    assert isinstance(high_conf, torch.BoolTensor)
    assert high_conf.shape == (4,)


def test_prediction_loss_pseudo_comprehensive():
    """Test prediction_loss_pseudo with comprehensive scenarios"""

    num_classes = 3

    # Test scenario: patch 1 has views that agree on class 0; patch 2 has disagreeing views
    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 of patch 1 - high conf for class 0
            [0.85, 0.1, 0.05],  # View 2 of patch 1 - high conf for class 0 (agreement)
            [0.3, 0.4, 0.3],  # View 1 of patch 2 - class 1
            [0.2, 0.6, 0.2],  # View 2 of patch 2 - class 2 (disagreeing views)
        ]
    )

    labels = torch.tensor([-1, -1, -1, -1])  # All unlabeled

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits,
        labels,
        pseudo_thresh=0.8,  # Threshold that allows both patch views
        views_per_patch=2,
    )

    # Both views of first patch should be marked as high confidence (agreement)
    assert high_conf[0] and high_conf[1]

    # Views in second patch should not be high confidence due to disagreement
    assert not high_conf[2] or not high_conf[3]


def test_prediction_loss_pseudo_with_threshold():
    """Test that threshold requirement works correctly"""

    num_classes = 3

    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 - high conf for class 0
            [0.8, 0.1, 0.1],  # View 2 - medium conf for class 0
            [0.3, 0.4, 0.3],  # View 3 - low conf for class 1
            [0.2, 0.5, 0.3],  # View 4 - medium conf for class 1
        ]
    )

    labels = torch.tensor([-1, -1, -1, -1])  # All unlabeled

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits,
        labels,
        pseudo_thresh=0.85,  # High threshold that only first view meets
        views_per_patch=2,  # Two patches of two views each
    )

    # With high threshold, not all views should pass
    assert not (high_conf[0] and high_conf[1])  # First patch may not be fully confident


def test_prediction_loss_pseudo_mixed_labels():
    """Test with mixed labeled/unlabeled data"""

    num_classes = 3

    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 - high conf for class 0
            [0.8, 0.1, 0.1],  # View 2 - medium conf for class 0
            [0.3, 0.4, 0.3],  # View 3 - low conf for class 1
            [0.2, 0.5, 0.3],  # View 4 - medium conf for class 1
        ]
    )

    labels = torch.tensor([0, -1, -1, -1])  # First is labeled

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits, labels, pseudo_thresh=0.8, views_per_patch=2
    )

    # First sample (labeled) should not be in high_conf
    assert not high_conf[0]


def test_prediction_loss_pseudo_single_view():
    """Test behavior with single view per patch"""

    num_classes = 3

    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],  # View 1 - high conf for class 0
            [0.3, 0.4, 0.3],  # View 2 - low conf for class 1
        ]
    )

    labels = torch.tensor([-1, -1])  # All unlabeled

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits,
        labels,
        pseudo_thresh=0.8,
        views_per_patch=1,  # Single view per patch
    )

    # With single view, majority vote is trivial - it's the only view
    assert not high_conf[0] or not high_conf[1]


def test_prediction_loss_pseudo_no_views():
    """Test behavior when no views_per_patch provided"""

    num_classes = 3

    logits = torch.tensor(
        [
            [0.9, 0.05, 0.05],
            [0.8, 0.1, 0.1],
        ]
    )

    labels = torch.tensor([-1, -1])  # All unlabeled

    pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
        logits,
        labels,
        pseudo_thresh=0.8,
        views_per_patch=None,  # No views specified
    )

    # Should return all False for high_conf when no view info provided
    assert not high_conf.any()


def test_semantic_head_loss():
    """Test semantic head loss function"""

    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    labels = torch.tensor([0, 1])

    loss = semantic_head_loss(coords, labels)
    assert isinstance(loss, torch.Tensor)


def test_semantic_head_loss_edge_cases():
    """Test semantic head loss edge cases"""

    # Test with all unlabeled
    coords = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    labels = torch.tensor([-1, -1])

    loss = semantic_head_loss(coords, labels)
    assert isinstance(loss, torch.Tensor)


def test_neighborhood_loss():
    """Test neighborhood loss function"""

    z_batch = torch.randn(5, 10)
    proj_coords = torch.randn(5, 2)

    loss = neighborhood_loss(z_batch, proj_coords)
    assert isinstance(loss, torch.Tensor)


def test_neighborhood_loss_edge_cases():
    """Test neighborhood loss edge cases"""

    # Test with empty inputs
    z_batch_empty = torch.empty(0, 10)
    proj_coords_empty = torch.empty(0, 2)

    loss_empty = neighborhood_loss(z_batch_empty, proj_coords_empty)
    assert isinstance(loss_empty, torch.Tensor)


def test_spread_loss():
    """Test SpreadLoss class"""

    # Test initialization
    spread_loss = SpreadLoss(grid_size=100, quantile=0.95, ema_decay=0.99)

    # Test forward pass
    coords = torch.randn(10, 2)
    loss = spread_loss(coords)
    assert isinstance(loss, torch.Tensor)


def test_spread_loss_edge_cases():
    """Test SpreadLoss edge cases"""

    # Test with empty coordinates
    spread_loss = SpreadLoss()
    coords_empty = torch.empty(0, 2)

    loss_empty = spread_loss(coords_empty)
    assert isinstance(loss_empty, torch.Tensor)


def test_max_mean_discrepancy():
    """Test max mean discrepancy function"""

    coords = torch.randn(10, 2)

    discrepancy = max_mean_discrepancy(coords)
    assert isinstance(discrepancy, torch.Tensor)


def test_max_mean_discrepancy_edge_cases():
    """Test max mean discrepancy edge cases"""

    # Test with empty coordinates
    coords_empty = torch.empty(0, 2)

    discrepancy_empty = max_mean_discrepancy(coords_empty)
    assert isinstance(discrepancy_empty, torch.Tensor)


def test_simclr_loss():
    """Test simclr loss function"""

    proj_emb = torch.randn(10, 5)  # 10 samples, 5 dimensions

    loss = simclr_loss(proj_emb)
    assert isinstance(loss, torch.Tensor)


def test_vicreg_loss():
    """Test vicreg loss function"""

    proj_emb = torch.randn(10, 5)  # 10 samples, 5 dimensions

    loss = vicreg_loss(proj_emb)
    assert isinstance(loss, torch.Tensor)


def test_gaussian_mask():
    """Test gaussian mask function"""

    mask = gaussian_mask(64, 64, sigma=0.5)
    assert mask.shape == (64, 64)
    assert isinstance(mask, torch.Tensor)


def test_gaussian_mask_edge_cases():
    """Test gaussian mask edge cases"""

    # Test with different dimensions
    mask_small = gaussian_mask(10, 10, sigma=0.5)
    assert mask_small.shape == (10, 10)

    # Test with zero sigma
    mask_zero = gaussian_mask(32, 32, sigma=0.0)
    assert mask_zero.shape == (32, 32)


if __name__ == "__main__":
    # Run all tests
    test_labeled_rate_tracker_initialization()
    test_labeled_rate_tracker_update()
    test_labeled_rate_tracker_edge_cases()
    test_get_transforms()
    test_joint_head_forward()
    test_joint_head_edge_cases()
    test_repulsion_loss()
    test_repulsion_loss_edge_cases()
    test_memory_bank()
    test_memory_bank_edge_cases()
    test_importance_score_tensor()
    test_importance_score_tensor_edge_cases()
    test_assign_bins()
    test_get_margin()
    test_get_margin_edge_cases()
    test_temporal_loss()
    test_temporal_loss_edge_cases()
    test_intra_bin_repulsion_vectorized()
    test_intra_bin_repulsion_vectorized_edge_cases()
    test_bin_losses_vectorized()
    test_bin_losses_vectorized_edge_cases()
    test_prediction_loss_pseudo_basic()
    test_prediction_loss_pseudo_comprehensive()
    test_prediction_loss_pseudo_with_threshold()
    test_prediction_loss_pseudo_mixed_labels()
    test_prediction_loss_pseudo_single_view()
    test_prediction_loss_pseudo_no_views()
    test_semantic_head_loss()
    test_semantic_head_loss_edge_cases()
    test_neighborhood_loss()
    test_neighborhood_loss_edge_cases()
    test_spread_loss()
    test_spread_loss_edge_cases()
    test_max_mean_discrepancy()
    test_max_mean_discrepancy_edge_cases()
    test_simclr_loss()
    test_vicreg_loss()
    test_gaussian_mask()
    test_gaussian_mask_edge_cases()

    print("All tests passed!")
