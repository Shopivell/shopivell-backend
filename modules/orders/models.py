
# --- Order Model ---
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    request_id: Mapped[PG_UUID] = mapped_column(ForeignKey("request_posts.id"), nullable=False, unique=True)
    # The `offer_id` is now nullable. When a supplier directly accepts a request,
    # an 'internal' offer might be created, or you could simply link the order to the request directly
    # and not require an `offer_id` if no explicit counter-offer was involved.
    # However, keeping it non-nullable simplifies relationships, meaning even a direct accept creates an `Offer` object.
    offer_id: Mapped[PG_UUID] = mapped_column(ForeignKey("offers.id"), nullable=False, unique=True)
    customer_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    # Order status lifecycle
    # "placed": Order confirmed (customer accepted counter-offer, or supplier directly accepted request)
    # "processing": Supplier is preparing the order (e.g., baking the cake)
    # "shipped": Order is out for delivery
    # "delivered": Order has reached the customer
    # "completed": Order is delivered and potentially payment/review finalized
    # "cancelled_by_customer": Customer cancelled after placement
    # "cancelled_by_supplier": Supplier cancelled after placement
    status: Mapped[str] = mapped_column(
        Enum("placed", "processing", "shipped", "delivered", "completed", "cancelled", "cancelled_by_supplier", name="order_statuses", create_type=True),
        server_default="placed", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    delivery_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    delivery_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    request_post: Mapped["RequestPost"] = relationship("RequestPost", back_populates="order")
    # For `Offer`, changed `back_backref` to `back_populates` for modern SQLAlchemy
    offer: Mapped["Offer"] = relationship("Offer", back_populates="order")
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id], back_populates="customer_orders")
    supplier: Mapped["User"] = relationship("User", foreign_keys=[supplier_id], back_populates="supplier_orders")
