import torch
import torch.nn.functional as F
import torchvision.utils as vutils
import matplotlib.pyplot as plt

from configs import *
# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

CLASS_COLORS = [
    [0.20, 0.55, 0.90],  # blue
    [0.90, 0.20, 0.20],  # red
    [0.20, 0.78, 0.35],  # green
    [0.95, 0.75, 0.10],  # yellow
    [0.75, 0.25, 0.90],  # purple
    [0.95, 0.50, 0.10],  # orange
    [0.10, 0.85, 0.85],  # cyan
    [0.90, 0.40, 0.70],  # pink
]


def _label_to_color(label: int, lightness: float = 1.0) -> list[float]:
    """Map a class label to an RGB color; -1 (unlabeled) → gray.
    lightness in (0, 1] blends the color toward white."""
    if label < 0:
        base = [0.55, 0.55, 0.55]
    else:
        base = CLASS_COLORS[label % len(CLASS_COLORS)]
    return [1.0 - lightness * (1.0 - c) for c in base]


def _apply_borders(
    img_t: torch.Tensor,
    outer_label: int | None,
    inner_label: int | None,
    thickness: int = 2,
) -> torch.Tensor:
    """
    img_t : [3, H, W]  float32 in [0, 1]
    outer_label : pred_label  (outermost 2-px ring)
    inner_label : gt label    (next 2-px ring inward)
    Returns a new tensor with borders painted in-place on a clone.
    """
    img = img_t.clone()
    C, H, W = img.shape

    def paint(band_slice_h, band_slice_w, color):
        for c, v in enumerate(color):
            img[c, band_slice_h, band_slice_w] = v

    if outer_label is not None:
        col = _label_to_color(outer_label)
        t = thickness
        paint(slice(0, t), slice(None), col)  # top
        paint(slice(H - t, H), slice(None), col)  # bottom
        paint(slice(None), slice(0, t), col)  # left
        paint(slice(None), slice(W - t, W), col)  # right

    if inner_label is not None:
        col = _label_to_color(inner_label)
        t = thickness
        t2 = thickness * 2
        paint(slice(t, t2), slice(t, W - t), col)  # top
        paint(slice(H - t2, H - t), slice(t, W - t), col)  # bottom
        paint(slice(t, H - t), slice(t, t2), col)  # left
        paint(slice(t, H - t), slice(W - t2, W - t), col)  # right

    return img


def _pad_to(t: torch.Tensor, th: int, tw: int) -> torch.Tensor:
    """Centre-pad [N, 3, h, w] -> [N, 3, th, tw]."""
    _, _, h, w = t.shape
    ph, pw = (th - h) // 2, (tw - w) // 2
    return F.pad(t, (pw, tw - w - pw, ph, th - h - ph))


def _apply_borders_batch(
    imgs: torch.Tensor,
    outer_labels,  # int tensor [N] or None
    inner_labels,  # int tensor [N] or None
    thickness: int = 2,
) -> torch.Tensor:
    """Vectorised wrapper: applies borders to every image in [N, 3, H, W]."""
    N = imgs.shape[0]
    out = []
    for i in range(N):
        ol = int(outer_labels[i].item()) if outer_labels is not None else None
        il = int(inner_labels[i].item()) if inner_labels is not None else None
        out.append(_apply_borders(imgs[i], ol, il, thickness))
    return torch.stack(out)


# ---------------------------------------------------------------------------
# Main logging functions
# ---------------------------------------------------------------------------


