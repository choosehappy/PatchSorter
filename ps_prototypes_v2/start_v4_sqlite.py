# %%
import io
import random
import sqlite3

import torch
import torch.nn.functional as F
from albumentations.pytorch import ToTensorV2
from torchvision.transforms.functional import center_crop
from tqdm import tqdm
import logging

from utils import *
from patch_logging import *
from utils_logging import (
    enqueue_embeddings_to_db,
    init_db_writer,
    init_summary_writer,
    log_confusion_matrix,
    log_embedding_histograms,
    log_training_scalars,
)
import timm
from configs import *
from sqlite_dataset import GTEnrichedDataset
from score_writer import ScoreWriter
import atexit

from save_utils import save_models_checkpoint, load_models_checkpoint
from utils_profile import start_profiler

import tables
import numpy as np

torch.set_float32_matmul_precision('high')

# Initialize dataset with proper parameters
DATA_DB_PATH = "mitosis_train_patches.db"

label_tracker = LabeledRateTracker(N_CLASS, momentum=0.9, device=DEVICE)
adaptive_thresh = AdaptiveThreshold(num_classes=N_CLASS, base_thresh=0.95, ema_decay=0.99, device=DEVICE)


score_writer = ScoreWriter(DATA_DB_PATH)
atexit.register(score_writer.close)

dataset = GTEnrichedDataset(
    DATA_DB_PATH,
    nviews=NVIEWS,
    transforms=get_transforms(PATCH_SIZE),
    enrichment_rate=GT_ENRICHMENT,
    label_tracker=label_tracker,
    score_writer=score_writer,
)


dataloader = DataLoader(
    InfiniteDataset(dataset),
    batch_size=BATCH_SIZE,
    shuffle=False,
    #num_workers=64,
    num_workers=32,
    pin_memory=True,
    drop_last=True,
    persistent_workers=True,
    prefetch_factor=4, #UNCOMMENT
)
# prefetcher = cuda_prefetc[her(dataloader)
vram_prefetcher = threaded_vram_prefetcher(dataloader, buffer_size=4, device=DEVICE) #UNCOMMENT
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
).to(DEVICE,non_blocking=True)
#mem_bank = MemoryBank(MEMORY_BANK_SIZE, feature_dim)



# lr_head = 1e-3
# lr_backbone = 1e-4
lr_head = 1e-2
lr_backbone = 1e-3
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

backbone = backbone.to(DEVICE,non_blocking=True)
joint_head = joint_head.to(DEVICE,non_blocking=True)

# print("Starting compile")
# backbone = torch.compile(backbone)
# joint_head = torch.compile(joint_head)
# print("end compile")

from torchinfo import summary
summary(backbone, (1,3,64,64),device=DEVICE)
summary(joint_head, (1,1024),device=DEVICE)

logger = logging.getLogger(__name__)

# Optionally load latest checkpoint
if LOAD_CHECKPOINT:
    try:
        load_models_checkpoint("./model",backbone=backbone, joint_head=joint_head)
    except Exception:
        logger.exception("Loading checkpoint failed")

from datetime import datetime
writer = init_summary_writer()

niter_total = 0
# last_save = 0
# running_loss = []


# ideal spacing given batch size and grid size
ideal_spacing = GRID_SIZE / math.sqrt(BATCH_SIZE)  # ~3.1 for 1024 points
REPULSION_MARGIN = ideal_spacing * 10.5  # slight buffer above ideal

del batch_imgs, batch_labels, original_imgs  # free up memory from initial batch

all_views = torch.cat([v.float().to(DEVICE,non_blocking=True) / 255.0 for v in views], dim=0)


if not LOAD_CHECKPOINT:
    ## ---- UNCOMMENT - JUST COMMENTED OUT FORS PEEED
    z_init, proj_coords_init = initialize_projection_from_batch(
        backbone, joint_head, all_views, writer, grid_size=GRID_SIZE
    )

#mem_bank.add_candidates(z_init, proj_coords_init)

scaler = torch.amp.GradScaler("cuda")


# initialize DB writer (non-blocking) - stores first view's x,y and embedding blob per id
db_writer = init_db_writer(db_path="./coords_embeddings.db", batch_size=BATCH_SIZE, flush_interval=0.25)
atexit.register(db_writer.close)

