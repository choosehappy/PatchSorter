from torch import nn
import torch

class Autoencoder(nn.Module):
    def __init__(self, nclasses=2, codesize=32):
        super(Autoencoder, self).__init__()

        self.encoder = nn.Sequential(
            nn.Conv2d(3, 6, kernel_size=3),
            nn.ReLU(True),
            nn.BatchNorm2d(6),
            nn.Conv2d(6, 8, stride=2, kernel_size=3),
            nn.ReLU(True),
            nn.BatchNorm2d(8),
            nn.Conv2d(8, 8, stride=2, kernel_size=3),
            nn.ReLU(True),
            nn.BatchNorm2d(8),
            nn.AdaptiveAvgPool2d((6, 6)))

        self.fc = nn.Sequential(
            nn.Linear(8 * 6 * 6, codesize),
            nn.ReLU(True),
            nn.Linear(codesize, codesize),
            nn.ReLU(True)
        )

        self.classifier = nn.Sequential(
            nn.Linear(codesize, nclasses)
        )

        self.lin2conv = nn.Sequential(
            nn.Linear(codesize, 8 * 6 * 6),
            nn.ReLU(True),
        )

        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(8, 8, kernel_size=4, stride=2),
            nn.ReLU(True),
            nn.BatchNorm2d(8),
            nn.ConvTranspose2d(8, 6, kernel_size=4, stride=2),
            nn.ReLU(True),
            nn.BatchNorm2d(6),
            nn.ConvTranspose2d(6, 3, kernel_size=3),
            nn.ReLU(True),
            nn.BatchNorm2d(3),
            nn.Sigmoid())

    def features(self, x):
        x = self.encoder(x)
        x = torch.flatten(x, 1)
        x = self.fc(x)
        return x

    def vec2img(self, x):
        x = self.lin2conv(x)
        x = x.view(-1, 8, 6, 6)
        x = self.decoder(x)
        return x

    def vec2class(self, x):
        x = self.classifier(x)
        return x

    def forward(self, x):
        x = self.encoder(x)
        x = torch.flatten(x, 1)
        x = self.fc(x)
        x = self.lin2conv(x)
        x = x.view(-1, 8, 6, 6)

        x = self.decoder(x)
        return x