def log_nearest_neighbors(
    writer,
    img_aug,
    orig,
    proj_emb,
    proj_coords,
    niter_total,
    labels=None,
    pred_labels=None,
    n_queries=5,
    n_neighbors=5,
):
    """
    labels      : int tensor [B], gt labels (-1 = unlabeled). Drives inner border.
    pred_labels : int tensor [B], model predictions.           Drives outer border.
    """
    V_B, D = proj_emb.shape
    B = orig.shape[0]
    V = V_B // B

    imgs_orig = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
    imgs_orig = imgs_orig.cpu().permute(0, 3, 1, 2)  # [B, 3, H, W]

    imgs_aug = img_aug.float() / 255.0 if img_aug.max() > 1.0 else img_aug.float()
    imgs_aug = imgs_aug.cpu().view(V, B, *img_aug.shape[1:])  # [V, B, 3, h, w]

    emb = F.normalize(proj_emb.detach().cpu().float(), dim=-1).view(V, B, D)
    emb_v0, emb_v1 = emb[0], emb[1]

    coords = proj_coords.detach().cpu().float().view(V, B, -1)
    coords_v0, coords_v1 = coords[0], coords[1]

    H, W = imgs_orig.shape[2], imgs_orig.shape[3]

    # Pre-compute bordered versions once
    ol = pred_labels.cpu() if pred_labels is not None else None
    il = labels.cpu() if labels is not None else None

    imgs_orig_b = _apply_borders_batch(imgs_orig, ol, il)
    imgs_aug_b = [_apply_borders_batch(imgs_aug[v], ol, il) for v in range(V)]

    query_idx = torch.randperm(B)[:n_queries].tolist()

    def make_grid(sim, use_aug_query, use_aug_neighbors):
        q_imgs = imgs_aug_b[0] if use_aug_query else imgs_orig_b
        nn_imgs = imgs_aug_b[1] if use_aug_neighbors else imgs_orig_b
        if use_aug_query:
            q_imgs = _pad_to(q_imgs, H, W)
        if use_aug_neighbors:
            nn_imgs = _pad_to(nn_imgs, H, W)

        rows = []
        for qi in query_idx:
            nn_idx = sim[qi].argsort(descending=True).tolist()
            nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
            row = torch.cat([q_imgs[qi].unsqueeze(0), nn_imgs[nn_idx]], dim=0)
            rows.append(row)
        return vutils.make_grid(
            torch.cat(rows, dim=0), nrow=n_neighbors + 1, padding=2, normalize=False
        )

    sim_emb = torch.mm(emb_v0, emb_v1.T)
    sim_coords = -torch.cdist(coords_v0, coords_v1)

    for space, sim in [("emb", sim_emb), ("coords", sim_coords)]:
        writer.add_image(
            f"nn/{space}/orig_orig", make_grid(sim, False, False), niter_total
        )
        writer.add_image(
            f"nn/{space}/orig_aug", make_grid(sim, False, True), niter_total
        )
        writer.add_image(
            f"nn/{space}/aug_orig", make_grid(sim, True, False), niter_total
        )
        writer.add_image(f"nn/{space}/aug_aug", make_grid(sim, True, True), niter_total)

    ranks = [
        (sim_emb[b].argsort(descending=True) == b).nonzero(as_tuple=True)[0].item()
        for b in range(B)
    ]
    writer.add_scalar("nn/mean_positive_rank", sum(ranks) / len(ranks), niter_total)
    writer.add_histogram("nn/positive_rank_dist", torch.tensor(ranks), niter_total)


def log_nearest_neighbors_orig(
    writer,
    orig,
    sim_emb,
    sim_coords,
    niter_total,
    labels=None,
    pred_labels=None,
    n_queries=5,
    n_neighbors=5,
):
    """
    labels      : int tensor [B], gt labels (-1 = unlabeled). Drives inner border.
    pred_labels : int tensor [B], model predictions.           Drives outer border.
    """
    B = orig.shape[0]
    n_queries = min(n_queries, B)

    imgs = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
    imgs = imgs.cpu().permute(0, 3, 1, 2)  # [B, 3, H, W]

    ol = pred_labels.cpu() if pred_labels is not None else None
    il = labels.cpu() if labels is not None else None
    imgs = _apply_borders_batch(imgs, ol, il)

    query_idx = torch.randperm(B)[:n_queries].tolist()

    def make_grid(sim):
        rows = []
        for qi in query_idx:
            nn_idx = sim[qi].argsort(descending=True).tolist()
            nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
            row = torch.cat([imgs[qi].unsqueeze(0), imgs[nn_idx]], dim=0)
            rows.append(row)
        return vutils.make_grid(
            torch.cat(rows, dim=0), nrow=n_neighbors + 1, padding=2, normalize=False
        )

    writer.add_image("nn_orig/emb", make_grid(sim_emb), niter_total)
    writer.add_image("nn_orig/coords", make_grid(sim_coords), niter_total)


