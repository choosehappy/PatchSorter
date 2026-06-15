from __future__ import annotations

import cv2
import numpy as np
import albumentations as A
from albumentations.pytorch import ToTensorV2


class StainPerturbation(A.ImageOnlyTransform):
    """Macenko-style HE stain augmentation.

    Perturbs stain concentrations in optical-density space by scaling and
    shifting each stain channel independently.

    Args:
        sigma: Standard deviation of the multiplicative noise on stain concentrations.
        bias: Standard deviation of the additive noise on stain concentrations.
        p: Probability of applying the transform.
    """

    def __init__(self, sigma: float = 0.05, bias: float = 0.05, p: float = 0.8) -> None:
        super().__init__(p=p)
        self.sigma = sigma
        self.bias = bias

        self._HE = np.array(
            [[0.650, 0.072], [0.704, 0.990], [0.286, 0.105]], dtype=np.float32
        )
        self._HE_pinv = np.linalg.pinv(self._HE)

    def apply(self, img: np.ndarray, alpha: np.ndarray, beta: np.ndarray, **_) -> np.ndarray:
        img = img.astype(np.float32) * (1.0 / 255.0)
        np.clip(img, 1e-6, 1.0, out=img)

        H, W, _ = img.shape
        OD = -np.log(img).reshape(-1, 3)

        C = self._HE_pinv @ OD.T
        C[0] *= alpha[0]
        C[0] += beta[0]
        C[1] *= alpha[1]
        C[1] += beta[1]
        np.clip(C, 0, None, out=C)

        OD_aug = (self._HE @ C).T
        img_out = np.exp(-OD_aug).reshape(H, W, 3)
        np.clip(img_out, 0.0, 1.0, out=img_out)
        return (img_out * 255.0).astype(np.uint8)

    def get_params(self):
        return {
            "alpha": np.random.normal(1.0, self.sigma, 2).astype(np.float32),
            "beta": np.random.normal(0.0, self.bias, 2).astype(np.float32),
        }

    def get_transform_init_args_dict(self):
        return {"sigma": self.sigma, "bias": self.bias}


