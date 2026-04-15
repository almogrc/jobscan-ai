import queue
import time

class LocalPubSub:
    def __init__(self):
        self._topics = {}

    def _get_or_create_topic(self, topic_name: str) -> queue.Queue:
        if topic_name not in self._topics:
            self._topics[topic_name] = queue.Queue()
        return self._topics[topic_name]

    def publish(self, topic_name: str, message: dict):
        q = self._get_or_create_topic(topic_name)
        q.put(message)

    def pull(self, topic_name: str, timeout: int = 2) -> dict:
        q = self._get_or_create_topic(topic_name)
        try:
            message = q.get(timeout=timeout)
            return message
        except queue.Empty:
            return None

    def acknowledge(self, topic_name: str): # sucsses
        q = self._get_or_create_topic(topic_name)
        q.task_done()
        
    def nack(self, topic_name: str, message: dict): # Crash
        self.publish(topic_name, message)