# Initialize torch profiler if enabled
torch_profiler = start_profiler(TORCH_PROFILE,wait=5,active=5)

#spread_loss = SpreadLoss(grid_size=GRID_SIZE, quantile=0.95)


patch_mask = gaussian_mask(PATCH_SIZE, PATCH_SIZE).to(DEVICE,non_blocking=True)


for _ in range(10_000):
    for batch_idx, batch_data in tqdm(enumerate(vram_prefetcher)):
        # forward all views → [nviews, B, D]
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=False): ##TODO: don't use it while we're testing / building 
            *views, labels, orig, ids = batch_data
            labels = labels.long().to(DEVICE,non_blocking=True)

            # imgs = torch.cat(views, dim=0).half().to(DEVICE,non_blocking=True) / 255.0  # [B*V, C, H, W]
            # views = [v.half().to(DEVICE,non_blocking=True) for v in views] # lets not do this during development

            # Concatenate, convert to half-precision, and normalize
            views_gpu = [v.to(DEVICE, non_blocking=True) for v in views]
            #imgs = torch.stack(views_gpu, dim=1).flatten(0, 1) / 255.0  # [B*V, C, H, W] #NOTE: THIS WAS VERY WRONG, flattened in the wrong direction
            imgs = torch.stack(views_gpu, dim=0).flatten(0, 1) / 255.0  # [B*V, C, H, W]
 
            del views_gpu

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
            if LOG_EMBEDDINGS_TOSQL:
                try:
                    enqueue_embeddings_to_db(db_writer, proj_coords, proj_emb, ids)
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
                #simclr_emb_loss_coord = swav_loss(proj_coords)  -- this seems crazy
            else:
                simclr_emb_loss = simclr_loss(proj_emb, temperature=0.07)
                #simclr_emb_loss_coord = simclr_loss(proj_coords, temperature=0.07)

            # flat [nviews*B, D] — drop-in for all existing functions
            proj_emb = proj_emb.view(-1, proj_emb.shape[-1])
            proj_coords = proj_coords.view(-1, 2)
            pred_logits = pred_logits.view(-1, pred_logits.shape[-1])
            labels = labels.repeat(len(views))

