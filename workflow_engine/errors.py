"""Custom exceptions for the workflow engine."""


class WorkflowError(Exception):
    """Base class for workflow related errors."""


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow definition fails validation."""


class SchedulerError(WorkflowError):
    """Raised when scheduling operations fail."""


class PersistenceError(WorkflowError):
    """Raised when persistence layer encounters an error."""


class ExecutionFailed(WorkflowError):
    """Raised when execution fails after retries."""