def get_transforms(patch_size: int) -> tuple[A.Compose, A.Compose]:
    """Build geometric and photometric albumentations pipelines for a given patch size.

    The geometric pipeline produces spatially consistent crops/flips/warps.
    The photometric pipeline applies colour/stain/noise augmentations and
    converts the result to a float32 ``torch.Tensor`` via ``ToTensorV2``.

    Args:
        patch_size: Spatial size of the square patch in pixels.

    Returns:
        Tuple of ``(geom_transforms, photo_transforms)``.
    """
    if patch_size <= 96:
        p = dict(
            crop_scale=(0.55, 1.0),
            crop_ratio=(0.90, 1.10),
            rotate_limit=20,
            rotate_p=0.5,
            elastic_alpha=5,
            elastic_sigma=4,
            elastic_p=0.35,
            grid_steps=3,
            grid_limit=0.12,
            grid_p=0.25,
            blur_limit=5,
            blur_p=0.5,
            iso_intensity=(0.05, 0.40),
            iso_color=(0.01, 0.06),
            jpeg_quality=60,
            stain_sigma=0.12,
            stain_bias=0.10,
            stain_p=0.9,
            dropout_holes=4,
            dropout_size=8,
            dropout_p=0.3,
            grayscale_p=0.15,
            brightness_limit=0.25,
            contrast_limit=0.25,
            gamma_limit=(70, 130),
            hsv_sat=30,
            hsv_val=25,
        )
    elif patch_size <= 192:
        p = dict(
            crop_scale=(0.45, 1.0),
            crop_ratio=(0.88, 1.12),
            rotate_limit=35,
            rotate_p=0.5,
            elastic_alpha=12,
            elastic_sigma=10,
            elastic_p=0.35,
            grid_steps=4,
            grid_limit=0.20,
            grid_p=0.3,
            blur_limit=7,
            blur_p=0.5,
            iso_intensity=(0.05, 0.35),
            iso_color=(0.01, 0.05),
            jpeg_quality=60,
            stain_sigma=0.12,
            stain_bias=0.10,
            stain_p=0.9,
            dropout_holes=6,
            dropout_size=16,
            dropout_p=0.3,
            grayscale_p=0.15,
            brightness_limit=0.25,
            contrast_limit=0.25,
            gamma_limit=(70, 130),
            hsv_sat=30,
            hsv_val=25,
        )
    else:
        p = dict(
            crop_scale=(0.35, 1.0),
            crop_ratio=(0.85, 1.15),
            rotate_limit=45,
            rotate_p=0.5,
            elastic_alpha=int(patch_size * 0.07),
            elastic_sigma=int(patch_size * 0.07),
            elastic_p=0.4,
            grid_steps=5,
            grid_limit=0.25,
            grid_p=0.3,
            blur_limit=9,
            blur_p=0.5,
            iso_intensity=(0.05, 0.40),
            iso_color=(0.01, 0.06),
            jpeg_quality=60,
            stain_sigma=0.12,
            stain_bias=0.10,
            stain_p=0.9,
            dropout_holes=8,
            dropout_size=32,
            dropout_p=0.3,
            grayscale_p=0.15,
            brightness_limit=0.25,
            contrast_limit=0.25,
            gamma_limit=(70, 130),
            hsv_sat=30,
            hsv_val=25,
        )

    geom_transforms = A.Compose(
        [
            A.RandomResizedCrop(
                size=(patch_size, patch_size),
                scale=p["crop_scale"],
                ratio=p["crop_ratio"],
                interpolation=cv2.INTER_LINEAR,
                p=1.0,
            ),
            A.RandomRotate90(p=0.5),
            A.Rotate(
                limit=p["rotate_limit"],
                border_mode=cv2.BORDER_REFLECT,
                p=p["rotate_p"],
            ),
            A.VerticalFlip(p=0.5),
            A.HorizontalFlip(p=0.5),
            A.ElasticTransform(
                alpha=p["elastic_alpha"],
                sigma=p["elastic_sigma"],
                p=p["elastic_p"],
            ),
            A.GridDistortion(
                num_steps=p["grid_steps"],
                distort_limit=p["grid_limit"],
                border_mode=cv2.BORDER_REFLECT,
                p=p["grid_p"],
            ),
        ]
    )

    photo_transforms = A.Compose(
        [
            StainPerturbation(sigma=p["stain_sigma"], bias=p["stain_bias"], p=p["stain_p"]),
            A.ToGray(p=p["grayscale_p"]),
            A.OneOf(
                [
                    A.MedianBlur(blur_limit=p["blur_limit"], p=1.0),
                    A.GaussianBlur(blur_limit=(3, p["blur_limit"]), p=1.0),
                    A.MotionBlur(blur_limit=p["blur_limit"], p=1.0),
                ],
                p=p["blur_p"],
            ),
            A.ISONoise(intensity=p["iso_intensity"], color_shift=p["iso_color"], p=0.4),
            A.RandomBrightnessContrast(
                brightness_limit=(-p["brightness_limit"], p["brightness_limit"]),
                contrast_limit=(-p["contrast_limit"], p["contrast_limit"]),
                brightness_by_max=False,
                p=0.6,
            ),
            A.RandomGamma(gamma_limit=p["gamma_limit"], p=0.5),
            A.HueSaturationValue(
                hue_shift_limit=0,
                sat_shift_limit=p["hsv_sat"],
                val_shift_limit=p["hsv_val"],
                p=0.5,
            ),
            A.ImageCompression(quality_lower=p["jpeg_quality"], quality_upper=100, p=0.3),
            A.CoarseDropout(
                max_holes=p["dropout_holes"],
                max_height=p["dropout_size"],
                max_width=p["dropout_size"],
                min_holes=1,
                fill_value=0,
                p=p["dropout_p"],
            ),
            ToTensorV2(),
        ]
    )

    return geom_transforms, photo_transforms
