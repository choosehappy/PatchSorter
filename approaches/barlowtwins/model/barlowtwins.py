
#https://arxiv.org/pdf/2103.03230.pdf
#https://github.com/facebookresearch/barlowtwins

import torch
import torch.nn as nn
import torchvision.models as models


class Barlowtwins(nn.Module):

    def __init__(self, codesize=32, nclasses=2, lambd = 0.005):
        super(Barlowtwins, self).__init__()

        self.backbone = models.resnet18(pretrained=False, num_classes=codesize)
        dim_mlp = self.backbone.fc.in_features

        # add mlp projection head
        self.backbone.fc = nn.Sequential(nn.Linear(dim_mlp, dim_mlp), nn.ReLU(), self.backbone.fc)

        self.bn = nn.BatchNorm1d(codesize, affine=False)

        self.finalfc = nn.Sequential(nn.Linear(codesize, nclasses))

        self.lambd = lambd

    def features(self, x):
        return self.backbone(x)

    def loss(self, z1, z2):

        c = self.bn(z1).T @ self.bn(z2)

        # sum the cross-correlation matrix between all gpus
        c.div_(z1.shape[0])

        on_diag = torch.diagonal(c).add_(-1).pow_(2).sum()
        off_diag = self.off_diagonal(c).pow_(2).sum()
        loss = on_diag + self.lambd * off_diag
        return loss

    def forward_pred(self, x):
        x = self.bn(x)
        return self.finalfc(x)

    def off_diagonal(self,x):
        # return a flattened view of the off-diagonal elements of a square matrix
        n, m = x.shape
        assert n == m
        return x.flatten()[:-1].view(n - 1, n + 1)[:, 1:].flatten()