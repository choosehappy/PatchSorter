# %% 
import torch
import torch.nn as nn
import torch.nn.functional as F
import random
import torchvision.utils as vutils

from torch.utils.tensorboard import SummaryWriter
import logging

from tqdm import tqdm
# +

import albumentations as A

from albumentations.pytorch import ToTensorV2
import cv2
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
#from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from utils import *

import timm
from torch.utils.data import DataLoader

from configs import *
# -

num_bins = GRID_SIZE**2  # 10000
target_count = max(BATCH_SIZE / num_bins,1)  # ~0.1024  #--- i think this may need to be a positive number?
print(f"Target count per bin: {target_count:.4f}")


import tables
class Dataset(object):
    def __init__(self, fname ,nviews, transforms=None):
        self.fname=fname

        self.geom_transform, self.photo_transform = transforms if transforms else (None, None)
        

        with tables.open_file(self.fname,'r') as db:
            self.nitems=db.root.patch.shape[0]
        
        self.imgs = None
        self.labels = None
        self.nviews=nviews
        
    def __getitem__(self, index):

        with tables.open_file(self.fname,'r') as db:
            self.imgs=db.root.patch
            self.labels=db.root.ps_label

            #get the requested image and mask from the pytable
            img = self.imgs[index,:,:,:]
            label = self.labels[index]
        
        
        img_new = img

        if self.geom_transform:
            geom_out = self.geom_transform(image=img_new)
            img_geom = geom_out["image"]

            if self.photo_transform:
                views = tuple(
                    self.photo_transform(image=img_geom)["image"]
                    for _ in range(self.nviews)
                )
                return (*views, label, img)

        else:
            print("no aug?")
            return img_new, label, img
        

    def __len__(self):
        return self.nitems


dataset=Dataset("mitosis_ps_labels.pytable", nviews=NVIEWS, transforms=get_transforms(PATCH_SIZE))
dataloader=DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=16,pin_memory=True, 
                drop_last=True)#, persistent_workers = True, prefetch_factor=2)


#------------------------



import matplotlib.pyplot as plt
import numpy as np
import math

# obtenir un batch
batch_data = next(iter(dataloader))
*views, batch_labels, original_imgs = batch_data
batch_imgs = views[0] 

import matplotlib.pyplot as plt
import torchvision.utils as vutils

def visualize_batch(batch_imgs, original_imgs, nrow=10,ntot=50):
    batch_imgs    = batch_imgs[:ntot]
    original_imgs = original_imgs[:ntot].permute(0, 3, 1, 2)  # (B, H, W, C) -> (B, C, H, W)

    batch_grid    = vutils.make_grid(batch_imgs,    nrow=nrow, padding=2)
    original_grid = vutils.make_grid(original_imgs, nrow=nrow, padding=2)

    batch_np    = batch_grid.permute(1, 2, 0).cpu().numpy()
    original_np = original_grid.permute(1, 2, 0).cpu().numpy()

    fig, axes = plt.subplots(2, 1, figsize=(20, 5))

    axes[0].imshow(batch_np)
    axes[0].set_title("Augmented / Transformed", fontsize=13)
    axes[0].axis("off")

    axes[1].imshow(original_np)
    axes[1].set_title("Original", fontsize=13)
    axes[1].axis("off")

    plt.tight_layout()
    plt.savefig("batch_visualization.png", dpi=150, bbox_inches='tight')
    plt.close()

visualize_batch(batch_imgs, original_imgs) 


#-----------------------


backbone=timm.create_model('mobilenetv3_small_050', pretrained=True, features_only=False, num_classes=0 )

# # Freeze the backbone (all layers)
# for param in backbone.parameters():
#     param.requires_grad = False

feature_dim = backbone(torch.zeros(1, 3, PATCH_SIZE, PATCH_SIZE)).shape[-1]


joint_head = JointHead(feature_dim, HIDDEN_DIM, EMBED_DIM, PROJ_DIM, num_classes=N_CLASS, grid_size=GRID_SIZE).to(DEVICE)
mem_bank = MemoryBank(MEMORY_BANK_SIZE, feature_dim)


lr_head = 1e-3
lr_backbone = 1e-4
weight_decay = 1e-5


optimizer = torch.optim.AdamW([
    {'params': backbone.parameters(), 'lr': lr_backbone},  # plus petit lr pour backbone
    {'params': joint_head.parameters(), 'lr': lr_head}     # lr plus grand pour la tête
], weight_decay=weight_decay)

backbone=backbone.to(DEVICE)
joint_head=joint_head.to(DEVICE)    

label_tracker = LabeledRateTracker(momentum=0.9)  # outside loop

logger = logging.getLogger(__name__)
writer = SummaryWriter(log_dir='runs/projection')

niter_total = 0
last_save = 0
running_loss = []


