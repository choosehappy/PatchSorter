from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
import timm


class JointHead(nn.Module):
    """Shared embedding + 2D projection + classification head.

    Args:
        in_dim: Dimensionality of backbone output features.
        hidden_dim: Width of hidden layers in the MLP.
        embed_dim: Output dimensionality of the shared embedding.
        proj_dim: Dimensionality of the 2D projection (typically 2).
        num_classes: Number of output classes for the prediction head.
        grid_size: Upper bound of the projection grid (coordinates clamped to [0, grid_size]).
    """

    def __init__(
        self,
        in_dim: int,
        hidden_dim: int,
        embed_dim: int,
        proj_dim: int,
        num_classes: int,
        grid_size: float,
    ) -> None:
        super().__init__()
        self.grid_size = grid_size

        self.shared_fc = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embed_dim),
            nn.BatchNorm1d(embed_dim),
        )

        self.proj_fc = nn.Sequential(
            nn.Linear(embed_dim, proj_dim),
            nn.Hardtanh(min_val=0.0, max_val=grid_size),
        )

        self.pred_fc = nn.Linear(embed_dim, num_classes)

        self._init_weights()

    def _init_weights(self) -> None:
        nn.init.uniform_(self.proj_fc[0].weight, -1.0, 1.0)
        nn.init.uniform_(self.proj_fc[0].bias, 0.0, self.grid_size)

    def forward(self, z: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            z: Backbone features of shape ``[B, in_dim]``.

        Returns:
            Tuple of ``(embedding, coords, logits)`` where:
            - ``embedding`` is ``[B, embed_dim]``
            - ``coords`` is ``[B, proj_dim]`` with values in ``[0, grid_size]``
            - ``logits`` is ``[B, num_classes]``
        """
        shared = self.shared_fc(z)
        proj = self.proj_fc(shared)
        logits = self.pred_fc(shared)
        return shared, proj, logits


def backbone_init(patch_size: int) -> tuple[nn.Module, int]:
    """Create a MobileNetV3-small-050 backbone and return it with its feature dim.

    Args:
        patch_size: Spatial size of input patches (used to determine feature dim).

    Returns:
        Tuple of ``(backbone, feature_dim)``.
    """
    backbone = timm.create_model(
        "mobilenetv3_small_050",
        pretrained=True,
        features_only=False,
        num_classes=0,
    )
    with torch.no_grad():
        dummy = torch.zeros(1, 3, patch_size, patch_size)
        feature_dim = backbone(dummy).shape[-1]
    return backbone, feature_dim
