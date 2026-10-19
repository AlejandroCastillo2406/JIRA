# Import centralizado solo para registrar metadata SQLAlchemy/Alembic.
from app.modules.users.models import PermissionModel, Role, User  # noqa: F401
from app.modules.auth.models import UserSession  # noqa: F401
from app.modules.workflows.models import IssueType, Priority, Workflow, WorkflowStatus, WorkflowTransition  # noqa: F401
from app.modules.projects.models import Project, ProjectMember  # noqa: F401
from app.modules.issues.models import Issue, IssueBlock, IssueImage  # noqa: F401
from app.modules.comments.models import Comment  # noqa: F401
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.notifications.models import Notification, OutboxEvent  # noqa: F401
