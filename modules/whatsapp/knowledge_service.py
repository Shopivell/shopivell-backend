"""
Knowledge Service for AI Sales Bot

Handles:
- FAQ sync to knowledge base
- Product sync to knowledge base
- Semantic search for bot retrieval
- Embedding generation
"""

import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from utils.embeddings import embed_text, embed_texts, active_embedding_model, EMBEDDING_DIM

from .models import CompanyKnowledge, FAQ, StoreBotConfig

logger = logging.getLogger(__name__)

# Embedding provider/model is now resolved centrally in utils.embeddings
# (retry/backoff, provider failover, usage tracking). See that module.
EMBEDDING_DIMENSIONS = EMBEDDING_DIM


class KnowledgeService:
    """Service for managing knowledge base and semantic search"""

    def __init__(self, store_id: UUID):
        self.store_id = store_id

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate an embedding via the central, resilient embeddings layer."""
        return embed_text(text, agent_name="knowledge_embeddings")

    def _generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts via the central layer."""
        return embed_texts(texts, agent_name="knowledge_embeddings")

    # =========================================================================
    # FAQ Management
    # =========================================================================

    def sync_faq_to_knowledge(
        self,
        db: Session,
        faq: FAQ
    ) -> CompanyKnowledge:
        """
        Sync a single FAQ to the knowledge base.
        Creates or updates the knowledge entry with embedding.
        """
        # Format FAQ content for embedding
        content = faq.to_knowledge_content()
        title = f"FAQ: {faq.question[:100]}"

        # Generate embedding
        embedding = self._generate_embedding(content)

        # Check if knowledge entry exists
        if faq.knowledge_id:
            knowledge = db.query(CompanyKnowledge).filter(
                CompanyKnowledge.id == faq.knowledge_id
            ).first()

            if knowledge:
                # Update existing entry
                knowledge.title = title
                knowledge.content = content
                knowledge.category = faq.category or "faq"
                knowledge.embedding = embedding
                knowledge.embedding_model = active_embedding_model()
                knowledge.is_active = faq.is_active
                knowledge.last_synced_at = datetime.utcnow()
                knowledge.updated_at = datetime.utcnow()

                db.commit()
                db.refresh(knowledge)

                logger.info(f"Updated knowledge entry for FAQ {faq.id}")
                return knowledge

        # Create new knowledge entry
        knowledge = CompanyKnowledge(
            store_id=self.store_id,
            title=title,
            content=content,
            category=faq.category or "faq",
            content_type="faq",
            source_id=faq.id,
            embedding=embedding,
            embedding_model=active_embedding_model(),
            is_active=faq.is_active,
            last_synced_at=datetime.utcnow()
        )
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)

        # Update FAQ with knowledge_id
        faq.knowledge_id = knowledge.id
        faq.last_synced_at = datetime.utcnow()
        db.commit()

        logger.info(f"Created knowledge entry for FAQ {faq.id}")
        return knowledge

    def sync_all_faqs_to_knowledge(self, db: Session) -> int:
        """
        Sync all active FAQs to the knowledge base.
        Returns the number of FAQs synced.
        """
        faqs = db.query(FAQ).filter(
            FAQ.store_id == self.store_id,
            FAQ.is_active == True
        ).all()

        synced_count = 0
        for faq in faqs:
            try:
                self.sync_faq_to_knowledge(db, faq)
                synced_count += 1
            except Exception as e:
                logger.error(f"Error syncing FAQ {faq.id}: {e}")

        logger.info(f"Synced {synced_count} FAQs to knowledge base for store {self.store_id}")
        return synced_count

    def delete_faq_knowledge(self, db: Session, faq: FAQ):
        """Delete knowledge entry for a FAQ"""
        if faq.knowledge_id:
            knowledge = db.query(CompanyKnowledge).filter(
                CompanyKnowledge.id == faq.knowledge_id
            ).first()

            if knowledge:
                db.delete(knowledge)
                faq.knowledge_id = None
                faq.last_synced_at = None
                db.commit()

                logger.info(f"Deleted knowledge entry for FAQ {faq.id}")

    # =========================================================================
    # Product Sync
    # =========================================================================

    def sync_products_to_knowledge(self, db: Session) -> int:
        """
        Sync all active products to the knowledge base.
        Returns the number of products synced.
        """
        from modules.products.models import Product

        products = db.query(Product).filter(
            Product.store_id == self.store_id,
            func.lower(Product.status) == "active"
        ).all()

        synced_count = 0
        batch_size = 50
        batch_texts = []
        batch_products = []

        for product in products:
            # Format product content
            content = self._format_product_for_knowledge(product)
            batch_texts.append(content)
            batch_products.append(product)

            if len(batch_texts) >= batch_size:
                synced_count += self._sync_product_batch(db, batch_texts, batch_products)
                batch_texts = []
                batch_products = []

        # Sync remaining batch
        if batch_texts:
            synced_count += self._sync_product_batch(db, batch_texts, batch_products)

        logger.info(f"Synced {synced_count} products to knowledge base for store {self.store_id}")
        return synced_count

    def _format_product_for_knowledge(self, product) -> str:
        """Format product for knowledge base embedding"""
        parts = [
            f"Product: {product.title}",
        ]

        if product.description:
            parts.append(f"Description: {product.description}")

        if getattr(product, 'price', None) is not None:
            parts.append(f"Price: ${product.price}")

        if hasattr(product, 'category') and product.category:
            parts.append(f"Category: {product.category}")

        if hasattr(product, 'sku') and product.sku:
            parts.append(f"Stock Code: {product.sku}")

        if getattr(product, 'barcode', None):
            parts.append(f"Barcode: {product.barcode}")
        if getattr(product, 'branch', None):
            parts.append(f"Branch: {product.branch}")
        if getattr(product, 'in_stock', None) is not None:
            parts.append(f"In Stock: {'Yes' if product.in_stock else 'No'}")

        return "\n".join(parts)

    def _sync_product_batch(
        self,
        db: Session,
        texts: List[str],
        products: List
    ) -> int:
        """Sync a batch of products with embeddings"""
        try:
            embeddings = self._generate_embeddings_batch(texts)

            for i, product in enumerate(products):
                # Check if knowledge entry exists for this product
                existing = db.query(CompanyKnowledge).filter(
                    CompanyKnowledge.store_id == self.store_id,
                    CompanyKnowledge.content_type == "product",
                    CompanyKnowledge.source_id == product.id
                ).first()

                if existing:
                    # Update
                    existing.title = f"Product: {product.title}"
                    existing.content = texts[i]
                    existing.branch = product.branch
                    existing.embedding = embeddings[i]
                    existing.embedding_model = active_embedding_model()
                    existing.last_synced_at = datetime.utcnow()
                    existing.updated_at = datetime.utcnow()
                else:
                    # Create
                    knowledge = CompanyKnowledge(
                        store_id=self.store_id,
                        title=f"Product: {product.title}",
                        content=texts[i],
                        category="product",
                        content_type="product",
                        branch=product.branch,
                        source_id=product.id,
                        embedding=embeddings[i],
                        embedding_model=active_embedding_model(),
                        is_active=True,
                        last_synced_at=datetime.utcnow()
                    )
                    db.add(knowledge)

            db.commit()
            return len(products)

        except Exception as e:
            logger.error(f"Error syncing product batch: {e}")
            db.rollback()
            return 0

    # =========================================================================
    # Manual Knowledge Management
    # =========================================================================

    def add_manual_knowledge(
        self,
        db: Session,
        content: str,
        title: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        priority: float = 1.0
    ) -> CompanyKnowledge:
        """Add a manual knowledge entry"""
        embedding = self._generate_embedding(content)

        knowledge = CompanyKnowledge(
            store_id=self.store_id,
            title=title,
            content=content,
            category=category,
            tags=tags,
            content_type="manual",
            embedding=embedding,
            embedding_model=active_embedding_model(),
            priority=priority,
            is_active=True,
            last_synced_at=datetime.utcnow()
        )
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)

        logger.info(f"Added manual knowledge entry {knowledge.id} for store {self.store_id}")
        return knowledge

    def update_knowledge(
        self,
        db: Session,
        knowledge_id: UUID,
        content: Optional[str] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        priority: Optional[float] = None,
        is_active: Optional[bool] = None
    ) -> Optional[CompanyKnowledge]:
        """Update a knowledge entry"""
        knowledge = db.query(CompanyKnowledge).filter(
            CompanyKnowledge.id == knowledge_id,
            CompanyKnowledge.store_id == self.store_id
        ).first()

        if not knowledge:
            return None

        if content is not None:
            knowledge.content = content
            # Re-generate embedding for new content
            knowledge.embedding = self._generate_embedding(content)
            knowledge.embedding_model = active_embedding_model()

        if title is not None:
            knowledge.title = title
        if category is not None:
            knowledge.category = category
        if tags is not None:
            knowledge.tags = tags
        if priority is not None:
            knowledge.priority = priority
        if is_active is not None:
            knowledge.is_active = is_active

        knowledge.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(knowledge)

        logger.info(f"Updated knowledge entry {knowledge_id}")
        return knowledge

    def delete_knowledge(self, db: Session, knowledge_id: UUID) -> bool:
        """Delete a knowledge entry (soft delete by setting is_active=False)"""
        knowledge = db.query(CompanyKnowledge).filter(
            CompanyKnowledge.id == knowledge_id,
            CompanyKnowledge.store_id == self.store_id
        ).first()

        if not knowledge:
            return False

        knowledge.is_active = False
        knowledge.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Soft deleted knowledge entry {knowledge_id}")
        return True

    # =========================================================================
    # Semantic Search
    # =========================================================================

    def search_knowledge(
        self,
        db: Session,
        query: str,
        threshold: float = 0.4,
        limit: int = 5,
        content_types: Optional[List[str]] = None
    ) -> List[Tuple[CompanyKnowledge, float]]:
        """
        Semantic search in the knowledge base.
        Returns list of (knowledge, similarity_score) tuples.
        """
        # Generate query embedding
        query_embedding = self._generate_embedding(query)

        # Build query
        base_query = db.query(
            CompanyKnowledge,
            (1 - CompanyKnowledge.embedding.cosine_distance(query_embedding)).label("similarity")
        ).filter(
            CompanyKnowledge.store_id == self.store_id,
            CompanyKnowledge.is_active == True
        )

        if content_types:
            base_query = base_query.filter(
                CompanyKnowledge.content_type.in_(content_types)
            )

        # Order by similarity and limit
        results = base_query.order_by(
            (1 - CompanyKnowledge.embedding.cosine_distance(query_embedding)).desc()
        ).limit(limit).all()

        # Filter by threshold
        filtered_results = [
            (knowledge, similarity)
            for knowledge, similarity in results
            if similarity >= threshold
        ]

        return filtered_results

    def get_context_for_query(
        self,
        db: Session,
        query: str,
        config: Optional[StoreBotConfig] = None
    ) -> Dict[str, Any]:
        """
        Get context for a bot query.
        Returns context dict with results and confidence info.
        """
        threshold = config.similarity_threshold if config else 0.4

        results = self.search_knowledge(
            db=db,
            query=query,
            threshold=threshold,
            limit=5
        )

        if not results:
            return {
                "context": None,
                "sources": [],
                "confidence": 0,
                "fallback_triggered": True
            }

        # Build context from results
        context_parts = []
        sources = []
        max_confidence = 0

        for knowledge, similarity in results:
            context_parts.append(knowledge.content)
            sources.append({
                "id": str(knowledge.id),
                "title": knowledge.title,
                "type": knowledge.content_type,
                "similarity": similarity
            })
            max_confidence = max(max_confidence, similarity)

        return {
            "context": "\n\n---\n\n".join(context_parts),
            "sources": sources,
            "confidence": max_confidence,
            "fallback_triggered": max_confidence < threshold
        }

    # =========================================================================
    # Knowledge Stats
    # =========================================================================

    def get_knowledge_stats(self, db: Session) -> Dict[str, Any]:
        """Get statistics about the knowledge base"""
        total = db.query(func.count(CompanyKnowledge.id)).filter(
            CompanyKnowledge.store_id == self.store_id
        ).scalar() or 0

        active = db.query(func.count(CompanyKnowledge.id)).filter(
            CompanyKnowledge.store_id == self.store_id,
            CompanyKnowledge.is_active == True
        ).scalar() or 0

        by_type = {}
        type_counts = db.query(
            CompanyKnowledge.content_type,
            func.count(CompanyKnowledge.id)
        ).filter(
            CompanyKnowledge.store_id == self.store_id,
            CompanyKnowledge.is_active == True
        ).group_by(CompanyKnowledge.content_type).all()

        for content_type, count in type_counts:
            by_type[content_type] = count

        return {
            "total": total,
            "active": active,
            "by_type": by_type
        }
