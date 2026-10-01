"""
assistant_threads - Shape B (misc/AI, A6, AI-60). Payload in the model's docstring.

Nothing to add to EncryptedRepository: the two-step insert, the AAD and user
scoping come with it. assistant_service.history is the only caller.
"""

from app.db.models import AssistantThread
from app.db.repositories.encrypted_repository import EncryptedRepository


class AssistantThreadRepository(EncryptedRepository):
    model = AssistantThread
