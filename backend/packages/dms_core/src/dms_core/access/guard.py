from dms_core.models import DocumentRow, User

WRITER_ROLES = frozenset({"contributor", "admin"})


def can_read(user: User, doc: DocumentRow) -> bool:
    return doc.department_id in user.department_ids


def can_write(user: User, doc: DocumentRow) -> bool:
    return user.role_in(doc.department_id) in WRITER_ROLES
