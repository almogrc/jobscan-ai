import queue
import time

class LocalPubSub:
    """
    מחלקה שמדמה את הממשק של GCP Pub/Sub.
    היא מנהלת מילון של נושאים (Topics), כשכל נושא הוא בעצם תור עצמאי.
    """
    def __init__(self):
        # מילון שיחזיק את כל התורים שלנו
        # מפתח: שם הנושא (למשל 'urls-topic')
        # ערך: התור עצמו
        self._topics = {}

    def _get_or_create_topic(self, topic_name: str) -> queue.Queue:
        """פונקציית עזר פנימית שמביאה תור קיים או יוצרת חדש אם חסר"""
        if topic_name not in self._topics:
            self._topics[topic_name] = queue.Queue()
        return self._topics[topic_name]

    def publish(self, topic_name: str, message: dict):
        """
        מקביל לפעולת Publish ב-GCP.
        יכול לקבל כל סוג של מילון - URL, אובייקט משרה, וכו'.
        """
        q = self._get_or_create_topic(topic_name)
        q.put(message)
        # בפרודקשן היית מחזיר פה Message ID, אפשר לוותר כרגע

    def pull(self, topic_name: str, timeout: int = 2) -> dict:
        """
        מקביל למשיכת הודעות (Pull Subscription).
        ממתין להודעה עד שה-timeout נגמר, כדי לא לתקוע את התוכנית לנצח.
        """
        q = self._get_or_create_topic(topic_name)
        try:
            # מנסה למשוך הודעה מהתור
            message = q.get(timeout=timeout)
            return message
        except queue.Empty:
            # אם התור ריק אחרי ההמתנה, מחזירים כלום
            return None

    def acknowledge(self, topic_name: str):
        """
        (Ack) ב-GCP חייבים לאשר שההודעה טופלה כדי שלא תישלח שוב.
        כאן אנחנו מסמנים לתור המקומי שהמשימה הסתיימה.
        """
        q = self._get_or_create_topic(topic_name)
        q.task_done()