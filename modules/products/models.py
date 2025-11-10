# --- Product Model ---
from datetime import datetime


class Product(Base):
    __tablename__ = "products"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False) # Use Numeric for price for precision
    category: Mapped[str] = mapped_column(String, index=True, nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    supplier: Mapped["User"] = relationship("User", back_populates="products")
