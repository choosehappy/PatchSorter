"""pytest fixtures and configuration"""

import torch
import pytest


@pytest.fixture
def sample_logits():
    """Provide sample logits for testing"""
    return torch.randn(4, 3)


@pytest.fixture
def sample_labels():
    """Provide sample labels for testing"""
    return torch.tensor([-1, -1, -1, -1])


@pytest.fixture
def sample_coords():
    """Provide sample coordinates for testing"""
    return torch.randn(5, 2)


@pytest.fixture
def sample_embeddings():
    """Provide sample embeddings for testing"""
    return torch.randn(3, 5, 10)
