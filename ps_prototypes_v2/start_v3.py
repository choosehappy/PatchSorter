# %%
import torch
import torch.nn.functional as F
from albumentations.pytorch import ToTensorV2
from torchvision.transforms.functional import center_crop
from tqdm import tqdm
from torch.utils.tensorboard import SummaryWriter
import logging

from utils import *
from patch_logging import *
import timm
from configs import *
from db_writer import SQLiteWriter
import atexit

import tables


class Dataset(object):
    def __init__(self, fname, nviews, transforms=None):
        self.fname = fname

        self.geom_transform, self.photo_transform = (
            transforms if transforms else (None, None)
        )

        with tables.open_file(self.fname, "r") as db:
            self.nitems = db.root.patch.shape[0]

        self.imgs = None
        self.labels = None
        self.nviews = nviews

    def __getitem__(self, index):
        with tables.open_file(self.fname, "r") as db:
            self.imgs = db.root.patch
            self.labels = db.root.tmp_label  # ps_label has all the data - here we're using just a random set created  in a noteobok

            # get the requested image and mask from the pytable
            img = self.imgs[index, :, :, :]
            label = self.labels[index]

        img_new = img

        if self.geom_transform:
            geom_out = self.geom_transform(image=img_new)
            img_geom = geom_out["image"]
            anchor = ToTensorV2()(image=img_geom)["image"]

            if self.photo_transform:
                
                views = tuple(
                    self.photo_transform(image=self.geom_transform(image=img_new)["image"])["image"]
                    for _ in range(self.nviews - 1)
                )
                return (anchor, *views, label, img,index)

        else:
            print("no aug?")
            return img_new, label, img, index

    def __len__(self):
        return self.nitems


# Initialize dataset with proper parameters
dataset = Dataset(
    "mitosis_ps_labels.pytable", nviews=NVIEWS, transforms=get_transforms(PATCH_SIZE)
)


dataloader = DataLoader(
    InfiniteDataset(dataset),
    batch_size=BATCH_SIZE,
    shuffle=False,
    #num_workers=64,
    num_workers=8,
    pin_memory=True,
    drop_last=True,
    persistent_workers=True,
    prefetch_factor=4, #UNCOMMENT
)
# prefetcher = cuda_prefetc[her(dataloader)
vram_prefetcher = threaded_vram_prefetcher(dataloader, buffer_size=4) #UNCOMMENT
#vram_prefetcher = dataloader


#
# ------------------------


import matplotlib.pyplot as plt
import math

# obtenir un batch
batch_data = next(iter(dataloader))
*views, batch_labels, original_imgs, ids = batch_data
batch_imgs = views[0]

import torchvision.utils as vutils


def visualize_batch(batch_imgs, original_imgs, nrow=10, ntot=50):
    batch_imgs = batch_imgs[:ntot]
    original_imgs = original_imgs[:ntot].permute(
        0, 3, 1, 2
    )  # (B, H, W, C) -> (B, C, H, W)

    batch_grid = vutils.make_grid(batch_imgs, nrow=nrow, padding=2)
    original_grid = vutils.make_grid(original_imgs, nrow=nrow, padding=2)

    batch_np = batch_grid.permute(1, 2, 0).cpu().numpy()
    original_np = original_grid.permute(1, 2, 0).cpu().numpy()

    fig, axes = plt.subplots(2, 1, figsize=(20, 5))

    axes[0].imshow(batch_np)
    axes[0].set_title("Augmented / Transformed", fontsize=13)
    axes[0].axis("off")

    axes[1].imshow(original_np)
    axes[1].set_title("Original", fontsize=13)
    axes[1].axis("off")

    plt.tight_layout()
    plt.savefig("batch_visualization.png", dpi=150, bbox_inches="tight")
    plt.close()


#visualize_batch(batch_imgs, original_imgs)


# -----------------------


backbone = timm.create_model(
    "mobilenetv3_small_050", pretrained=True, features_only=False, num_classes=0
)

