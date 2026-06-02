from __future__ import annotations

import logging
from typing import Any

from azure.cosmos.exceptions import CosmosResourceNotFoundError, CosmosHttpResponseError

logger = logging.getLogger(__name__)


class ConversationRepository:
    def __init__(self, container: Any) -> None:
        self._container = container
        logger.info("ConversationRepository initialised with Cosmos container")

    def create_conversation(
        self,
        conversation_id: str,
        created_at: str,
        user_id: str | None,
        name: str = "New Chat...",
    ) -> None:
        logger.debug(
            "create_conversation conversation_id=%s user_id=%s name=%s",
            conversation_id,
            user_id,
            name,
        )
        item = {
            "id": f"{conversation_id}_META",
            "conversationId": conversation_id,
            "pk": f"CONV#{conversation_id}",
            "sk": "META",
            "type": "META",
            "conversation_id": conversation_id,
            "created_at": created_at,
            "updated_at": created_at,
            "name": name,
        }
        if user_id:
            item["user_id"] = user_id

        try:
            self._container.upsert_item(body=item)
            logger.debug("Conversation created in Cosmos DB conversation_id=%s", conversation_id)
        except CosmosHttpResponseError:
            logger.exception(
                "CosmosDB error creating conversation conversation_id=%s",
                conversation_id,
            )
            raise

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
        item = {
            "id": f"{conversation_id}_MSG_{message_id}",
            "conversationId": conversation_id,
            "pk": f"CONV#{conversation_id}",
            "sk": f"MSG#{created_at}#{message_id}",
            "type": "MSG",
            "message_id": message_id,
            "role": role,
            "content": content,
            "created_at": created_at,
        }
        if attachment:
            item["attachment"] = attachment
        if attachments:
            item["attachments"] = attachments
        if user_id:
            item["user_id"] = user_id

        self._container.upsert_item(body=item)

    def get_recent_messages(self, conversation_id: str, limit: int) -> list[dict]:
        logger.debug(
            "get_recent_messages conversation_id=%s limit=%d", conversation_id, limit
        )
        query = (
            "SELECT * FROM c WHERE c.conversationId = @convId AND c.type = 'MSG' "
            "ORDER BY c.created_at DESC"
        )
        params = [
            {"name": "@convId", "value": conversation_id}
        ]
        items = list(self._container.query_items(
            query=query,
            parameters=params,
            partition_key=conversation_id,
        ))
        
        # Trim to limit and reverse to restore chronological order (older first)
        items = items[:limit]
        items.reverse()
        
        logger.debug(
            "get_recent_messages returned %d messages conversation_id=%s",
            len(items),
            conversation_id,
        )
        return items

    def get_context(self, conversation_id: str) -> dict | None:
        logger.debug("get_context conversation_id=%s", conversation_id)
        try:
            item = self._container.read_item(
                item=f"{conversation_id}_CTX",
                partition_key=conversation_id,
            )
            logger.debug(
                "get_context conversation_id=%s found=True", conversation_id
            )
            return item
        except CosmosResourceNotFoundError:
            logger.debug(
                "get_context conversation_id=%s found=False", conversation_id
            )
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
        item = {
            "id": f"{conversation_id}_CTX",
            "conversationId": conversation_id,
            "pk": f"CONV#{conversation_id}",
            "sk": "CTX",
            "type": "CTX",
            "messages": messages,
            "ttl": ttl_epoch,
            "updated_at": updated_at,
        }
        self._container.upsert_item(body=item)

    def get_user_conversations(self, user_id: str) -> list[dict]:
        logger.debug("get_user_conversations user_id=%s", user_id)
        query = (
            "SELECT * FROM c WHERE c.user_id = @userId AND c.type = 'META'"
        )
        params = [{"name": "@userId", "value": user_id}]
        items = list(self._container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ))
        items.sort(
            key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True
        )
        return items

    def get_conversation_meta(self, conversation_id: str) -> dict | None:
        logger.debug("get_conversation_meta conversation_id=%s", conversation_id)
        try:
            return self._container.read_item(
                item=f"{conversation_id}_META",
                partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            return None

    def update_conversation(
        self, conversation_id: str, name: str, updated_at: str
    ) -> None:
        logger.debug(
            "update_conversation conversation_id=%s name=%s", conversation_id, name
        )
        meta = self.get_conversation_meta(conversation_id)
        if meta:
            meta["name"] = name
            meta["updated_at"] = updated_at
            self._container.upsert_item(body=meta)

    def get_all_messages(self, conversation_id: str) -> list[dict]:
        logger.debug("get_all_messages conversation_id=%s", conversation_id)
        query = (
            "SELECT * FROM c WHERE c.conversationId = @convId AND c.type = 'MSG' "
            "ORDER BY c.created_at ASC"
        )
        params = [
            {"name": "@convId", "value": conversation_id}
        ]
        return list(self._container.query_items(
            query=query,
            parameters=params,
            partition_key=conversation_id,
        ))

    def delete_conversation(self, conversation_id: str) -> None:
        logger.debug("delete_conversation conversation_id=%s", conversation_id)
        query = (
            "SELECT c.id FROM c WHERE c.conversationId = @convId"
        )
        params = [
            {"name": "@convId", "value": conversation_id}
        ]
        items = list(self._container.query_items(
            query=query,
            parameters=params,
            partition_key=conversation_id,
        ))
        
        for item in items:
            try:
                self._container.delete_item(
                    item=item["id"],
                    partition_key=conversation_id,
                )
            except CosmosResourceNotFoundError:
                pass

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
        item = {
            "id": f"{user_id}_RAGDOC_{document_id}",
            "conversationId": f"_user_{user_id}",
            "pk": f"USER#{user_id}",
            "sk": f"RAGDOC#{created_at}#{document_id}",
            "type": "RAGDOC",
            "user_id": user_id,
            "document_id": document_id,
            "filename": filename,
            "source_doc": filename,
            "chunks_ingested": chunks_ingested,
            "status": status,
            "created_at": created_at,
            "updated_at": created_at,
        }
        self._container.upsert_item(body=item)

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
        doc_id = f"{user_id}_RAGDOC_{document_id}"
        partition_key = f"_user_{user_id}"
        try:
            item = self._container.read_item(item=doc_id, partition_key=partition_key)
            item["status"] = status
            item["chunks_ingested"] = chunks_ingested
            item["updated_at"] = updated_at
            self._container.upsert_item(body=item)
        except CosmosResourceNotFoundError:
            logger.warning("RAG document not found for update user_id=%s document_id=%s", user_id, document_id)

    def list_rag_documents(self, user_id: str) -> list[dict]:
        logger.debug("list_rag_documents user_id=%s", user_id)
        query = (
            "SELECT * FROM c WHERE c.user_id = @userId AND c.type = 'RAGDOC'"
        )
        params = [{"name": "@userId", "value": user_id}]
        items = list(self._container.query_items(
            query=query,
            parameters=params,
            partition_key=f"_user_{user_id}",
        ))
        
        # Sort newest first
        items.sort(
            key=lambda x: x.get("created_at", ""), reverse=True
        )
        return items