def log_embeddings(
    writer,
    z_batch,
    proj_coords,
    pred_logits,
    labels,
    pred_labels,
    high_conf,
    mem_bank,
    niter_total,
    write_embeddings=False,
):

    if write_embeddings:
        # ---- 1. current batch embeddings (PCA/UMAP done by tensorboard)
        batch_size = z_batch.shape[0]
        batch_labels_str = [
            f"batch_labeled_{l.item()}" if l >= 0 else "batch_unlabeled" for l in labels
        ]
        writer.add_embedding(
            z_batch.detach(),
            metadata=batch_labels_str,
            global_step=niter_total,
            tag="embeddings/batch",
        )

        # ---- 2. memory bank embeddings
        if mem_bank and mem_bank.z.shape[0] > 0:
            mem_labels_str = [
                f"mem_labeled_{l.item()}" if l >= 0 else "mem_unlabeled"
                for l in mem_bank.labels
            ]
            writer.add_embedding(
                mem_bank.z.detach(),
                metadata=mem_labels_str,
                global_step=niter_total,
                tag="embeddings/memory",
            )

        # ---- 3. combined batch + memory with color tags
        if mem_bank and mem_bank.z.shape[0] > 0:
            # sample memory to avoid overwhelming the viz
            sample_size = min(batch_size, mem_bank.z.shape[0])
            idx = torch.randperm(mem_bank.z.shape[0])[:sample_size]
            mem_z_sample = mem_bank.z[idx].detach()
            mem_labels_sample = mem_bank.labels[idx]

            combined_z = torch.cat([z_batch.detach(), mem_z_sample], dim=0)
            combined_meta = [
                f"batch_labeled_{l.item()}" if l >= 0 else "batch_unlabeled"
                for l in labels
            ] + [
                f"mem_labeled_{l.item()}" if l >= 0 else "mem_unlabeled"
                for l in mem_labels_sample
            ]
            writer.add_embedding(
                combined_z,
                metadata=combined_meta,
                global_step=niter_total,
                tag="embeddings/combined",
            )

    # ---- 4. projected 2D coordinates as a scatter image
    # ---- 4. projected 2D coordinates as a scatter image
    fig, ax = plt.subplots(figsize=(6, 6))
    coords_np = proj_coords.detach().cpu().numpy()

    labeled_mask = labels >= 0
    unlabeled_mask = ~labeled_mask

    if unlabeled_mask.any():
        low_conf_mask = unlabeled_mask & ~high_conf
        high_conf_mask = unlabeled_mask & high_conf

        if low_conf_mask.any():
            colors = [
                _label_to_color(int(l), lightness=0.3)
                for l in pred_labels[low_conf_mask].cpu()
            ]
            ax.scatter(
                coords_np[low_conf_mask.cpu(), 0],
                coords_np[low_conf_mask.cpu(), 1],
                c=colors,
                alpha=0.2,
                s=10,
            )

        if high_conf_mask.any():
            colors = [
                _label_to_color(int(l), lightness=0.6)
                for l in pred_labels[high_conf_mask].cpu()
            ]
            ax.scatter(
                coords_np[high_conf_mask.cpu(), 0],
                coords_np[high_conf_mask.cpu(), 1],
                c=colors,
                alpha=0.5,
                s=15,
            )

    if labeled_mask.any():
        colors = [
            _label_to_color(int(l), lightness=1.0) for l in labels[labeled_mask].cpu()
        ]
        ax.scatter(
            coords_np[labeled_mask.cpu(), 0],
            coords_np[labeled_mask.cpu(), 1],
            c=colors,
            alpha=0.85,
            s=30,
            marker="x",
        )

    # # overlay memory coords
    # if mem_bank.coords.shape[0] > 0:
    #     mem_coords_np = mem_bank.coords.detach().cpu().numpy()
    #     ax.scatter(mem_coords_np[:, 0], mem_coords_np[:, 1],
    #                c='gray', alpha=0.2, s=5, label='memory')

    ax.set_xlim(0, GRID_SIZE)
    ax.set_ylim(0, GRID_SIZE)
    ax.legend(loc="upper right")
    ax.set_title(f"Projected Coordinates (iter {niter_total})")
    writer.add_figure("viz/proj_coords", fig, niter_total)
    plt.close(fig)

    # ---- 5. confidence histogram
    with torch.no_grad():
        probs = torch.softmax(pred_logits, dim=1)
        confidence = probs.max(dim=1).values
    writer.add_histogram("train/confidence", confidence, niter_total)
    #writer.add_histogram("train/memory_age", mem_bank.age, niter_total)
    writer.add_histogram("train/proj_coords_x", proj_coords[:, 0].detach(), niter_total)
    writer.add_histogram("train/proj_coords_y", proj_coords[:, 1].detach(), niter_total)
    writer.add_scalar("train/mean_confidence", confidence.mean().item(), niter_total)
