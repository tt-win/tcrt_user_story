from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends

from .audit import AuditAccessBoundary, get_audit_access_boundary
from .main import MainAccessBoundary, get_main_access_boundary
from .usm import UsmAccessBoundary, get_usm_access_boundary


@dataclass(frozen=True)
class CrossDatabaseCoordinator:
    main: MainAccessBoundary
    audit: AuditAccessBoundary
    usm: UsmAccessBoundary


def get_cross_database_coordinator(
    main: MainAccessBoundary = Depends(get_main_access_boundary),
    audit: AuditAccessBoundary = Depends(get_audit_access_boundary),
    usm: UsmAccessBoundary = Depends(get_usm_access_boundary),
) -> CrossDatabaseCoordinator:
    return CrossDatabaseCoordinator(main=main, audit=audit, usm=usm)

