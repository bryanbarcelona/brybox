from brybox.core.models.email import ProcessingContext, ProcessResult


def manual_click_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Placeholder for emails requiring manual action — never deletes."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='Manual click required.',
        can_delete=False,
    )


def ignore_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Signals to the engine to skip this email and leave it in the inbox."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=False,
    )


def delete_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Signals to the engine that this email should be deleted."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=True,
    )
