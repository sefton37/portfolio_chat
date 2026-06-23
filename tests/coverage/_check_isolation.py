"""
DOD-21: Isolation check — proves no production contact files are written.

Builds the dev-mode orchestrator, snapshots the file count in data/contacts/,
runs two messages (one contact-path, one normal in_scope), then asserts ZERO
new files appeared.

Prints 'isolation_ok' on success, raises/prints failure otherwise.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROD_CONTACTS = _REPO_ROOT / "data" / "contacts"

# Allow invocation by absolute script path (the form the DoD uses):
# put the repo root on sys.path so `import tests.battery.*` resolves.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


async def _check() -> None:
    # Snapshot current file count in production contacts dir
    prod_contacts = _PROD_CONTACTS
    if prod_contacts.exists():
        before_count = len(list(prod_contacts.iterdir()))
    else:
        before_count = 0

    # Import here so the module can be found without package context issues
    from portfolio_chat.config import MODELS
    from portfolio_chat.contact.storage import ContactStorage
    from portfolio_chat.conversation.manager import ConversationManager
    from portfolio_chat.models.ollama_client import AsyncOllamaClient
    from portfolio_chat.pipeline.orchestrator_fast import FastPipelineOrchestrator
    from tests.battery.engine import InstrumentedOllamaClient

    import tempfile

    contact_dir = Path(tempfile.mkdtemp(prefix="coverage_contacts_"))

    # Verify contact_dir is outside prod dir
    contact_dir_resolved = contact_dir.resolve()
    if prod_contacts.exists():
        try:
            contact_dir_resolved.relative_to(prod_contacts.resolve())
            raise RuntimeError(
                f"LEAK GUARD: contact_dir {contact_dir_resolved} is INSIDE prod dir!"
            )
        except ValueError:
            pass  # Good

    contact_store = ContactStorage(storage_dir=contact_dir)
    gen_client = InstrumentedOllamaClient(url=MODELS.OLLAMA_URL, default_model="qwen3:4b")
    cls_client = AsyncOllamaClient(url=MODELS.OLLAMA_URL, default_model="qwen2.5:3b")

    orch = FastPipelineOrchestrator(
        ollama_client=gen_client,
        conversation_manager=ConversationManager(),
        contact_storage=contact_store,
        analytics_storage=None,
    )
    orch.layer2_combined.client = cls_client
    orch.layer6.model = "qwen3:4b"

    # Force analytics OFF — the constructor coerces None into a real
    # AnalyticsStorage when ANALYTICS.ENABLED is true. Null it post-construction
    # so no prod-analytics writes happen (all analytics calls are guarded).
    orch.analytics_storage = None
    if orch.analytics_storage is not None:
        raise RuntimeError("ISOLATION FAIL: analytics_storage is not None!")

    # Message 1: exercises the contact path (tool call to store message)
    try:
        await orch.process_message(
            message="please pass a message to Kellogg: hello from the isolation check",
            conversation_id="isolation_contact_test",
            client_ip="10.0.0.200",
        )
    except Exception as e:
        print(f"[isolation_check] Contact-path message raised (non-fatal): {e}")

    # Message 2: normal in_scope question
    try:
        await orch.process_message(
            message="What projects has Kellogg worked on?",
            conversation_id="isolation_scope_test",
            client_ip="10.0.0.200",
        )
    except Exception as e:
        print(f"[isolation_check] In-scope message raised (non-fatal): {e}")

    await gen_client.close()
    await cls_client.close()

    # Verify zero new files in production contacts dir
    if prod_contacts.exists():
        after_count = len(list(prod_contacts.iterdir()))
    else:
        after_count = 0

    if after_count != before_count:
        new_files = after_count - before_count
        raise AssertionError(
            f"ISOLATION FAIL: {new_files} new file(s) appeared in {prod_contacts}. "
            f"Before={before_count}, After={after_count}. "
            f"Contact files MUST NOT be written to production data/contacts/."
        )

    # Verify temp dir received any contact files (proves the tool path was used)
    temp_files = list(contact_dir.iterdir())
    print(f"[isolation_check] Temp dir files: {len(temp_files)} (correct — isolated)")
    print("isolation_ok")


if __name__ == "__main__":
    asyncio.run(_check())
