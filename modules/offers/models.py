# --- Offer Model ---
class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[PG_UUID] = mapped_column(ForeignKey("request_posts.id"), nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    proposed_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Offer statuses:
    # "pending": Supplier made the offer/counter-offer, awaiting customer response
    # "accepted": Customer accepted this specific offer/counter-offer (leads to order)
    # "rejected": Customer rejected this specific offer/counter-offer
    # "cancelled_by_supplier": Supplier cancelled their own offer before customer action
    # "expired": Offer expired (e.g., customer didn't respond in time)
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "rejected", "cancelled_by_supplier", "expired", "countered", name="offer_statuses", create_type=True),
        server_default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    request_post: Mapped["RequestPost"] = relationship("RequestPost", back_populates="offers")
    supplier: Mapped["User"] = relationship("User", back_populates="offers")
    # One-to-one with Order: an offer can result in one order
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="offer", uselist=False, cascade="all, delete-orphan")