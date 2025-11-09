# --- User Model ---
class User(Base):
    __tablename__ = "users"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    role: Mapped[str] = mapped_column(Enum("customer", "supplier", "admin", "both", name="user_roles", create_type=True), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    surname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Using `func.now()` for `onupdate` timestamp.
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    status: Mapped[str] = mapped_column(Enum("active", "disabled", "pending", name="user_statuses", create_type=True), server_default="active", nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Business specific fields (for suppliers)
    business_phone_number: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    business_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    personal_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    requests: Mapped[List["RequestPost"]] = relationship("RequestPost", back_populates="customer", cascade="all, delete-orphan")
    offers: Mapped[List["Offer"]] = relationship("Offer", back_populates="supplier", cascade="all, delete-orphan")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="supplier", cascade="all, delete-orphan")
    customer_orders: Mapped[List["Order"]] = relationship("Order", foreign_keys="[Order.customer_id]", back_populates="customer", cascade="all, delete-orphan")
    supplier_orders: Mapped[List["Order"]] = relationship("Order", foreign_keys="[Order.supplier_id]", back_populates="supplier", cascade="all, delete-orphan")
    device_tokens: Mapped[List["DeviceToken"]] = relationship("DeviceToken", back_populates="user", cascade="all, delete-orphan")
    sent_notifications: Mapped[List["Notification"]] = relationship("Notification", foreign_keys="[Notification.sender_id]", back_populates="sender", cascade="all, delete-orphan")
    received_notifications: Mapped[List["Notification"]] = relationship("Notification", foreign_keys="[Notification.recipient_id]", back_populates="recipient", cascade="all, delete-orphan")
    verification_codes: Mapped[List["VerificationCode"]] = relationship("VerificationCode", back_populates="user", cascade="all, delete-orphan")