# # Freeze the backbone (all layers)
# for param in backbone.parameters():
#     param.requires_grad = False

feature_dim = backbone(torch.zeros(1, 3, PATCH_SIZE, PATCH_SIZE)).shape[-1]


joint_head = JointHead(
    feature_dim,
    HIDDEN_DIM,
    EMBED_DIM,
    PROJ_DIM,
    num_classes=N_CLASS,
    grid_size=GRID_SIZE,
).to(DEVICE)
#mem_bank = MemoryBank(MEMORY_BANK_SIZE, feature_dim)


# lr_head = 1e-3
# lr_backbone = 1e-4
lr_head = 1e-2
lr_backbone = 1e-2
weight_decay = 1e-5

# spatial_mask = ContentAwareMask(H=PATCH_SIZE, W=PATCH_SIZE).to(DEVICE)


optimizer = torch.optim.AdamW(
    [
        {
            "params": backbone.parameters(),
            "lr": lr_backbone,
        },  # plus petit lr pour backbone
        {
            "params": joint_head.parameters(),
            "lr": lr_head,
        },  # lr plus grand pour la tête
        #    {'params': spatial_mask.parameters(), 'lr': 1e-3}  # slower
    ],
    weight_decay=weight_decay,
)

backbone = backbone.to(DEVICE)
joint_head = joint_head.to(DEVICE)

label_tracker = LabeledRateTracker(N_CLASS, momentum=0.9, device=DEVICE)  # outside loop

