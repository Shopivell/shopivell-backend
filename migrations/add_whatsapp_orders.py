"""
Migration script to add WhatsApp orders tables.
Run with: python migrations/add_whatsapp_orders.py
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Creating whatsapp_orders table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_orders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                store_id UUID NOT NULL REFERENCES stores(id),
                order_number VARCHAR(50) NOT NULL UNIQUE,

                -- Customer details
                customer_phone VARCHAR(50) NOT NULL,
                customer_name VARCHAR(255),
                customer_address TEXT,

                -- Order details
                branch VARCHAR(100),
                items JSONB NOT NULL DEFAULT '[]',
                subtotal FLOAT DEFAULT 0.0,
                delivery_fee FLOAT DEFAULT 0.0,
                total_amount FLOAT DEFAULT 0.0,

                -- Collection method
                collection_method VARCHAR(50) DEFAULT 'delivery',
                delivery_distance_km FLOAT,

                -- Payment
                payment_method VARCHAR(50) DEFAULT 'cod',
                payment_provider VARCHAR(50),
                payment_status VARCHAR(50) DEFAULT 'pending',
                payment_reference VARCHAR(255),
                payment_poll_url TEXT,

                -- Order status
                status VARCHAR(50) DEFAULT 'pending',

                -- Timestamps
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                confirmed_at TIMESTAMP,
                delivered_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_store_id ON whatsapp_orders(store_id);
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_customer_phone ON whatsapp_orders(customer_phone);
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_order_number ON whatsapp_orders(order_number);
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_status ON whatsapp_orders(status);
        """))
        conn.commit()
        print("[OK] whatsapp_orders table created")

        print("Creating whatsapp_order_states table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_order_states (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                store_id UUID NOT NULL REFERENCES stores(id),
                customer_phone VARCHAR(50) NOT NULL,

                -- Current state
                current_state VARCHAR(50) DEFAULT 'idle',

                -- Cart
                cart_items JSONB DEFAULT '[]',
                selected_branch VARCHAR(100),

                -- Collected details
                customer_name VARCHAR(255),
                customer_address TEXT,
                collection_method VARCHAR(50),
                payment_method VARCHAR(50),

                -- Timestamps
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,

                UNIQUE(store_id, customer_phone)
            );

            CREATE INDEX IF NOT EXISTS ix_whatsapp_order_states_store_phone
                ON whatsapp_order_states(store_id, customer_phone);
        """))
        conn.commit()
        print("[OK] whatsapp_order_states table created")

        # Add missing columns to whatsapp_order_states if they don't exist
        print("Adding missing columns to whatsapp_order_states...")
        try:
            conn.execute(text("""
                ALTER TABLE whatsapp_order_states
                ADD COLUMN IF NOT EXISTS customer_phone_delivery VARCHAR(50),
                ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(50),
                ADD COLUMN IF NOT EXISTS payment_phone VARCHAR(50);
            """))
            conn.commit()
            print("[OK] Added missing columns")
        except Exception as e:
            print(f"[INFO] Columns may already exist: {e}")
            conn.rollback()

        print("\n[SUCCESS] Migration completed!")


if __name__ == "__main__":
    run_migration()
