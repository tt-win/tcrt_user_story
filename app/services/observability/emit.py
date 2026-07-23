"""TCRT Event Emit Helpers."""

import logging
from typing import Any, Optional, Dict

from .event_catalog import get_event_def, Outcome, Impact
from .exceptions import (
    UnknownEventCodeError,
    EventDetailsValidationError,
    AuditWriteError,
)


logger = logging.getLogger(__name__)


async def emit_event(
    *,
    event_code: str,
    outcome: Outcome,
    details: Optional[Dict[str, Any]] = None,
    impact: Optional[Impact] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    role: Optional[str] = None,
    action_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    team_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Core event emission - validates and routes to audit/ops.
    
    Raises:
        UnknownEventCodeError: event_code not in catalog
        EventDetailsValidationError: details fail schema validation
        AuditWriteError: audit DB write failed
    """
    # 1. Look up event definition
    event_def = get_event_def(event_code)
    
    # 2. Validate details against schema
    schema = event_def.details_schema
    try:
        validated_details = schema(**(details or {}))
    except Exception as e:
        raise EventDetailsValidationError(
            event_code=event_code,
            message=f"Event {event_code} details validation failed: {e}"
        ) from e
    
    # 3. Validate ops outcome if write_ops
    if event_def.write_ops:
        event_def.validate_ops_outcome(outcome)
    
    # 4. Emit to ops logger (if write_ops)
    if event_def.write_ops:
        _emit_ops(
            event_code=event_code,
            outcome=outcome,
            details=validated_details,
            event_def=event_def,
        )
    
    # 5. Emit to audit DB (if write_audit)
    if event_def.write_audit:
        await _emit_audit(
            event_code=event_code,
            outcome=outcome,
            details=validated_details,
            impact=impact or event_def.default_impact,
            user_id=user_id,
            username=username,
            role=role,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )


async def safe_emit_event(
    *,
    event_code: str,
    outcome: Outcome,
    details: Optional[Dict[str, Any]] = None,
    impact: Optional[Impact] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    role: Optional[str] = None,
    action_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    team_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """
    Safe wrapper for business logic - never raises, logs errors instead.
    
    Returns:
        True if emitted successfully, False if any error (logged via raw logger)
    """
    try:
        await emit_event(
            event_code=event_code,
            outcome=outcome,
            details=details,
            impact=impact,
            user_id=user_id,
            username=username,
            role=role,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return True
    except UnknownEventCodeError as e:
        # Log raw error without going through catalog (prevent recursion)
        logger.error(f"Unknown event code: {event_code}: {e}")
        return False
    except EventDetailsValidationError as e:
        logger.error(f"Event details validation failed for {event_code}: {e}")
        return False
    except AuditWriteError as e:
        logger.error(f"Audit write failed for {event_code}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error emitting {event_code}: {e}")
        return False


async def emit_audit_event(
    *,
    event_code: str,
    outcome: Outcome,
    details: Optional[Dict[str, Any]] = None,
    user_id: int,
    username: str,
    role: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    team_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    impact: Optional[Impact] = None,
) -> bool:
    """Safe emit for audit events (always safe_emit)."""
    return await safe_emit_event(
        event_code=event_code,
        outcome=outcome,
        details=details,
        user_id=user_id,
        username=username,
        role=role,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        team_id=team_id,
        ip_address=ip_address,
        user_agent=user_agent,
        impact=impact,
    )


async def emit_ops_event(
    *,
    event_code: str,
    outcome: Outcome,
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Safe emit for ops-only events (no audit context needed)."""
    return await safe_emit_event(
        event_code=event_code,
        outcome=outcome,
        details=details,
    )


def get_legacy_event_code(action: str, resource: str) -> str:
    """Get legacy audit event code for adapter."""
    from .event_catalog import legacy_event_code
    return legacy_event_code(action, resource)


def _emit_ops(
    *,
    event_code: str,
    outcome: Outcome,
    details: Any,
    event_def: Any,
) -> None:
    """Emit structured log to Python stdlib logging (captured by ring buffer)."""
    level = event_def.get_ops_level(outcome)
    if level is None:
        return
    
    # Build human-readable message from template
    if event_def.brief_template:
        try:
            message = event_def.brief_template.format(**details.model_dump())
        except Exception:
            message = f"{event_code} {outcome.value}"
    else:
        message = f"{event_code} {outcome.value}"
    
    # Add structured suffix for parsing
    suffix_parts = [f"event={event_code}", f"outcome={outcome.value}"]
    for k, v in details.model_dump().items():
        if v is not None:
            suffix_parts.append(f"{k}={v}")
    suffix = " | " + " ".join(suffix_parts)
    
    full_message = message + suffix
    
    # Log at the appropriate level
    log_level = getattr(logging, level.value, logging.INFO)
    logger.log(log_level, full_message)


async def _emit_audit(
    *,
    event_code: str,
    outcome: Outcome,
    details: Any,
    impact: Optional[Impact],
    user_id: Optional[int],
    username: Optional[str],
    role: Optional[str],
    action_type: Optional[str],
    resource_type: Optional[str],
    resource_id: Optional[str],
    team_id: Optional[int],
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    """Emit to audit DB (via existing audit_service)."""
    # Import here to avoid circular dependency
    try:
        from app.audit.audit_service import audit_service
        from app.audit.models import ActionType, ResourceType, AuditSeverity
    except ImportError:
        # If audit service not available, log and raise
        logger.error(f"Audit service not available for {event_code}")
        raise AuditWriteError(event_code=event_code, message="Audit service unavailable")
    
    # Map impact -> legacy severity
    severity_map: dict[Impact, AuditSeverity] = {
        Impact.PRIVILEGED: AuditSeverity.CRITICAL,
        Impact.SENSITIVE: AuditSeverity.WARNING,
        Impact.NOTABLE: AuditSeverity.WARNING,
        Impact.ROUTINE: AuditSeverity.INFO,
    }
    legacy_severity = severity_map.get(impact or Impact.ROUTINE, AuditSeverity.INFO)
    
    # Build action_brief from template
    action_brief = None
    try:
        event_def = get_event_def(event_code)
        if event_def.brief_template:
            action_brief = event_def.brief_template.format(**details.model_dump())
    except Exception:
        pass
    
    # Call audit service (best-effort, doesn't raise on failure)
    try:
        await audit_service.log_action(
            user_id=user_id or 0,
            username=username or "system",
            role=role or "unknown",
            action_type=ActionType(action_type) if action_type else ActionType.READ,
            resource_type=ResourceType(resource_type) if resource_type else ResourceType.SYSTEM,
            resource_id=resource_id or "unknown",
            team_id=team_id,
            details=details.model_dump() if details else None,
            action_brief=action_brief,
            severity=legacy_severity,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as e:
        logger.error(f"Audit write failed for {event_code}: {e}")
        raise AuditWriteError(event_code=event_code, message=str(e)) from e