logger = logging.getLogger(__name__)
from datetime import datetime
writer = SummaryWriter(log_dir=f"runs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

niter_total = 0
# last_save = 0
# running_loss = []


# ideal spacing given batch size and grid size
ideal_spacing = GRID_SIZE / math.sqrt(BATCH_SIZE)  # ~3.1 for 1024 points
REPULSION_MARGIN = ideal_spacing * 10.5  # slight buffer above ideal

del batch_imgs, batch_labels, original_imgs  # free up memory from initial batch

all_views = torch.cat([v.float().to(DEVICE) / 255.0 for v in views], dim=0)

## ---- UNCOMMENT - JUST COMMENTED OUT FORS PEEED
z_init, proj_coords_init = initialize_projection_from_batch(
    backbone, joint_head, all_views, writer, grid_size=GRID_SIZE
)

#mem_bank.add_candidates(z_init, proj_coords_init)

scaler = torch.amp.GradScaler("cuda")
import os

os.makedirs("./models", exist_ok=True)

# initialize DB writer (non-blocking) - stores first view's x,y and embedding blob per id
db_writer = SQLiteWriter(db_path="./coords_embeddings.db", batch_size=512, flush_interval=0.25)
atexit.register(db_writer.close)

#spread_loss = SpreadLoss(grid_size=GRID_SIZE, quantile=0.95)


patch_mask = gaussian_mask(PATCH_SIZE, PATCH_SIZE).to(DEVICE)


for _ in range(10_000):
    for batch_idx, batch_data in tqdm(enumerate(vram_prefetcher)):
        # forward all views → [nviews, B, D]
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=True):
            *views, labels, orig, ids = batch_data
            labels = labels.long().to(DEVICE)

            # imgs = torch.cat(views, dim=0).half().to(DEVICE) / 255.0  # [B*V, C, H, W]
            views = [v.half().to(DEVICE) for v in views]

            # Concatenate, convert to half-precision, and normalize
            imgs = torch.cat(views, dim=0) / 255.0  # [B*V, C, H, W]

            if USE_MASK:
                # imgs = spatial_mask(imgs)
                imgs = imgs * patch_mask.unsqueeze(0).unsqueeze(
                    0
                )  # broadcast over [B, C, H, W]

            z = backbone(imgs)  # [B*V, D]
            emb, coords, logits = joint_head(z)  # [B*V, ...]

            B = views[0].shape[0]
            V = len(views)

            emb = F.normalize(emb, dim=-1)   #NOTE: this is likely done in a few of the functions below as well but doing it twice shouldn't be a problem and ensures consistency across all losses that use emb

            # directly get [V, B, D] shape
            proj_emb = emb.view(V, B, -1)
            proj_coords = coords.view(V, B, -1)

            #-------------- write to sqlite
            # --- enqueue first view's coords and embeddings to the DB writer (non-blocking)
            try:
                # take first view only
                first_view_coords = proj_coords[0].detach().cpu().float().numpy()
                first_view_embs = proj_emb[0].detach().cpu().float().numpy()
                # ids may be tensor or list
                try:
                    ids_np = ids.detach().cpu().numpy()
                except Exception:
                    import numpy as _np

                    ids_np = _np.asarray(ids)

                db_writer.enqueue(ids_np, first_view_coords, first_view_embs)
            except Exception as _e:
                logger.exception("DB enqueue failed: %s", _e)
            #------- finish write

            pred_logits = logits.view(V, B, -1)

            # ---compute other losses
            #occ_loss, intra_loss = bin_losses_vectorized(proj_coords, target_count)
            neigh_loss = neighborhood_loss(proj_emb, proj_coords)

            # coordinate consistency
            # mean_coords = proj_coords.mean(dim=0, keepdim=True)
            # coord_consistency_loss = (
            #     ((proj_coords - mean_coords) ** 2).sum(dim=-1).mean()
            # )
            anchor_coords = proj_coords[0:1]  # [1, 1024, 2]
            coord_consistency_loss = ((proj_coords[1:] - anchor_coords) ** 2).sum(dim=-1).mean()

            # coord_contrastive: different samples → push apart (use mean coords per sample)
            dists = torch.cdist(anchor_coords, anchor_coords).squeeze()  # [B, B]

            # only push apart different samples (mask diagonal)
            mask = ~torch.eye(dists.shape[0], dtype=torch.bool, device=DEVICE)
            coord_contrastive_loss = (1.0 / (dists[mask] + 1e-6)).mean()

            # contrastive / prototype losses: support simclr or swav (configurable)
            if LOSS_TYPE.lower() == "swav":
                # use the learnable prototypes from the joint head for embedding SwAV
                simclr_emb_loss = swav_loss(proj_emb, prototypes=joint_head.prototypes)
                # for coordinates, keep k-means-based SwAV (prototypes not provided)
                simclr_emb_loss_coord = swav_loss(proj_coords)
            else:
                simclr_emb_loss = simclr_loss(proj_emb, temperature=0.07)
                simclr_emb_loss_coord = simclr_loss(proj_coords, temperature=0.07)

            # flat [nviews*B, D] — drop-in for all existing functions
            proj_emb = proj_emb.view(-1, proj_emb.shape[-1])
            proj_coords = proj_coords.view(-1, 2)
            pred_logits = pred_logits.view(-1, pred_logits.shape[-1])
            labels = labels.repeat(len(views))

