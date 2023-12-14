import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models


class Simclr(nn.Module):

    def __init__(self, codesize=32, nclasses=2):
        super(Simclr, self).__init__()

        self.backbone = models.resnet18(pretrained=False, num_classes=codesize)
        dim_mlp = self.backbone.fc.in_features

        # add mlp projection head
        self.backbone.fc = nn.Sequential(nn.Linear(dim_mlp, dim_mlp), nn.ReLU(), self.backbone.fc)

        self.finalfc = nn.Sequential(nn.Linear(codesize, nclasses))

    def forward(self, x):
        return self.backbone(x)

    def forward_pred(self, x):
        return self.finalfc(x)

    def features(self,x):
        return self.backbone(x)


def info_nce_loss(features,device,temperature,n_views=2):
    npatches=int(features.shape[0] / n_views)
    labels = torch.cat([torch.arange(npatches) for i in range(n_views)], dim=0)
    labels = (labels.unsqueeze(0) == labels.unsqueeze(1)).float()
    labels = labels.to(device)

    features = F.normalize(features, dim=1)

    similarity_matrix = torch.matmul(features, features.T)

    # discard the main diagonal from both: labels and similarities matrix
    mask = torch.eye(labels.shape[0], dtype=torch.bool).to(device)
    labels = labels[~mask].view(labels.shape[0], -1)
    similarity_matrix = similarity_matrix[~mask].view(similarity_matrix.shape[0], -1)
    # assert similarity_matrix.shape == labels.shape

    # select and combine multiple positives
    positives = similarity_matrix[labels.bool()].view(labels.shape[0], -1)

    # select only the negatives the negatives
    negatives = similarity_matrix[~labels.bool()].view(similarity_matrix.shape[0], -1)

    logits = torch.cat([positives, negatives], dim=1)
    labels = torch.zeros(logits.shape[0], dtype=torch.long).to(device)

    logits = logits / temperature
    return logits, labels