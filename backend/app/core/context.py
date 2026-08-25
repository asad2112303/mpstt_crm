"""Request-scoped context (request id, user id) shared with logging/audit."""
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def new_request_id() -> str:
    return str(uuid.uuid4())
