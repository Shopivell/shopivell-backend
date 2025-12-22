from database import SessionLocal
from modules.whatsapp.models import CompanyKnowledge
from sqlalchemy import select

db = SessionLocal()
knowledge = db.execute(select(CompanyKnowledge)).scalars().all()

print(f"Total knowledge entries: {len(knowledge)}")
for i, item in enumerate(knowledge):
    print(f"\n--- Entry {i+1} ---")
    print(f"ID: {item.id}")
    print(f"Content preview: {item.content[:200]}...")
    print(f"Embedding type: {type(item.embedding)}")
    if hasattr(item.embedding, '__len__'):
        print(f"Embedding length: {len(item.embedding)}")
db.close()