# ideal spacing given batch size and grid size
ideal_spacing = GRID_SIZE / math.sqrt(BATCH_SIZE)  # ~3.1 for 1024 points
REPULSION_MARGIN = ideal_spacing * 10.5             # slight buffer above ideal

del batch_imgs, batch_labels, original_imgs  # free up memory from initial batch

all_views = torch.cat([v.float().to(DEVICE)/255.0 for v in views], dim=0)
z_init, proj_coords_init = initialize_projection_from_batch(backbone, joint_head, all_views, writer, grid_size=GRID_SIZE)
mem_bank.add_candidates(z_init, proj_coords_init )

scaler = torch.amp.GradScaler("cuda")


spread_loss = SpreadLoss(grid_size=GRID_SIZE, quantile=0.95)

for _ in range(100):
    for batch_idx, batch_data in tqdm(enumerate(dataloader)):
        # forward all views → [nviews, B, D]
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=True):

            *views, labels, orig = batch_data
            labels = labels.long().to(DEVICE)
            labeled_rate = label_tracker.update(labels)

            imgs = torch.cat(views, dim=0).half().to(DEVICE) / 255.0  # [B*V, C, H, W]
            z = backbone(imgs)                                          # [B*V, D]
            emb, coords, logits = joint_head(z)                        # [B*V, ...]

            B = views[0].shape[0]
            V = len(views)

            # directly get [V, B, D] shape
            z_batch     = z.view(V, B, -1)
            proj_emb    = emb.view(V, B, -1)
            proj_coords = coords.view(V, B, -1)
            pred_logits = logits.view(V, B, -1)

            
            # coordinate consistency
            mean_coords = proj_coords.mean(dim=0, keepdim=True)
            coord_consistency_loss = ((proj_coords - mean_coords) ** 2).sum(dim=-1).mean() 

            # coord_contrastive: different samples → push apart (use mean coords per sample)
            dists = torch.cdist(mean_coords, mean_coords).squeeze()  # [B, B]

            # only push apart different samples (mask diagonal)
            mask = ~torch.eye(dists.shape[0], dtype=torch.bool, device=DEVICE)
            coord_contrastive_loss = (1.0 / (dists[mask] + 1e-6)).mean()


            simclr_emb_loss = simclr_loss(proj_emb, temperature=0.5)


            # flat [nviews*B, D] — drop-in for all existing functions
            z_batch     = z_batch.view(-1, z_batch.shape[-1])
            proj_emb    = proj_emb.view(-1, proj_emb.shape[-1])
            proj_coords = proj_coords.view(-1, 2)
            pred_logits = pred_logits.view(-1, pred_logits.shape[-1])
            labels      = labels.repeat(len(views))



            spread_loss_val = spread_loss(proj_coords) 
            max_mean_discrepancy_loss = max_mean_discrepancy(proj_coords)
            repulsion_loss_val = repulsion_loss(proj_coords, margin=REPULSION_MARGIN)
            
            #---compute other losses
            occ_loss, intra_loss  = bin_losses_vectorized(proj_coords,target_count)
            neigh_loss = neighborhood_loss(proj_emb, proj_coords) 

            semantic_attr_loss, semantic_repel_loss  = semantic_head_loss(proj_coords, labels)
            semantic_loss = semantic_attr_loss + semantic_repel_loss  #report seperately
            
            sup_pred_loss,pseudo_pred_loss  = prediction_loss(pred_logits, labels, pseudo_thresh=PSEUDO_THRESH)
            pred_loss = sup_pred_loss + PSEUDO_PRED_LAMBDA*pseudo_pred_loss #report seperately

            #---compute tempoerate loss - make sure our coorindates don't go wild 
            mem_z, mem_coords, mem_ages = mem_bank.sample(MEMORY_SAMPLE_SIZE)
            if mem_z.shape[0] > 0:
                with torch.no_grad():
                    _, mem_proj_coords_now, _ = joint_head(mem_z)
                margin = get_margin(pred_loss, labeled_rate)
                loss_temp = temporal_loss(mem_proj_coords_now, mem_coords, mem_ages, margin=margin)
            else:
                loss_temp = torch.tensor(0.0, device=DEVICE)

            #contrastative loss ==  ??   proj + emb space
            
            total_loss = (
                        COORD_CONSITENCY_LOSS * coord_consistency_loss 
                        + COORD_CONTRASTIVE_LOSS *  coord_contrastive_loss
                        + SIMCLR_EMB_LOSS * simclr_emb_loss
#                        + SPREAD_LOSS * spread_loss_val
                        + MAX_MEAN_LOSS * max_mean_discrepancy_loss
                #BATCH_BIN_LAMBDA  * occ_loss
                        #+ REPULSION_LAMBDA   * repulsion_loss_val

                        # + INTRA_BIN_LAMBDA  * intra_loss
                         + NEIGHBOR_LAMBDA   * neigh_loss
    #                   + TEMPORAL_LAMBDA   * loss_temp
    #                  + labeled_rate      * SEMANTIC_LAMBDA * semantic_loss
    #                    + PRED_LAMBDA       * pred_loss
            )


            optimizer.zero_grad()
            scaler.scale(total_loss).backward()
            scaler.step(optimizer)
            scaler.update()    
        

            mem_bank.add_candidates(z_batch.detach(), proj_coords.detach())
            mem_bank.age_all()


            log_embeddings(writer, z_batch, proj_coords, pred_logits, labels, mem_bank, niter_total, write_embeddings = False)
            log_nearest_neighbors(writer, orig, proj_emb, proj_coords, niter_total, n_queries=5, n_neighbors=5, log_every=10)


            # tensorboard
            writer.add_scalar('loss/total',               total_loss.item(),        niter_total)
            writer.add_scalar('loss/coord_consistency', coord_consistency_loss.item(), niter_total)
            writer.add_scalar('loss/coord_contrastive', coord_contrastive_loss.item(), niter_total)
            writer.add_scalar('loss/simclr_emb',          simclr_emb_loss.item(), niter_total)
            writer.add_scalar('loss/spread',             spread_loss_val.item(),   niter_total)
            writer.add_scalar('loss/max_mean_discrepancy',               max_mean_discrepancy_loss.item(),     niter_total)
            writer.add_scalar('loss/repulsion', repulsion_loss_val.item(), niter_total)
            writer.add_scalar('loss/occupancy',           occ_loss.item(),          niter_total)
            writer.add_scalar('loss/intra_bin',           intra_loss.item(),        niter_total)
            writer.add_scalar('loss/neighborhood',        neigh_loss.item(),        niter_total)
            writer.add_scalar('loss/temporal',            loss_temp.item(),         niter_total)
            writer.add_scalar('loss/semantic',            semantic_loss.item(),                niter_total)
            writer.add_scalar('loss/semantic_weighted',   semantic_loss.item() * labeled_rate, niter_total)
            writer.add_scalar('train/semantic_lambda',    labeled_rate * SEMANTIC_LAMBDA,      niter_total)        
            writer.add_scalar('loss/semantic_attract',    semantic_attr_loss.item(),niter_total)
            writer.add_scalar('loss/semantic_repel',      semantic_repel_loss.item(),niter_total)
            writer.add_scalar('loss/pred',                pred_loss.item(),         niter_total)
            writer.add_scalar('loss/pred_supervised',     sup_pred_loss.item(),     niter_total)
            writer.add_scalar('loss/pred_pseudo',         pseudo_pred_loss.item(),  niter_total)
            writer.add_scalar('train/labeled_rate',       labeled_rate,             niter_total)
            writer.add_scalar('train/temporal_margin',    margin if mem_z.shape[0] > 0 else 5.0, niter_total)
            writer.add_scalar('train/memory_size',        mem_bank.z.shape[0],      niter_total)

            running_loss.append(total_loss.item())
            niter_total += 1
            last_save   += 1

            if niter_total % 25 == 0   :
                avg_loss = sum(running_loss) / len(running_loss)
                logger.info(f"niter_total [{niter_total}], Avg Loss: {avg_loss:.4f}")
                logger.info(f"  - Occupancy:          {occ_loss.item():.4f}")
                logger.info(f"  - Intra Bin:          {intra_loss.item():.4f}")
                logger.info(f"  - Neighborhood:       {neigh_loss.item():.4f}")
                logger.info(f"  - Temporal:           {loss_temp.item():.4f} (margin={margin if mem_z.shape[0] > 0 else 5.0:.3f})")
                logger.info(f"  - Semantic:           {semantic_loss.item():.4f}")
                logger.info(f"    - Attract:          {semantic_attr_loss.item():.4f}")
                logger.info(f"    - Repel:            {semantic_repel_loss.item():.4f}")
                logger.info(f"  - Prediction:         {pred_loss.item():.4f}")
                logger.info(f"    - Supervised:       {sup_pred_loss.item():.4f}")
                logger.info(f"    - Pseudo:           {pseudo_pred_loss.item():.4f}")
                logger.info(f"  - Labeled Rate:       {labeled_rate:.3f}")
                logger.info(f"  - Memory Size:        {mem_bank.z.shape[0]}")

                logger.info("Saving model checkpoint")
                checkpoint_path = f'./models/model_{niter_total}.pth'
                torch.save({
                    'backbone':   backbone.state_dict(),
                    'joint_head': joint_head.state_dict(),
                    'optimizer':  optimizer.state_dict(),
                    'niter_total': niter_total,
                    'num_labeled': label_tracker.rate,
                }, checkpoint_path)
                logger.info(f"Checkpoint saved to {checkpoint_path}")

                running_loss = []
                last_save    = 0

logger.info("Exiting training!")
writer.close()

    # %%