#            spread_loss_val = spread_loss(proj_coords)
            max_mean_discrepancy_loss = max_mean_discrepancy(proj_coords)
            repulsion_loss_val = repulsion_loss(proj_coords, margin=REPULSION_MARGIN)

            semantic_coord_attr_loss, semantic_coord_repel_loss = semantic_head_loss(proj_coords, labels)
            semantic_coord_loss = (semantic_coord_attr_loss + semantic_coord_repel_loss)  # report seperately

            proj_emb_norm = F.normalize(proj_emb, dim=1 )  # projects onto unit hypersphere

            semantic_emb_attr_loss, semantic_emb_repel_loss = semantic_head_loss(proj_emb_norm, labels, margin=0.5)
            
            semantic_emb_loss = (semantic_emb_attr_loss + semantic_emb_repel_loss)  # report seperately

            class_weights = label_tracker.get_class_weights()

            sup_pred_loss = prediction_loss_sup(pred_logits,labels,class_weights=class_weights)

            pseudo_pred_loss, pred_labels, high_conf = prediction_loss_pseudo(pred_logits,labels,pseudo_class_weights=None,pseudo_thresh=PSEUDO_THRESH,views_per_patch=NVIEWS)  # i don't think we want psudo class weights
            pred_loss = (sup_pred_loss + PSEUDO_PRED_LAMBDA * pseudo_pred_loss)  # report seperately

            labeled_rate, num_label, num_pseudo = label_tracker.update(
                labels, pred_labels[high_conf] if high_conf is not None else None
            )  # update with current batch's true and pseudo labels

            # # ---compute tempoerate loss - make sure our coorindates don't go wild
            # mem_z, mem_coords, mem_ages = mem_bank.sample(MEMORY_SAMPLE_SIZE)
            # if mem_z.shape[0] > 0:
            #     with torch.no_grad():
            #         _, mem_proj_coords_now, _ = joint_head(mem_z)
            #     margin = get_margin(pred_loss, labeled_rate)
            #     loss_temp = temporal_loss(
            #         mem_proj_coords_now, mem_coords, mem_ages, margin=margin
            #     )
            # else:
            #     loss_temp = torch.tensor(0.0, device=DEVICE)

            # contrastative loss ==  ??   proj + emb space

            total_loss = (
                COORD_CONSITENCY_LOSS * coord_consistency_loss
                + COORD_CONTRASTIVE_LOSS * coord_contrastive_loss
                + SIMCLR_EMB_LOSS * simclr_emb_loss
                + SIMCLR_EMB_LOSS * simclr_emb_loss_coord
                #                        + SPREAD_LOSS * spread_loss_val
                + MAX_MEAN_LOSS * max_mean_discrepancy_loss
                # BATCH_BIN_LAMBDA  * occ_loss
                # + REPULSION_LAMBDA   * repulsion_loss_val
                # + INTRA_BIN_LAMBDA  * intra_loss
                + NEIGHBOR_LAMBDA * neigh_loss
                #                   + TEMPORAL_LAMBDA   * loss_temp
                + SEMANTIC_LAMBDA
                * semantic_coord_loss  # * labeled_rate  # not sure if this addidtional makes sense?
                + SEMANTIC_LAMBDA
                * semantic_emb_loss  # * labeled_rate  # not sure if this addidtional makes sense?
                + PRED_LAMBDA * pred_loss
            )

            optimizer.zero_grad()
            scaler.scale(total_loss).backward()
            scaler.step(optimizer)
            scaler.update()

            # mem_bank.add_candidates(z_batch.detach(), proj_coords.detach()) #___COMMENTED OUT
            #mem_bank.age_all()

            if niter_total % LOG_EVERY == 0:
                logger.info("writing embeddings")
                log_embeddings(
                    writer,
                    torch.zeros(0), #z_batch
                    proj_coords,
                    pred_logits,
                    labels,
                    pred_labels,
                    high_conf,
                    None, #mem_bank
                    niter_total,
                    write_embeddings=False,
                )
                log_nearest_neighbors(
                    writer,
                    imgs,
                    orig,
                    proj_emb,
                    proj_coords,
                    niter_total,
                    labels=labels,
                    pred_labels=pred_labels,
                    n_queries=5,
                    n_neighbors=5,
                )

                if LOG_ORIGS:
                    imgs_orig = orig.permute(0, 3, 1, 2).to(DEVICE) / 255.0
                    imgs_orig = center_crop(imgs_orig, PATCH_SIZE)

                    if USE_MASK:
                        # imgs_orig = spatial_mask(imgs_orig)
                        imgs_orig = imgs_orig * patch_mask.unsqueeze(0).unsqueeze(0)

                    z_orig = backbone(imgs_orig)  # [B, D]
                    emb_orig, coords_orig, _ = joint_head(z_orig)  # [B, D], [B, 2]

                    # normalize and compute self-similarity (no cross-view, just orig vs orig)
                    emb_orig_norm = F.normalize(
                        emb_orig.detach().cpu().float(), dim=-1
                    )  # [B, D]
                    sim_emb = torch.mm(emb_orig_norm, emb_orig_norm.T)  # [B, B]
                    sim_coords = -torch.cdist(
                        coords_orig.detach().cpu().float(),
                        coords_orig.detach().cpu().float(),
                    )  # [B, B]

                    log_nearest_neighbors_orig(
                        writer,
                        orig,
                        sim_emb,
                        sim_coords,
                        niter_total,
                        labels=labels,
                        pred_labels=pred_labels,
                        n_queries=5,
                        n_neighbors=5,
                    )

                    del imgs_orig, z_orig, emb_orig, coords_orig
                    del emb_orig_norm, sim_emb, sim_coords

            # tensorboard
            writer.add_scalar("loss/total", total_loss.item(), niter_total)
            writer.add_scalar(
                "loss/coord_consistency", coord_consistency_loss.item(), niter_total
            )
            writer.add_scalar(
                "loss/coord_contrastive", coord_contrastive_loss.item(), niter_total
            )
            writer.add_scalar("loss/simclr_emb", simclr_emb_loss.item(), niter_total)
            writer.add_scalar("loss/simclr_coord", simclr_emb_loss_coord.item(), niter_total)
            #writer.add_scalar("loss/spread", spread_loss_val.item(), niter_total)
            writer.add_scalar(
                "loss/max_mean_discrepancy",
                max_mean_discrepancy_loss.item(),
                niter_total,
            )
            writer.add_scalar("loss/repulsion", repulsion_loss_val.item(), niter_total)
            # writer.add_scalar("loss/occupancy", occ_loss.item(), niter_total)
            # writer.add_scalar("loss/intra_bin", intra_loss.item(), niter_total)
            writer.add_scalar("loss/neighborhood", neigh_loss.item(), niter_total)
