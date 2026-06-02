from __future__ import annotations

import logging
from typing import Any

from google.cloud import firestore

logger = logging.getLogger(__name__)


class ConversationRepository:
    def __init__(self, client: firestore.Client) -> None:
        self._client = client
        logger.info("ConversationRepository initialised with Firestore Native client")

    def create_conversation(
        self,
        conversation_id: str,
        created_at: str,
        user_id: str | None,
        name: str = "New Chat...",
    ) -> None:
        user_id = user_id or "admin"
        logger.debug(
            "create_conversation conversation_id=%s user_id=%s name=%s",
            conversation_id,
            user_id,
            name,
        )
        doc_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
        )
        doc_ref.set({
            "conversation_id": conversation_id,
            "created_at": created_at,
            "updated_at": created_at,
            "user_id": user_id,
            "name": name,
        })
        logger.debug("Conversation created in Firestore conversation_id=%s", conversation_id)

    def put_message(
        self,
        conversation_id: str,
        message_id: str,
        role: str,
        content: str,
        created_at: str,
        attachment: dict | None = None,
        user_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        logger.debug(
            "put_message conversation_id=%s message_id=%s role=%s",
            conversation_id,
            message_id,
            role,
        )
        
        # If user_id is not passed, find it from the conversation document
        if not user_id:
            convs = (
                self._client.collection_group("conversations")
                .where("conversation_id", "==", conversation_id)
                .limit(1)
                .get()
            )
            if convs:
                user_id = convs[0].reference.parent.parent.id
            else:
                user_id = "admin"

        msg_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
            .collection("messages")
            .document(message_id)
        )

        item = {
            "message_id": message_id,
            "role": role,
            "content": content,
            "created_at": created_at,
        }
        if attachment:
            item["attachment"] = attachment
        if attachments:
            item["attachments"] = attachments

        msg_ref.set(item)

    def get_recent_messages(self, conversation_id: str, limit: int) -> list[dict]:
        logger.debug(
            "get_recent_messages conversation_id=%s limit=%d", conversation_id, limit
        )
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if not convs:
            return []
        user_id = convs[0].reference.parent.parent.id

        messages_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
            .collection("messages")
        )
        
        query = messages_ref.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        items = [doc.to_dict() for doc in query.get()]
        items.reverse()  # Restore older first chronological order
        
        logger.debug(
            "get_recent_messages returned %d messages conversation_id=%s",
            len(items),
            conversation_id,
        )
        return items

    def get_context(self, conversation_id: str) -> dict | None:
        logger.debug("get_context conversation_id=%s", conversation_id)
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if not convs:
            return None
        user_id = convs[0].reference.parent.parent.id

        context_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
            .collection("state")
            .document("context")
        )
        
        doc = context_ref.get()
        if doc.exists:
            logger.debug("get_context conversation_id=%s found=True", conversation_id)
            return doc.to_dict()
            
        logger.debug("get_context conversation_id=%s found=False", conversation_id)
        return None

    def set_context(
        self,
        conversation_id: str,
        messages: list[dict],
        ttl_epoch: int,
        updated_at: str,
    ) -> None:
        logger.debug(
            "set_context conversation_id=%s message_count=%d ttl=%d",
            conversation_id,
            len(messages),
            ttl_epoch,
        )
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if convs:
            user_id = convs[0].reference.parent.parent.id
        else:
            user_id = "admin"

        context_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
            .collection("state")
            .document("context")
        )

        context_ref.set({
            "conversationId": conversation_id,
            "messages": messages,
            "ttl": ttl_epoch,
            "updated_at": updated_at,
        })

    def get_user_conversations(self, user_id: str) -> list[dict]:
        logger.debug("get_user_conversations user_id=%s", user_id)
        convs_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
        )
        
        items = [doc.to_dict() for doc in convs_ref.get()]
        items.sort(
            key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True
        )
        return items

    def get_conversation_meta(self, conversation_id: str) -> dict | None:
        logger.debug("get_conversation_meta conversation_id=%s", conversation_id)
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if convs:
            return convs[0].to_dict()
        return None

    def update_conversation(
        self, conversation_id: str, name: str, updated_at: str
    ) -> None:
        logger.debug(
            "update_conversation conversation_id=%s name=%s", conversation_id, name
        )
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if convs:
            convs[0].reference.update({
                "name": name,
                "updated_at": updated_at,
            })

    def get_all_messages(self, conversation_id: str) -> list[dict]:
        logger.debug("get_all_messages conversation_id=%s", conversation_id)
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if not convs:
            return []
        user_id = convs[0].reference.parent.parent.id

        messages_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
            .collection("messages")
        )
        
        docs = messages_ref.order_by("created_at", direction=firestore.Query.ASCENDING).get()
        return [doc.to_dict() for doc in docs]

    def delete_conversation(self, conversation_id: str) -> None:
        logger.debug("delete_conversation conversation_id=%s", conversation_id)
        convs = (
            self._client.collection_group("conversations")
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        if not convs:
            return
        user_id = convs[0].reference.parent.parent.id

        conv_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
        )
        
        # Delete all messages in the messages subcollection
        for msg in conv_ref.collection("messages").get():
            msg.reference.delete()
            
        # Delete all documents in the state subcollection
        for st in conv_ref.collection("state").get():
            st.reference.delete()
            
        # Delete the main conversation metadata document
        conv_ref.delete()

    def put_rag_document(
        self,
        user_id: str,
        document_id: str,
        filename: str,
        chunks_ingested: int,
        created_at: str,
        status: str = "ready",
    ) -> None:
        logger.debug(
            "put_rag_document user_id=%s document_id=%s filename=%s status=%s",
            user_id,
            document_id,
            filename,
            status,
        )
        doc_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("rag_documents")
            .document(document_id)
        )
        
        doc_ref.set({
            "document_id": document_id,
            "user_id": user_id,
            "filename": filename,
            "source_doc": filename,
            "chunks_ingested": chunks_ingested,
            "status": status,
            "created_at": created_at,
            "updated_at": created_at,
        })

    def update_rag_document_status(
        self,
        user_id: str,
        document_id: str,
        status: str,
        chunks_ingested: int,
        updated_at: str,
    ) -> None:
        logger.debug(
            "update_rag_document_status user_id=%s document_id=%s status=%s chunks=%d",
            user_id,
            document_id,
            status,
            chunks_ingested,
        )
        doc_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("rag_documents")
            .document(document_id)
        )
        try:
            doc_ref.update({
                "status": status,
                "chunks_ingested": chunks_ingested,
                "updated_at": updated_at,
            })
        except Exception as exc:
            logger.warning(
                "RAG document not found for update user_id=%s document_id=%s. Error: %s",
                user_id, document_id, exc
            )

    def list_rag_documents(self, user_id: str) -> list[dict]:
        logger.debug("list_rag_documents user_id=%s", user_id)
        docs_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("rag_documents")
        )
        
        items = [doc.to_dict() for doc in docs_ref.get()]
        items.sort(
            key=lambda x: x.get("created_at", ""), reverse=True
        )
        return items
