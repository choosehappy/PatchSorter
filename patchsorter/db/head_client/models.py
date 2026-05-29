from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, Float, ForeignKey,
    Index, Integer, LargeBinary, SmallInteger, Text, UniqueConstraint, Uuid, event
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func, text
from sqlalchemy.types import TIMESTAMP
from typing import Dict, Tuple

from patchsorter.db.head_client.table_names import (
    patch_table, pred_patch_table, confusion_matrix_table,
)

from patchsorter.config.constants import PredPatchSuffix, SettingType


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "project"

    project_id   = Column(Integer, primary_key=True, autoincrement=True)
    project_name = Column(Text, nullable=False)
    description  = Column(Text)

    images        = relationship("Image",       back_populates="project")
    label_classes = relationship("LabelClass",  back_populates="project")
    settings      = relationship("Setting",     back_populates="project")


class Image(Base):
    __tablename__ = "image"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
    )

    image_id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id        = Column(Integer, ForeignKey("project.project_id"), nullable=False)
    name              = Column(Text, nullable=False)
    image_path        = Column(Text, nullable=False)
    upload_ts         = Column(TIMESTAMP, nullable=False, server_default=func.now())
    base_mag          = Column(Float, nullable=False)
    base_width        = Column(Integer, nullable=False)
    base_height       = Column(Integer, nullable=False)
    deepzoom_tilesize = Column(Integer, nullable=False)
    embedding_x       = Column(Float)
    embedding_y       = Column(Float)
    group_id          = Column(Integer)
    train_test_split  = Column(Integer)

    project = relationship("Project", back_populates="images")


class LabelClass(Base):
    __tablename__ = "label_class"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
    )

    label_class_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id     = Column(Integer, ForeignKey("project.project_id"))
    name           = Column(Text, nullable=False)
    color_code     = Column(Text)
    event_ts       = Column(TIMESTAMP, nullable=False, server_default=func.now())

    project = relationship("Project", back_populates="label_classes")


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("project_id", "setting_key", name="uq_project_setting"),
        CheckConstraint(
            f"setting_type IN ({', '.join(repr(t.value) for t in SettingType)})",
            name="ck_setting_type",
        ),
        CheckConstraint(
            f"setting_type != '{SettingType.ENUM}' OR allowed_values IS NOT NULL",
            name="chk_enum_has_values",
        ),
    )

    setting_id     = Column(Integer, primary_key=True, autoincrement=True)
    project_id     = Column(Integer, ForeignKey("project.project_id", name="fk_project"))
    setting_key    = Column(Text, nullable=False)
    setting_value  = Column(Text, nullable=False)
    default_value  = Column(Text, nullable=False)
    setting_type   = Column(Text, nullable=False)
    allowed_values = Column(Text)
    disabled       = Column(Boolean, nullable=False, server_default="false")

    project = relationship("Project", back_populates="settings")


class Log(Base):
    __tablename__ = "log"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())
    level     = Column(Text, nullable=False, server_default="INFO")
    message   = Column(Text, nullable=False, server_default="")


# ---------------------------------------------------------------------------
# Per-project model factories
#
# Each project has its own set of distributed tables named after the project
# ID (e.g. ``project1_patch``).  SQLAlchemy models for these tables are
# created on demand using ``type()`` so they are properly registered in
# ``Base.metadata`` and can drive ``create_all`` / ``drop_all`` DDL.
#
# Results are cached to prevent duplicate registrations in the mapper
# registry when the same project_id is requested more than once.
# ---------------------------------------------------------------------------

_patch_cache: Dict[int, type] = {}
_pred_patch_latest_cache: Dict[int, type] = {}
_pred_patch_last_cache: Dict[int, type] = {}
_cm_cache: Dict[Tuple[int, int], type] = {}


def patch_model(project_id: int) -> type:
    """Return the ORM model class for ``project{N}_patch``."""
    if project_id not in _patch_cache:
        _patch_cache[project_id] = type(
            f"Patch{project_id}",
            (Base,),
            {
                "__tablename__": patch_table(project_id),
                "patch_id":       Column(BigInteger, primary_key=True, autoincrement=True),
                "patch_uid":      Column(Uuid, unique=True),
                "label_class_id": Column(SmallInteger, nullable=False),
                "image_id":       Column(Integer, nullable=False),
                "downsample_factor": Column(Float, nullable=False),
                "patch_image":    Column(LargeBinary, nullable=False),
            },
        )
    return _patch_cache[project_id]


def pred_patch_model(project_id: int, suffix: str) -> type:
    """Return the ORM model class for ``project{N}_pred_patch_{suffix}``.

    Args:
        project_id: Integer project ID.
        suffix: Either ``'latest'`` or ``'last'``.
    """
    cache = _pred_patch_latest_cache if suffix == PredPatchSuffix.LATEST else _pred_patch_last_cache
    if project_id not in cache:
        cache[project_id] = type(
            f"PredPatch{suffix.capitalize()}{project_id}",
            (Base,),
            {
                "__tablename__": pred_patch_table(project_id, suffix),
                "patch_id":       Column(BigInteger, primary_key=True),
                "embed_x":        Column(Float, nullable=False),
                "embed_y":        Column(Float, nullable=False),
                "grid_cell_i":    Column(SmallInteger, nullable=False),
                "grid_cell_j":    Column(SmallInteger, nullable=False),
                "event_ts":       Column(TIMESTAMP, nullable=False, server_default=func.now()),
                "label_class_id": Column(SmallInteger, nullable=False),
            },
        )
    return cache[project_id]


def confusion_matrix_model(project_id: int, level: int) -> type:
    """Return the ORM model class for ``project{N}_confusion_matrix_l{level}``.

    Args:
        project_id: Integer project ID.
        level: Hierarchical grid level (8–12 inclusive).
    """
    key = (project_id, level)
    if key not in _cm_cache:
        table_name = confusion_matrix_table(project_id, level)
        _cm_cache[key] = type(
            f"ConfusionMatrix{project_id}L{level}",
            (Base,),
            {
                "__tablename__": table_name,
                "__table_args__": (
                    Index(
                        f"idx_cm_p{project_id}_l{level}_nonpositive",
                        "count",
                        postgresql_where=text("count <= 0"),
                    ),
                ),
                "shard_id":    Column(BigInteger, nullable=False, primary_key=True),
                "grid_cell_i": Column(SmallInteger, nullable=False, primary_key=True),
                "grid_cell_j": Column(SmallInteger, nullable=False, primary_key=True),
                "bucket_date": Column(Date, nullable=False),
                "pred_label":  Column(SmallInteger, nullable=False, primary_key=True),
                "gt_label":    Column(SmallInteger, nullable=False, primary_key=True),
                "count":       Column(Integer, nullable=False),
            },
        )
    return _cm_cache[key]


def all_project_models(project_id: int) -> list:
    """Return all ORM model classes for the given project, in creation order."""
    return [
        patch_model(project_id),
        pred_patch_model(project_id, PredPatchSuffix.LATEST),
        pred_patch_model(project_id, PredPatchSuffix.LAST),
        *[confusion_matrix_model(project_id, lvl) for lvl in range(8, 13)],
    ]