#            writer.add_scalar("loss/temporal", loss_temp.item(), niter_total)
            writer.add_scalar(
                "loss/semantic_coord", semantic_coord_loss.item(), niter_total
            )
            # writer.add_scalar('loss/semantic_coord_weighted',   semantic_coord_loss.item() * labeled_rate, niter_total)
            # writer.add_scalar('train/semantic_coord_lambda',    labeled_rate * SEMANTIC_LAMBDA,      niter_total)
            writer.add_scalar(
                "loss/semantic_coord_attract",
                semantic_coord_attr_loss.item(),
                niter_total,
            )
            writer.add_scalar(
                "loss/semantic_coord_repel",
                semantic_coord_repel_loss.item(),
                niter_total,
            )

            writer.add_scalar(
                "loss/semantic_emb", semantic_emb_loss.item(), niter_total
            )
            # writer.add_scalar('loss/semantic_emb_weighted',   semantic_emb_loss.item() * labeled_rate, niter_total)
            writer.add_scalar(
                "loss/semantic_emb_attract", semantic_emb_attr_loss.item(), niter_total
            )
            writer.add_scalar(
                "loss/semantic_emb_repel", semantic_emb_repel_loss.item(), niter_total
            )

            writer.add_scalar("loss/pred", pred_loss.item(), niter_total)
            writer.add_scalar("loss/pred_supervised", sup_pred_loss.item(), niter_total)
            writer.add_scalar("loss/pred_pseudo", pseudo_pred_loss.item(), niter_total)
            writer.add_scalar("train/labeled_rate", labeled_rate, niter_total)
            # writer.add_scalar(
            #     "train/temporal_margin",
            #     margin if mem_z.shape[0] > 0 else 5.0,
            #     niter_total,
            # )
            # writer.add_scalar("train/memory_size", mem_bank.z.shape[0], niter_total)

            total_pseudo = 0
            if num_pseudo is not None and num_pseudo.any():
                total_pseudo = num_pseudo.sum()
                for i in (num_pseudo > 0).nonzero(as_tuple=True)[0].tolist():
                    writer.add_scalar(
                        f"loss/num_pseudo/{i}", num_pseudo[i].item(), niter_total
                    )

            writer.add_scalar("loss/num_pseudo/total", total_pseudo, niter_total)

            #add sqlite update
            niter_total += 1


logger.info("Exiting training!")
writer.close()
