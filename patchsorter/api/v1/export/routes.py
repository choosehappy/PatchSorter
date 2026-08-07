import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.models import build_table_name

router = APIRouter()