#            spread_loss_val = spread_loss(proj_coords)
            max_mean_discrepancy_loss = max_mean_discrepancy(proj_coords)
            #repulsion_loss_val = repulsion_loss(proj_coords, margin=REPULSION_MARGIN)
            repulsion_loss_val = torch.tensor(0.0, device=DEVICE)  

            semantic_coord_attr_loss, semantic_coord_repel_loss = semantic_head_loss(proj_coords / GRID_SIZE, labels, margin=.05)
            semantic_coord_loss = (semantic_coord_attr_loss + semantic_coord_repel_loss)  # report seperately

            #proj_emb_norm = F.normalize(proj_emb, dim=1 )  # projects onto unit hypersphere
            proj_emb_norm = proj_emb #normalization was done above --- not name refactoring yet

            semantic_emb_attr_loss, semantic_emb_repel_loss = semantic_head_loss(proj_emb_norm, labels, margin=0.5)
            
            semantic_emb_loss = (semantic_emb_attr_loss + semantic_emb_repel_loss)  # report seperately

            class_weights = label_tracker.get_class_weights()

            sup_pred_loss, sup_accuracy , confusion= prediction_loss_sup(pred_logits,labels,num_classes=N_CLASS,class_weights=class_weights)

            # pseudo_pred_loss, pred_labels, high_conf = prediction_loss_pseudo_sce(pred_logits,labels,pseudo_class_weights=None,
            #                                                                   views_per_patch=NVIEWS)  # i don't think we want psudo class weights

            pseudo_class_weights = label_tracker.get_class_weights(pseudo=True)

            pseudo_pred_loss, pred_labels, high_conf = prediction_loss_pseudo_sce_adaptive(pred_logits,labels,adaptive_thresh,
                                                                                           pseudo_class_weights=pseudo_class_weights,views_per_patch=NVIEWS)  # i don't think we want psudo class weights

            
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
                #+ SIMCLR_EMB_LOSS * simclr_emb_loss_coord
                #                        + SPREAD_LOSS * spread_loss_val
                + MAX_MEAN_LOSS * max_mean_discrepancy_loss
                # BATCH_BIN_LAMBDA  * occ_loss
                # + REPULSION_LAMBDA   * repulsion_loss_val
                # + INTRA_BIN_LAMBDA  * intra_loss
                + NEIGHBOR_LAMBDA * neigh_loss
                #                   + TEMPORAL_LAMBDA   * loss_temp
                + SEMANTIC_COORD_LAMBDA
                * semantic_coord_loss  # * labeled_rate  # not sure if this addidtional makes sense?
                + SEMANTIC_EMB_LAMBDA
                * semantic_emb_loss  # * labeled_rate  # not sure if this addidtional makes sense?
                + PRED_SUP_LAMBDA * sup_pred_loss
                + PRED_PSEUDO_LAMBDA * pseudo_pred_loss
            )

            optimizer.zero_grad()
            scaler.scale(total_loss).backward()
            scaler.step(optimizer)
            scaler.update()

            # mem_bank.add_candidates(z_batch.detach(), proj_coords.detach()) #___COMMENTED OUT
            #mem_bank.age_all()

            if niter_total % GT_POOL_UPDATE_INTERVAL== 0:
                dataset.refresh()


            if niter_total % LOG_EVERY == 0:
                log_embedding_histograms(writer, proj_emb, niter_total)

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

                # save a timestamped checkpoint to avoid overwriting
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_models_checkpoint("./model", timestamp=ts, backbone=backbone, joint_head=joint_head)
                except Exception:
                    logger.exception("Checkpoint save failed at iteration %s", niter_total)

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
            loss_values = {
                "loss/total": total_loss.item(),
                "loss/coord_consistency": coord_consistency_loss.item(),
                "loss/coord_contrastive": coord_contrastive_loss.item(),
                "loss/simclr_emb": simclr_emb_loss.item(),
                "loss/max_mean_discrepancy": max_mean_discrepancy_loss.item(),
                "loss/repulsion": repulsion_loss_val.item(),
                "loss/neighborhood": neigh_loss.item(),
                "loss/semantic_coord": semantic_coord_loss.item(),
                "loss/semantic_coord_attract": semantic_coord_attr_loss.item(),
                "loss/semantic_coord_repel": semantic_coord_repel_loss.item(),
                "loss/semantic_emb": semantic_emb_loss.item(),
                "loss/semantic_emb_attract": semantic_emb_attr_loss.item(),
                "loss/semantic_emb_repel": semantic_emb_repel_loss.item(),
                "loss/pred_supervised": sup_pred_loss.item(),
                "loss/sup_accuracy": sup_accuracy.item(),
                "loss/pred_pseudo": pseudo_pred_loss.item()
            }

            scaled_loss_values = {
                "loss_scaled/coord_consistency": COORD_CONSITENCY_LOSS * coord_consistency_loss.item(),
                "loss_scaled/coord_contrastive": COORD_CONTRASTIVE_LOSS * coord_contrastive_loss.item(),
                "loss_scaled/simclr_emb": SIMCLR_EMB_LOSS * simclr_emb_loss.item(),
                "loss_scaled/max_mean_discrepancy": MAX_MEAN_LOSS * max_mean_discrepancy_loss.item(),
                "loss_scaled/neighborhood": NEIGHBOR_LAMBDA * neigh_loss.item(),
                "loss_scaled/semantic_coord": SEMANTIC_COORD_LAMBDA * semantic_coord_loss.item(),
                "loss_scaled/semantic_emb": SEMANTIC_EMB_LAMBDA * semantic_emb_loss.item(),
                "loss_scaled/pred_supervised": PRED_SUP_LAMBDA * sup_pred_loss.item(),
                "loss_scaled/pred_pseudo": PRED_PSEUDO_LAMBDA * pseudo_pred_loss.item(),
            }

            log_training_scalars(
                writer,
                loss_values,
                scaled_loss_values,
                labeled_rate,
                num_pseudo,
                niter_total,
            )


            log_confusion_matrix(writer, confusion, niter_total)
    
            niter_total += 1
            if torch_profiler:
                torch_profiler.step()


# final save of model checkpoints
try:
    save_models_checkpoint("./model")
except Exception:
    logger.exception("Final checkpoint save failed")

logger.info("Exiting training!")
writer.close()
