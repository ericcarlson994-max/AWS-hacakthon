from dms_core.models import DocumentRow, User


def allowed_groups(user: User) -> list[str]:
    return sorted(set(user.department_ids))


def document_groups(doc: DocumentRow) -> list[str]:
    return [doc.department_id]
