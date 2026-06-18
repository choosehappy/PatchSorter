import atexit
import logging
import os
import torch

logger = logging.getLogger(__name__)

# safetensors checkpoint saving (preferred) with torch.save fallback
try:
    from safetensors.torch import save_file as _safetensors_save_file, load_file as _safetensors_load_file
    _USE_SAFETENSORS = True
except Exception:
    _safetensors_save_file = None
    _safetensors_load_file = None
    _USE_SAFETENSORS = False
    logger.warning("safetensors not available; falling back to torch.save for checkpoints")


def save_models_checkpoint(dir_path: str = "./model", timestamp: str = None ,backbone=None, joint_head=None) -> None:
    """Save backbone and joint_head weights to `dir_path`.

    If `timestamp` is provided, append it to filenames to avoid overwriting.
    Prefers safetensors if available, otherwise falls back to `torch.save`.
    """
    os.makedirs(dir_path, exist_ok=True)
    try:
        if timestamp is None:
            ts = ""
        else:
            ts = f"_{timestamp}"

        if _USE_SAFETENSORS and _safetensors_save_file is not None:
            backbone_state = {
                f"backbone.{k}": v.detach().cpu()
                for k, v in backbone.state_dict().items()
                if isinstance(v, torch.Tensor)
            }
            joint_state = {
                f"joint_head.{k}": v.detach().cpu()
                for k, v in joint_head.state_dict().items()
                if isinstance(v, torch.Tensor)
            }
            _safetensors_save_file(backbone_state, os.path.join(dir_path, f"backbone{ts}.safetensors"))
            _safetensors_save_file(joint_state, os.path.join(dir_path, f"joint_head{ts}.safetensors"))
            logger.info("Saved safetensors checkpoints to %s", dir_path)
        else:
            fname = os.path.join(dir_path, f"models{ts}.pt")
            torch.save(
                {"backbone": backbone.state_dict(), "joint_head": joint_head.state_dict()},
                fname,
            )
            logger.info("Saved torch checkpoint to %s", fname)
    except Exception as e:
        logger.exception("Failed to save model checkpoint: %s", e)


# loader for checkpoints
def load_models_checkpoint(dir_path: str = "./model", backbone=None, joint_head=None) -> None:
    """Load the most recent checkpoint for `backbone` and `joint_head` from `dir_path`.

    Prefers safetensors files if available, otherwise looks for .pt files.
    """
    if not os.path.isdir(dir_path):
        logger.info("Checkpoint directory %s does not exist, skipping load", dir_path)
        return

    # Try safetensors first
    try:
        if _USE_SAFETENSORS and _safetensors_load_file is not None:
            # find latest backbone*.safetensors
            files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.startswith("backbone") and f.endswith(".safetensors")]
            if files:
                latest_backbone = max(files, key=os.path.getmtime)
                bdict = _safetensors_load_file(latest_backbone)
                # strip prefix "backbone." from keys
                backbone_state = {k.split("backbone.", 1)[1]: v for k, v in bdict.items() if k.startswith("backbone.")}
                backbone.load_state_dict(backbone_state, strict=False)
                logger.info("Loaded backbone safetensors from %s", latest_backbone)

            files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.startswith("joint_head") and f.endswith(".safetensors")]
            if files:
                latest_joint = max(files, key=os.path.getmtime)
                jdict = _safetensors_load_file(latest_joint)
                joint_state = {k.split("joint_head.", 1)[1]: v for k, v in jdict.items() if k.startswith("joint_head.")}
                joint_head.load_state_dict(joint_state, strict=False)
                logger.info("Loaded joint_head safetensors from %s", latest_joint)
            return
    except Exception:
        logger.exception("Failed to load safetensors checkpoint, will try torch .pt files")

    # Fallback: look for latest .pt
    try:
        files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.endswith(".pt")]
        if not files:
            logger.info("No .pt checkpoints found in %s", dir_path)
            return
        latest = max(files, key=os.path.getmtime)
        state = torch.load(latest, map_location=DEVICE)
        if isinstance(state, dict):
            if "backbone" in state:
                backbone.load_state_dict(state["backbone"], strict=False)
            if "joint_head" in state:
                joint_head.load_state_dict(state["joint_head"], strict=False)
        logger.info("Loaded torch checkpoint from %s", latest)
    except Exception:
        logger.exception("Failed to load torch checkpoint from %s", dir_path)


# ensure we save on normal exit as well
atexit.register(save_models_checkpoint)