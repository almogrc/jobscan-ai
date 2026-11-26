import os
import sys

# סידור נתיבים כדי שיזהה את התיקיות שלך
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from infrastructure.db.database import SessionLocal
from infrastructure.db.model import Job

def clear_jobs_table():
    db = SessionLocal()
    try:
        # מוחק את כל השורות מטבלת המשרות (Job)
        deleted_count = db.query(Job).delete()
        db.commit()
        print(f"✅ הדיבי נוקה בהצלחה! נמחקו {deleted_count} משרות ישנות/זבל.")
    except Exception as e:
        db.rollback()
        print(f"❌ שגיאה במחיקה: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_jobs_table()